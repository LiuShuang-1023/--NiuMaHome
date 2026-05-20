"""通勤精算调度器（map/engine.py）v0.5.3

职责：
  接收起点地址 + 目的地地址，调用高德/百度/腾讯 API 完成精确路径规划，
  结果写入 commute_store（永久库）。

策略：高德优先（amap_first）+ 腾讯兜底 + 百度最终兜底
  1. 先查 commute_store.get_stable_baseline() —— 已固化的稳定路线直接返回，不调 API
  2. 高德 geocode + 路径规划
  3. 高德失败 → 腾讯兜底（GCJ02 坐标系相同，效率最高）
  4. 腾讯失败 → 百度最终兜底
  5. 全部失败 → 返回失败原因（显示给用户）

精算结果写入 commute_store.record_precise()，由每日任务计算7日均值更新 baseline。
三地图协作可有效降低单一 provider 的配额压力。
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.models import CommuteMode, CommuteResult, CommuteSummary
from app.services.map.address_cleaner import (
    build_geocode_candidates,
    fallback_landmark_address,
    haversine_km,
)
from app.services.map.amap import amap_client
from app.services.map.baidu import baidu_client
from app.services.map.tencent_map import tencent_client
from app.services.storage.commute_store import commute_store


@dataclass
class CommuteResultWithReason:
    """通勤计算结果 + 失败原因（用于诊断和UI展示）"""
    summary: Optional[CommuteSummary]
    fail_reason: str = ""      # 空字符串=成功；否则是具体原因
    used_provider: str = ""    # "amap" / "baidu" / "stable_baseline"


class CommuteEngine:
    """通勤精算引擎（高德优先策略）"""

    def __init__(self):
        self._stats = self._fresh_stats()

    @staticmethod
    def _fresh_stats() -> dict:
        return {
            "total_attempted": 0,
            "stable_baseline_hit": 0,
            "amap_attempted": 0,
            "amap_success": 0,
            "tencent_attempted": 0,
            "tencent_success": 0,
            "baidu_attempted": 0,
            "baidu_success": 0,
            "fail_geocode": 0,
            "fail_route": 0,
            "fail_quota": 0,
        }

    def reset_stats(self):
        self._stats = self._fresh_stats()

    def get_stats(self) -> dict:
        return dict(self._stats)

    def _save_to_store(
        self,
        origin_address: str,
        dest_address: str,
        summary: CommuteSummary,
        provider: str,
    ):
        """精算结果写入永久 commute_store（从 results 列表按 mode 提取）"""
        for r in summary.results:
            mode = r.mode.value if hasattr(r.mode, "value") else str(r.mode)
            if r.duration_min and r.duration_min > 0:
                commute_store.record_precise(
                    origin=origin_address.strip(),
                    dest=dest_address.strip(),
                    mode=mode,
                    duration_min=r.duration_min,
                    provider=provider,
                )

    async def compute(
        self,
        origin_address: str,
        dest_address: str,
        city: str,
        modes: list[CommuteMode] | None = None,
        use_amap: bool = True,
        use_baidu: bool = True,
        use_tencent: bool = True,
        origin_community: str = "",
        origin_district: str = "",
        dest_landmark: str = "",
        bidirectional: bool = True,
    ) -> CommuteResultWithReason:
        """计算从 origin 到 dest 的多维精确通勤时长。

        bidirectional=True 时同时计算"家→公司"和"公司→家"两个方向，
        结果一起写入 CommuteSummary.results（各带 direction 字段）。

        优先级：
          1. commute_store 稳定基准（is_stable=1）→ 直接返回，不调 API
          2. 高德 API（amap_first 策略）
          3. 腾讯 API（高德失败兜底，GCJ02 坐标系相同，效率高）
          4. 百度 API（全部失败最终兜底）
          5. 全部失败 → 返回具体失败原因

        三地图协同策略：高德(5000/天) + 腾讯(10000/天) + 百度(30000/天)
        通过轮流兜底最大化每日可用配额，减少失败率。
        """
        modes = modes or [CommuteMode.TRANSIT, CommuteMode.RIDING, CommuteMode.WALKING]
        self._stats["total_attempted"] += 1

        # ===== Step 0: 已固化的稳定路线，直接用，不调 API =====
        stable = commute_store.get_stable_baseline(
            origin_address.strip(), dest_address.strip()
        )
        if stable and all(str(m) in stable for m in modes):
            logger.info(f"[engine] 稳定基准命中，跳过API: {origin_address[:20]} → {dest_address[:20]}")
            self._stats["stable_baseline_hit"] += 1
            results = []
            for m in modes:
                if str(m) in stable:
                    results.append(CommuteResult(
                        map_provider="stable_baseline",
                        mode=m,
                        duration_min=int(stable[str(m)][0]),
                        distance_km=0.0,
                        direction="home_to_work",
                        raw_response={"source": "stable_baseline", "sample_count": stable[str(m)][1]},
                    ))
            summary = self._build_summary(dest_address, results)
            return CommuteResultWithReason(summary=summary, used_provider="stable_baseline")

        # ===== Step 1: 构建地址候选列表 =====
        origin_candidates = build_geocode_candidates(
            raw_community=origin_community or origin_address,
            address=origin_address,
            city=city,
            district=origin_district,
        )
        if not origin_candidates:
            origin_candidates = [origin_address]

        dest_candidates = [dest_address]
        if dest_landmark:
            fb = fallback_landmark_address(dest_landmark, city)
            if fb and fb not in dest_candidates:
                dest_candidates.append(fb)

        # ===== Step 2: 高德优先 =====
        if use_amap and amap_client.is_available:
            self._stats["amap_attempted"] += 1
            amap_origin_res, amap_dest_res = await asyncio.gather(
                amap_client.geocode_with_fallback(origin_candidates, city),
                amap_client.geocode_with_fallback(dest_candidates, city),
            )
            amap_origin = amap_origin_res[0] if amap_origin_res else None
            amap_dest = amap_dest_res[0] if amap_dest_res else None

            if amap_origin and amap_dest:
                # 家→公司
                h2w = await self._amap_routes(amap_origin, amap_dest, city, modes, "home_to_work")
                # 公司→家（双向时反向再算一次）
                w2h = []
                if bidirectional:
                    w2h = await self._amap_routes(amap_dest, amap_origin, city, modes, "work_to_home")
                results = h2w + w2h
                if results:
                    summary = self._build_summary(dest_address, results)
                    self._stats["amap_success"] += 1
                    self._save_to_store(origin_address, dest_address, summary, "amap")
                    return CommuteResultWithReason(summary=summary, used_provider="amap")
                logger.info("[engine] 高德路径规划全失败，尝试腾讯兜底")

        # ===== Step 3: 腾讯兜底（GCJ02 坐标系与高德相同，geocode 可复用）=====
        if use_tencent and tencent_client.is_available:
            self._stats["tencent_attempted"] += 1
            tencent_origin_res, tencent_dest_res = await asyncio.gather(
                tencent_client.geocode_with_fallback(origin_candidates, city),
                tencent_client.geocode_with_fallback(dest_candidates, city),
            )
            tencent_origin = tencent_origin_res[0] if tencent_origin_res else None
            tencent_dest = tencent_dest_res[0] if tencent_dest_res else None

            if tencent_origin and tencent_dest:
                h2w = await self._tencent_routes(tencent_origin, tencent_dest, city, modes, "home_to_work")
                w2h = []
                if bidirectional:
                    w2h = await self._tencent_routes(tencent_dest, tencent_origin, city, modes, "work_to_home")
                results = h2w + w2h
                if results:
                    summary = self._build_summary(dest_address, results)
                    self._stats["tencent_success"] += 1
                    self._save_to_store(origin_address, dest_address, summary, "tencent")
                    return CommuteResultWithReason(summary=summary, used_provider="tencent")
                logger.info("[engine] 腾讯路径规划全失败，尝试百度兜底")

        # ===== Step 4: 百度最终兜底 =====
        if use_baidu and baidu_client.is_available:
            self._stats["baidu_attempted"] += 1
            baidu_origin_res, baidu_dest_res = await asyncio.gather(
                baidu_client.geocode_with_fallback(origin_candidates, city),
                baidu_client.geocode_with_fallback(dest_candidates, city),
            )
            baidu_origin = baidu_origin_res[0] if baidu_origin_res else None
            baidu_dest = baidu_dest_res[0] if baidu_dest_res else None

            if baidu_origin and baidu_dest:
                h2w = await self._baidu_routes(baidu_origin, baidu_dest, city, modes, "home_to_work")
                w2h = []
                if bidirectional:
                    w2h = await self._baidu_routes(baidu_dest, baidu_origin, city, modes, "work_to_home")
                results = h2w + w2h
                if results:
                    summary = self._build_summary(dest_address, results)
                    self._stats["baidu_success"] += 1
                    self._save_to_store(origin_address, dest_address, summary, "baidu")
                    return CommuteResultWithReason(summary=summary, used_provider="baidu")

        # ===== Step 5: 全部失败，分类原因 =====
        return self._diagnose_failure(use_amap, use_tencent, use_baidu)

    # ── 路径规划助手 ─────────────────────────────────────
    async def _amap_routes(
        self, origin, dest, city, modes,
        direction: str = "home_to_work",
    ) -> list[CommuteResult]:
        tasks = []
        for m in modes:
            if m == CommuteMode.TRANSIT:
                tasks.append(amap_client.transit(origin, dest, city))
            elif m == CommuteMode.RIDING:
                tasks.append(amap_client.riding(origin, dest))
            elif m == CommuteMode.WALKING:
                tasks.append(amap_client.walking(origin, dest))
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in results_raw if isinstance(r, CommuteResult)]
        for r in results:
            r.direction = direction
        return results

    async def _tencent_routes(
        self, origin, dest, city, modes,
        direction: str = "home_to_work",
    ) -> list[CommuteResult]:
        tasks = []
        for m in modes:
            if m == CommuteMode.TRANSIT:
                tasks.append(tencent_client.transit(origin, dest, city))
            elif m == CommuteMode.RIDING:
                tasks.append(tencent_client.riding(origin, dest))
            elif m == CommuteMode.WALKING:
                tasks.append(tencent_client.walking(origin, dest))
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in results_raw if isinstance(r, CommuteResult)]
        for r in results:
            r.direction = direction
        return results

    async def _baidu_routes(
        self, origin, dest, city, modes,
        direction: str = "home_to_work",
    ) -> list[CommuteResult]:
        tasks = []
        for m in modes:
            if m == CommuteMode.TRANSIT:
                tasks.append(baidu_client.transit(origin, dest, city))
            elif m == CommuteMode.RIDING:
                tasks.append(baidu_client.riding(origin, dest))
            elif m == CommuteMode.WALKING:
                tasks.append(baidu_client.walking(origin, dest))
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in results_raw if isinstance(r, CommuteResult)]
        for r in results:
            r.direction = direction
        return results

    @staticmethod
    def _build_summary(dest_address: str, results: list[CommuteResult]) -> CommuteSummary:
        # best_duration_min 只取"家→公司"方向的最快，用于排序（避免双向平均）
        h2w = [r for r in results if r.direction == "home_to_work"]
        all_for_best = h2w if h2w else results
        best = min((r.duration_min for r in all_for_best), default=0)
        transit_durations = [r.duration_min for r in h2w if r.mode == CommuteMode.TRANSIT]
        avg_transit = sum(transit_durations) // len(transit_durations) if transit_durations else None
        return CommuteSummary(
            listing_id="",
            destination_address=dest_address,
            results=results,
            best_duration_min=best,
            avg_transit_min=avg_transit,
        )

    def _diagnose_failure(self, use_amap: bool, use_tencent: bool, use_baidu: bool) -> CommuteResultWithReason:
        """根据三个 client 的状态生成可读的失败原因"""
        amap_diag = amap_client.get_diagnostics()
        tencent_diag = tencent_client.get_diagnostics()
        baidu_diag = baidu_client.get_diagnostics()

        amap_quota = use_amap and amap_diag.get("quota_exhausted")
        tencent_quota = use_tencent and tencent_diag.get("quota_exhausted")
        baidu_quota = use_baidu and (baidu_diag.get("concurrency_limit_hit") or baidu_diag.get("quota_exhausted"))

        if amap_quota and tencent_quota and baidu_quota:
            self._stats["fail_quota"] += 1
            return CommuteResultWithReason(
                summary=None,
                fail_reason="三家地图 API 今日配额均已耗尽，请明日 0 点后继续",
            )
        if amap_quota and tencent_quota:
            self._stats["fail_quota"] += 1
            return CommuteResultWithReason(
                summary=None,
                fail_reason="高德+腾讯今日配额耗尽，正在用百度兜底中，请稍候",
            )
        if amap_quota:
            self._stats["fail_quota"] += 1
            return CommuteResultWithReason(
                summary=None,
                fail_reason="高德每日配额耗尽，已自动切换腾讯/百度兜底，请稍候重试",
            )
        if baidu_quota:
            return CommuteResultWithReason(
                summary=None,
                fail_reason="百度并发配额超限，请稍后点'继续测算'",
            )
        if use_amap and amap_diag.get("key_invalid"):
            return CommuteResultWithReason(summary=None, fail_reason="高德 Key 无效，请检查配置")
        if use_tencent and tencent_diag.get("key_invalid"):
            return CommuteResultWithReason(summary=None, fail_reason="腾讯地图 Key 无效，请检查配置")
        if use_baidu and baidu_diag.get("key_invalid"):
            return CommuteResultWithReason(summary=None, fail_reason="百度 AK 错误，请检查配置")

        self._stats["fail_geocode"] += 1
        return CommuteResultWithReason(
            summary=None,
            fail_reason="无法解析房源具体位置（小区名过于特殊或不在地图库中）",
        )


commute_engine = CommuteEngine()
