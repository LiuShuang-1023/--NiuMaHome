"""百度地图 Web 服务 API 封装

文档: https://lbsyun.baidu.com/index.php?title=webapi
SN 校验文档: https://lbsyun.baidu.com/index.php?title=lbscloud/api/appendix

注意：
- 百度坐标是 BD09，与高德 GCJ02 不同
- 「服务端AK」+ SN 校验：每次请求需要算签名 sn
- 「服务端AK」+ IP 白名单：不需要 sn，但 IP 必须在白名单内
- 同一个 AK 只能选一种校验方式
"""
import hashlib
import time
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
from loguru import logger

from app.core.config import settings
from app.models import CommuteMode, CommuteResult, MapProvider

BAIDU_BASE = "https://api.map.baidu.com"

# 百度错误码（status 字段）
BAIDU_STATUS_HINTS = {
    0: "成功",
    1: "服务器内部错误",
    2: "请求参数非法",
    3: "权限校验失败",
    4: "配额校验失败",
    5: "AK 不存在或不正确",
    101: "服务禁用",
    102: "不通过白名单或签名错误（关键！）",
    200: "APP 不存在，AK 错误",
    201: "APP 被用户自己禁用",
    202: "APP 被管理员禁用",
    211: "APP 被删除",
    240: "APP 类型不被支持",
    301: "永久配额超限",
    302: "天配额超限",
    401: "当前并发量已经超过约定的并发配额",
}


