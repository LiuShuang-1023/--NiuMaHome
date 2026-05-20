"""高德地图 Web 服务 API 封装

文档: https://lbs.amap.com/api/webservice/summary
个人开发者免费配额: 每日 5000 次, QPS 200
"""
import asyncio
from typing import Optional

import httpx
from loguru import logger

from app.core.config import settings
from app.models import CommuteMode, CommuteResult, MapProvider
from app.services.storage.daily_cache import daily_cache

AMAP_BASE = "https://restapi.amap.com/v3"
AMAP_BASE_V5 = "https://restapi.amap.com/v5"

# 高德错误码（关键的）
AMAP_ERROR_HINTS = {
    "10000": "成功",
    "10001": "Key 无效或被禁用",
    "10003": "请求超出配额",
    "10004": "QPS 超限（每秒查询数过多）",
    "10005": "IP 白名单出错",
    "10009": "请求 Key 与绑定平台不符",
    "10021": "单用户单接口 QPS 超限（个人 Key 限制 3 QPS）",
    "10044": "请求超出每日配额",
    "20000": "请求参数非法",
}


class AmapClient:
    """高德地图客户端（带缓存 + 限流退避）"""

    def __init__(self):
        self.key = settings.AMAP_KEY
        self.client = httpx.AsyncClient(timeout=10.0)

        # 全局串行锁（高德个人 Key 单接口 QPS = 3，串行最稳）
        self._sem = asyncio.Semaphore(1)

        # 上次请求时间，确保两次请求间隔 >= MIN_INTERVAL
        self._last_request_time = 0.0
        self.MIN_INTERVAL = 0.35  # 350ms 间隔，约 2.8 QPS，留余量

        # 地理编码缓存：address -> (lng, lat)
        self._geo_cache: dict[str, Optional[tuple[float, float]]] = {}

        # 路径缓存：(mode, ox, oy, dx, dy) -> CommuteResult
        self._route_cache: dict[tuple, Optional[CommuteResult]] = {}

        # 限流次数计数（用于诊断）
        self._rate_limit_count = 0

        # 配额耗尽标志（infocode=10044 后置 True，本进程内不再尝试）
        self._quota_exhausted = False
        # Key 无效标志（infocode=10001 后置 True）
        self._key_invalid = False

    @property
    def is_available(self) -> bool:
        """当前是否可用（未配额耗尽 / Key 有效 / 已配置）"""
        return bool(self.key) and not self._quota_exhausted and not self._key_invalid

    def reset_quota_flag(self):
        """手动重置配额耗尽标志（每日 0 点重置 / 用户切 Key 后调用）"""
        self._quota_exhausted = False
        self._key_invalid = False
        self._rate_limit_count = 0

    async def close(self):
        await self.client.aclose()

    async def _throttle(self):
        """节流：保证两次请求间隔 >= MIN_INTERVAL"""
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_INTERVAL:
            await asyncio.sleep(self.MIN_INTERVAL - elapsed)
        self._last_request_time = time.time()

    async def _get(self, url: str, params: dict, label: str = "") -> Optional[dict]:
        """统一请求入口（带限流 + 错误诊断 + 自动重试）"""
        # 配额已耗尽 / Key 无效：直接短路返回 None，不浪费请求
        if self._quota_exhausted or self._key_invalid:
            return None

        async with self._sem:
            await self._throttle()

            for attempt in range(3):
                try:
                    r = await self.client.get(url, params=params)
                    data = r.json()
                    info_code = str(data.get("infocode") or "")

                    # 限流处理：触发限流时退避重试
                    if info_code in ("10021", "10004", "10003"):
                        self._rate_limit_count += 1
                        wait = 0.5 * (attempt + 1) + 0.5  # 1秒/1.5秒/2秒
                        if self._rate_limit_count <= 5:
                            logger.warning(
                                f"⚠️ 高德 {label} 限流 (infocode={info_code})，{wait:.1f}秒后重试"
                            )
                        await asyncio.sleep(wait)
                        continue

                    # 配额超限不重试，且锁住后续请求
                    if info_code == "10044":
                        logger.error("⚠️ 高德每日配额已耗尽，本进程后续请求短路返回")
                        self._quota_exhausted = True
                        return None

                    # Key 无效不重试，锁住
                    if info_code == "10001":
                        logger.error("⚠️ 高德 Key 无效，本进程后续请求短路返回")
                        self._key_invalid = True
                        return None

                    # 失败诊断
                    status = data.get("status")
                    if status != "1" and label and self._rate_limit_count <= 5:
                        hint = AMAP_ERROR_HINTS.get(info_code, data.get("info", ""))
                        logger.warning(
                            f"高德 {label} 失败 status={status} infocode={info_code} info={hint}"
                        )

                    return data
                except Exception as e:
                    logger.warning(f"高德 {label} 异常: {e}")
                    if attempt < 2:
                        await asyncio.sleep(0.5)
                    else:
                        return None
            return None

    async def geocode(self, address: str, city: str = "") -> Optional[tuple[float, float]]:
        """地址 → 经纬度（内存缓存 + 每日持久缓存，命中时跳过锁）"""
        if not self.key:
            return None

        key = f"{city}|{address}"
        # 1. 内存缓存（最快）
        if key in self._geo_cache:
            return self._geo_cache[key]

        # 2. 每日持久缓存（跨会话复用，今日内不重复调 API）
        cached = daily_cache.get_geocode(city, address, provider="amap")
        if cached is not None:
            lng, lat, _, _ = cached
            result = (lng, lat)
            self._geo_cache[key] = result
            return result

        # 3. 调高德 API
        data = await self._get(
            f"{AMAP_BASE}/geocode/geo",
            {"key": self.key, "address": address, "city": city},
            label="geocode",
        )
        result = None
        if data and data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]
            lng, lat = loc.split(",")
            result = (float(lng), float(lat))
            # 写入每日缓存
            daily_cache.save_geocode(city, address, float(lng), float(lat), provider="amap")

        self._geo_cache[key] = result
        return result

    # v0.3.0.1: 高德 geocode 精确度等级
    # 这些是兜底匹配（地址不存在或不准确时高德返回的城市/区中心点等）
    # 业务侧应判定为"未真正命中"
    AMAP_FUZZY_LEVELS = {"省", "市", "区县", "乡镇", "街道"}

    async def geocode_with_level(
        self, address: str, city: str = "",
    ) -> Optional[tuple[tuple[float, float], str, str]]:
        """地址 → (坐标, level, formatted_address)（内存缓存 + 每日持久缓存）"""
        if not self.key:
            return None

        level_key = f"__level__{city}|{address}"
        # 1. 内存缓存
        if level_key in self._geo_cache:
            cached = self._geo_cache[level_key]
            return cached  # type: ignore[return-value]

        # 2. 每日持久缓存
        cached_daily = daily_cache.get_geocode(city, address, provider="amap_level")
        if cached_daily is not None:
            lng, lat, level, hit_addr = cached_daily
            result = ((lng, lat), level or "", hit_addr or "")
            self._geo_cache[level_key] = result
            return result

        # 3. 调高德 API
        data = await self._get(
            f"{AMAP_BASE}/geocode/geo",
            {"key": self.key, "address": address, "city": city},
            label="geocode",
        )
        result = None
        if data and data.get("status") == "1" and data.get("geocodes"):
            g = data["geocodes"][0]
            loc = g.get("location", "")
            if loc and "," in loc:
                lng, lat = loc.split(",")
                coord = (float(lng), float(lat))
                level = g.get("level", "") or ""
                formatted = g.get("formatted_address", "") or ""
                result = (coord, level, formatted)
                daily_cache.save_geocode(
                    city, address, float(lng), float(lat),
                    level=level, hit_addr=formatted, provider="amap_level",
                )

        self._geo_cache[level_key] = result
        return result

    async def geocode_with_fallback(
        self,
        candidates: list[str],
        city: str = "",
    ) -> Optional[tuple[tuple[float, float], str]]:
        """按候选列表依次尝试 geocode，返回 (坐标, 命中的候选)

        v0.2.1.1: 加坐标合理性验证。geocode 返回的坐标若不在 city 范围内
        （比如百度对 "MI 米谷公寓" fuzzy 匹配到白云区），视为失败继续下一级。

        Args:
            candidates: 候选地址列表（已按优先级排序）
            city: 城市名（用于辅助 geocode + 验证坐标范围）

        Returns:
            (lng, lat), 命中的地址字符串。全部失败返回 None
        """
        from app.services.map.address_cleaner import is_coord_in_city

        for addr in candidates:
            coord = await self.geocode(addr, city)
            if not coord:
                continue
            if not is_coord_in_city(coord, city):
                logger.warning(
                    f"[geocode 验证失败] 高德 '{addr}' 返回 {coord} 不在 {city} 范围内，跳过"
                )
                continue
            return coord, addr
        return None

    async def transit(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str,
    ) -> Optional[CommuteResult]:
        """公共交通"""
        if not self.key:
            return None

        cache_key = ("transit", round(origin[0], 4), round(origin[1], 4),
                     round(dest[0], 4), round(dest[1], 4), city)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        data = await self._get(
            f"{AMAP_BASE}/direction/transit/integrated",
            {
                "key": self.key,
                "origin": f"{origin[0]},{origin[1]}",
                "destination": f"{dest[0]},{dest[1]}",
                "city": city,
                "strategy": 0,
            },
            label="transit",
        )
        result: Optional[CommuteResult] = None
        if data and data.get("status") == "1" and data.get("route", {}).get("transits"):
            best = data["route"]["transits"][0]
            duration_s = int(best.get("duration", 0))
            distance_m = int(best.get("distance", 0))
            transfers = len(best.get("segments", []))
            result = CommuteResult(
                map_provider=MapProvider.AMAP,
                mode=CommuteMode.TRANSIT,
                duration_min=max(1, duration_s // 60),
                distance_km=round(distance_m / 1000, 2),
                transfers=transfers,
                raw_response={},  # 不缓存大对象，节省内存
            )
        self._route_cache[cache_key] = result
        return result

    async def riding(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        """骑行"""
        if not self.key:
            return None

        cache_key = ("riding", round(origin[0], 4), round(origin[1], 4),
                     round(dest[0], 4), round(dest[1], 4))
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        data = await self._get(
            f"{AMAP_BASE_V5}/direction/bicycling",
            {
                "key": self.key,
                "origin": f"{origin[0]},{origin[1]}",
                "destination": f"{dest[0]},{dest[1]}",
            },
            label="riding",
        )
        result: Optional[CommuteResult] = None
        if data:
            paths = (data.get("data") or {}).get("paths") or data.get("route", {}).get("paths") or []
            if paths:
                p = paths[0]
                result = CommuteResult(
                    map_provider=MapProvider.AMAP,
                    mode=CommuteMode.RIDING,
                    duration_min=max(1, int(p.get("duration", 0)) // 60),
                    distance_km=round(int(p.get("distance", 0)) / 1000, 2),
                    raw_response={},
                )
        self._route_cache[cache_key] = result
        return result

    async def walking(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        """步行"""
        if not self.key:
            return None

        cache_key = ("walking", round(origin[0], 4), round(origin[1], 4),
                     round(dest[0], 4), round(dest[1], 4))
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        data = await self._get(
            f"{AMAP_BASE}/direction/walking",
            {
                "key": self.key,
                "origin": f"{origin[0]},{origin[1]}",
                "destination": f"{dest[0]},{dest[1]}",
            },
            label="walking",
        )
        result: Optional[CommuteResult] = None
        if data and data.get("status") == "1" and data.get("route", {}).get("paths"):
            p = data["route"]["paths"][0]
            result = CommuteResult(
                map_provider=MapProvider.AMAP,
                mode=CommuteMode.WALKING,
                duration_min=max(1, int(p.get("duration", 0)) // 60),
                distance_km=round(int(p.get("distance", 0)) / 1000, 2),
                raw_response={},
            )
        self._route_cache[cache_key] = result
        return result

    def get_diagnostics(self) -> dict:
        """获取诊断信息"""
        return {
            "geo_cache_size": len(self._geo_cache),
            "route_cache_size": len(self._route_cache),
            "rate_limit_hits": self._rate_limit_count,
            "quota_exhausted": self._quota_exhausted,
            "key_invalid": self._key_invalid,
        }


amap_client = AmapClient()