class BaiduMapClient:
    """百度地图客户端（支持 SN 签名 + IP 白名单两种鉴权）"""

    def __init__(self):
        self.ak = settings.BAIDU_AK
        self.sk = (settings.BAIDU_SK or "").strip()
        self.client = httpx.AsyncClient(timeout=10.0)
        self._diag_count_fail = 0  # 失败诊断计数
        self._quota_exhausted = False  # 配额超限标志（status=301/302）
        self._concurrency_limit_hit = False  # 并发超限标志（status=401）
        self._key_invalid = False  # AK 错误标志（status=200/5）

        if self.ak:
            mode = "SN签名" if self.sk else "白名单"
            logger.info(f"百度地图: AK={self.ak[:6]}...{self.ak[-4:]} 鉴权方式={mode}")

    @property
    def use_sn(self) -> bool:
        return bool(self.sk)

    @property
    def is_available(self) -> bool:
        """当前是否可用"""
        return (bool(self.ak)
                and not self._quota_exhausted
                and not self._key_invalid
                and not self._concurrency_limit_hit)

    def reset_quota_flag(self):
        """手动重置配额超限标志（每日 0 点重置）"""
        self._quota_exhausted = False
        self._concurrency_limit_hit = False
        self._key_invalid = False
        self._diag_count_fail = 0

    async def close(self):
        await self.client.aclose()

    # ============================================================
    # SN 签名计算
    # ============================================================
    def _calc_sn(self, path: str, params: dict) -> str:
        """计算百度 SN 签名

        算法（百度官方）:
            1. 把 params 按 key 字典序排序
            2. 拼接成 path?k1=v1&k2=v2 形式（值需要 urlencode）
            3. 末尾拼接 SK
            4. 整个字符串再 urlencode 一次
            5. MD5 hex 小写

        Args:
            path: 请求路径，如 "/geocoding/v3/"（必须以 / 开头）
            params: 不含 sn 的参数字典（含 ak）

        Returns:
            32位小写 md5 字符串
        """
        # 1. 按 key 排序
        sorted_keys = sorted(params.keys())
        # 2. urlencode 拼接（quote_via=quote 保证 safe 字符也编码）
        query = "&".join(
            f"{k}={quote(str(params[k]), safe='')}" for k in sorted_keys
        )
        # 3. raw = path + ? + query + SK
        raw = f"{path}?{query}{self.sk}"
        # 4. 再整体 urlencode
        encoded = quote(raw, safe="")
        # 5. md5
        return hashlib.md5(encoded.encode("utf-8")).hexdigest()

    def _build_url_and_params(self, path: str, params: dict) -> tuple[str, dict]:
        """组装最终请求 URL 和参数（自动加 ak 和 sn）"""
        full = {"ak": self.ak, **params, "output": "json"}
        if self.use_sn:
            full["sn"] = self._calc_sn(path, full)
        return f"{BAIDU_BASE}{path}", full

    async def _get(self, path: str, params: dict, label: str = "") -> Optional[dict]:
        """统一 GET 请求 + 错误诊断"""
        if not self.ak:
            return None
        # 配额耗尽 / Key 无效 / 并发超限：直接短路返回
        if self._quota_exhausted or self._key_invalid or self._concurrency_limit_hit:
            return None
        url, full_params = self._build_url_and_params(path, params)
        try:
            r = await self.client.get(url, params=full_params)
            data = r.json()
        except Exception as e:
            logger.exception(f"百度 {label} 请求异常: {e}")
            return None

        status = data.get("status")
        if status != 0:
            hint = BAIDU_STATUS_HINTS.get(status, data.get("message", "未知错误"))
            self._diag_count_fail += 1

            # 关键错误：锁住后续请求
            if status in (301, 302):
                logger.error(f"⚠️ 百度配额超限 (status={status} {hint})，本进程后续请求短路")
                self._quota_exhausted = True
                return None
            if status == 401:
                logger.error(f"⚠️ 百度并发配额超限 (status=401)，本进程后续请求短路")
                self._concurrency_limit_hit = True
                return None
            if status in (5, 200, 240):
                logger.error(f"⚠️ 百度 AK/应用类型错误 (status={status} {hint})，本进程后续请求短路")
                self._key_invalid = True
                return None

            # 前几次失败时打详细日志，避免刷屏
            if self._diag_count_fail <= 5:
                logger.warning(
                    f"百度 {label} 失败 status={status} ({hint}) | "
                    f"message={data.get('message')} | sn模式={self.use_sn}"
                )
                if status == 102:
                    logger.warning(
                        "  → status=102 通常是 SN 签名错误或 IP 不在白名单。"
                        "请检查 BAIDU_SK 是否正确，或在百度控制台改成 IP 白名单 0.0.0.0/0"
                    )
            return None
        return data

    # ============================================================
    # 业务接口
    # ============================================================
    async def geocode(self, address: str, city: str = "") -> Optional[tuple[float, float]]:
        """地址 → BD09 经纬度"""
        params = {"address": address}
        if city:
            params["city"] = city
        data = await self._get("/geocoding/v3/", params, label="geocode")
        if data and data.get("result"):
            loc = data["result"]["location"]
            return float(loc["lng"]), float(loc["lat"])
        return None

    # v0.3.0.1: 百度 geocode 不可信 level（兜底匹配，非精确命中）
    BAIDU_FUZZY_LEVELS = {"省", "城市", "区县"}
    BAIDU_MIN_CONFIDENCE = 30  # confidence < 30 视为兜底

    async def geocode_with_level(
        self, address: str, city: str = "",
    ) -> Optional[tuple[tuple[float, float], str, int, str]]:
        """地址 → (BD09 坐标, level, confidence, 准确度判断)

        百度 geocode 返回的 confidence 0-100：
            > 80: 门牌号级
            50-80: 街道/POI 级
            20-50: 区县级（兜底）
            < 20: 城市级（强兜底）
        level 字段：
            旅游景点/购物/教育/...：精确 POI
            城市/区县/省：兜底
        """
        params = {"address": address}
        if city:
            params["city"] = city
        data = await self._get("/geocoding/v3/", params, label="geocode")
        if not (data and data.get("result")):
            return None
        r = data["result"]
        loc = r.get("location") or {}
        if "lng" not in loc or "lat" not in loc:
            return None
        coord = (float(loc["lng"]), float(loc["lat"]))
        level = r.get("level", "") or ""
        confidence = int(r.get("confidence", 0) or 0)
        return coord, level, confidence, address

    async def geocode_with_fallback(
        self,
        candidates: list[str],
        city: str = "",
    ) -> Optional[tuple[tuple[float, float], str]]:
        """按候选列表依次尝试 geocode

        v0.2.1.1: 加坐标合理性验证。百度 geocode 偶尔会把含特殊符号的小区名
        fuzzy 匹配到几十公里外的同名地点（实测 "广州独栋·MI 米谷公寓"被
        匹配到白云区），所以验证返回坐标是否在城市范围内。
        """
        from app.services.map.address_cleaner import is_coord_in_city

        for addr in candidates:
            coord = await self.geocode(addr, city)
            if not coord:
                continue
            if not is_coord_in_city(coord, city):
                logger.warning(
                    f"[geocode 验证失败] 百度 '{addr}' 返回 {coord} 不在 {city} 范围内，跳过"
                )
                continue
            return coord, addr
        return None

    async def gcj02_to_bd09(self, lng: float, lat: float) -> Optional[tuple[float, float]]:
        """高德 GCJ02 → 百度 BD09"""
        params = {"coords": f"{lng},{lat}", "from": 3, "to": 5}
        data = await self._get("/geoconv/v1/", params, label="geoconv")
        if data and data.get("result"):
            p = data["result"][0]
            return float(p["x"]), float(p["y"])
        return None

    async def _direction(
        self,
        mode: str,
        origin: tuple[float, float],
        dest: tuple[float, float],
        region: str = "",
    ) -> Optional[dict]:
        """统一的路径规划（注意百度坐标顺序是 lat,lng）"""
        path = f"/directionlite/v1/{mode}"
        params = {
            "origin": f"{origin[1]},{origin[0]}",
            "destination": f"{dest[1]},{dest[0]}",
        }
        if mode == "transit" and region:
            params["region"] = region
        data = await self._get(path, params, label=mode)
        return data.get("result") if data else None

    async def transit(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str,
    ) -> Optional[CommuteResult]:
        result = await self._direction("transit", origin, dest, region=city)
        if not result or not result.get("routes"):
            return None
        best = result["routes"][0]
        return CommuteResult(
            map_provider=MapProvider.BAIDU,
            mode=CommuteMode.TRANSIT,
            duration_min=max(1, int(best.get("duration", 0)) // 60),
            distance_km=round(int(best.get("distance", 0)) / 1000, 2),
            transfers=len(best.get("steps", [])),
            raw_response={},
        )

    async def riding(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        result = await self._direction("riding", origin, dest)
        if not result or not result.get("routes"):
            return None
        best = result["routes"][0]
        return CommuteResult(
            map_provider=MapProvider.BAIDU,
            mode=CommuteMode.RIDING,
            duration_min=max(1, int(best.get("duration", 0)) // 60),
            distance_km=round(int(best.get("distance", 0)) / 1000, 2),
            raw_response={},
        )

    async def walking(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        result = await self._direction("walking", origin, dest)
        if not result or not result.get("routes"):
            return None
        best = result["routes"][0]
        return CommuteResult(
            map_provider=MapProvider.BAIDU,
            mode=CommuteMode.WALKING,
            duration_min=max(1, int(best.get("duration", 0)) // 60),
            distance_km=round(int(best.get("distance", 0)) / 1000, 2),
            raw_response={},
        )

    def get_diagnostics(self) -> dict:
        return {
            "ak_configured": bool(self.ak),
            "sn_mode": self.use_sn,
            "fail_count": self._diag_count_fail,
            "quota_exhausted": self._quota_exhausted,
            "concurrency_limit_hit": self._concurrency_limit_hit,
            "key_invalid": self._key_invalid,
        }


baidu_client = BaiduMapClient()
