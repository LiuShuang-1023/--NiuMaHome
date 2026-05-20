"""腾讯地图 Web 服务 API 封装

文档: https://lbs.qq.com/service/webService/webServiceGuide/webServiceOverview
个人开发者免费配额: 每日 10000 次, QPS 5

注意：
  - 腾讯坐标系是 GCJ02（与高德一致，但与百度 BD09 不同）
  - 鉴权方式：key（必填） + sig（可选，WebServiceKey 开启 IP 校验时需要）
  - 路径规划接口：
    * 公交路径规划 /ws/direction/v1/transit/
    * 骑行路径规划 /ws/direction/v1/bicycling/
    * 步行路径规划 /ws/direction/v1/walking/
    * 驾车路径规划 /ws/direction/v1/driving/
  - Geocode:     /ws/geocoder/v1/
"""
import asyncio
import hashlib
from typing import Optional
from urllib.parse import urlencode, quote

import httpx
from loguru import logger

from app.core.config import settings
from app.models import CommuteMode, CommuteResult, MapProvider

TENCENT_BASE = "https://apis.map.qq.com"

# 腾讯地图错误码
TENCENT_STATUS_HINTS = {
    0: "成功",
    110: "请求来源未被授权（key 绑定域名/IP 校验失败）",
    111: "签名验证失败（sig 错误）",
    120: "key 非法",
    121: "key 未开启相应服务",
    122: "每日调用量超出限制",
    123: "签名校验参数缺少（需要 sig 参数）",
    311: "value 非法",
    306: "请求有护栏，信息安全",
    347: "查询条件缺少必要参数",
    351: "服务内部错误",
    380: "请求 referer 非法",
}


class TencentMapClient:
    """腾讯地图客户端（带配额保护 + 节流）"""

    def __init__(self):
        self.key = settings.TENCENT_KEY
        self.client = httpx.AsyncClient(timeout=10.0)

        # 腾讯免费版 QPS=5，用信号量控制并发
        self._sem = asyncio.Semaphore(2)
        self._last_request_time = 0.0
        self.MIN_INTERVAL = 0.22  # ~4.5 QPS，留余量

        # 状态标志
        self._quota_exhausted = False   # status=122
        self._key_invalid = False       # status=120/121

        # 内存缓存
        self._geo_cache: dict[str, Optional[tuple[float, float]]] = {}
        self._route_cache: dict[tuple, Optional[CommuteResult]] = {}

        if self.key:
            logger.info(f"腾讯地图: KEY={self.key[:6]}...{self.key[-4:]}")
        else:
            logger.warning("腾讯地图: TENCENT_KEY 未配置，该 provider 不可用")

    @property
    def is_available(self) -> bool:
        return bool(self.key) and not self._quota_exhausted and not self._key_invalid

    def reset_quota_flag(self):
        self._quota_exhausted = False
        self._key_invalid = False

    def get_diagnostics(self) -> dict:
        return {
            "available": self.is_available,
            "quota_exhausted": self._quota_exhausted,
            "key_invalid": self._key_invalid,
        }

    async def close(self):
        await self.client.aclose()

    # ── 内部工具 ─────────────────────────────────────────────────

    async def _throttle(self):
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_INTERVAL:
            await asyncio.sleep(self.MIN_INTERVAL - elapsed)
        self._last_request_time = time.time()

    async def _get(self, path: str, params: dict, label: str = "") -> Optional[dict]:
        """统一 GET 请求 + 状态码诊断"""
        if not self.is_available:
            return None

        params = {"key": self.key, "output": "json", **params}

        async with self._sem:
            await self._throttle()
            url = f"{TENCENT_BASE}{path}"
            try:
                r = await self.client.get(url, params=params)
                data = r.json()
            except Exception as e:
                logger.warning(f"腾讯地图 {label} 请求异常: {e}")
                return None

        status = data.get("status")
        if status != 0:
            hint = TENCENT_STATUS_HINTS.get(status, data.get("message", "未知"))
            if status == 122:
                logger.error(f"⚠️ 腾讯地图每日配额耗尽 (status=122)，本进程后续请求短路")
                self._quota_exhausted = True
                return None
            if status in (120, 121):
                logger.error(f"⚠️ 腾讯地图 Key 无效 (status={status} {hint})，本进程后续请求短路")
                self._key_invalid = True
                return None
            logger.warning(f"腾讯地图 {label} 失败 status={status} hint={hint}")
            return None

        return data

    # ── 地理编码 ─────────────────────────────────────────────────

    async def geocode(self, address: str, city: str = "") -> Optional[tuple[float, float]]:
        """地址 → (lng, lat)  GCJ02 坐标"""
        if not self.is_available:
            return None
        cache_key = f"{city}|{address}"
        if cache_key in self._geo_cache:
            return self._geo_cache[cache_key]

        # 腾讯地图：address 带城市前缀比用 region 参数更稳定
        full_address = f"{city}{address}" if city and not address.startswith(city) else address
        params = {"address": full_address}

        data = await self._get("/ws/geocoder/v1/", params, label=f"geocode({full_address[:20]})")
        if not data:
            self._geo_cache[cache_key] = None
            return None

        loc = data.get("result", {}).get("location")
        if loc:
            coord = (float(loc["lng"]), float(loc["lat"]))
            self._geo_cache[cache_key] = coord
            return coord

        self._geo_cache[cache_key] = None
        return None

    async def geocode_with_fallback(
        self,
        candidates: list[str],
        city: str = "",
    ) -> list[tuple[float, float]]:
        """逐一尝试候选地址，返回第一个成功的 [(lng, lat)]"""
        for addr in candidates:
            result = await self.geocode(addr, city)
            if result:
                return [result]
        return []

    # ── 路径规划 ─────────────────────────────────────────────────

    def _coord_str(self, lng: float, lat: float) -> str:
        return f"{lat},{lng}"  # 腾讯接口：纬度在前，经度在后

    async def transit(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        city: str = "",
    ) -> Optional[CommuteResult]:
        """公交路径规划"""
        cache_key = ("transit", *origin, *dest)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        params = {
            "from": self._coord_str(*origin),
            "to": self._coord_str(*dest),
            "departure_time": _next_workday_9am(),
        }

        data = await self._get("/ws/direction/v1/transit/", params, label="公交规划")
        if not data:
            self._route_cache[cache_key] = None
            return None

        routes = data.get("result", {}).get("routes", [])
        if not routes:
            self._route_cache[cache_key] = None
            return None

        # 取耗时最短的路线
        routes.sort(key=lambda x: x.get("duration", 9999))
        best = routes[0]
        duration_min = max(1, round(best.get("duration", 0) / 60))
        distance_km = round(best.get("distance", 0) / 1000, 2)

        # 换乘信息
        transfers = len([s for s in best.get("steps", [])
                         if isinstance(s, dict) and s.get("mode") == "TRANSIT"]) - 1

        result = CommuteResult(
            map_provider=MapProvider.TENCENT,
            mode=CommuteMode.TRANSIT,
            duration_min=duration_min,
            distance_km=distance_km,
            transfers=max(0, transfers),
            raw_response={"source": "tencent", "route_count": len(routes)},
        )
        self._route_cache[cache_key] = result
        return result

    async def riding(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        """骑行路径规划"""
        cache_key = ("riding", *origin, *dest)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        params = {
            "from": self._coord_str(*origin),
            "to": self._coord_str(*dest),
        }
        data = await self._get("/ws/direction/v1/bicycling/", params, label="骑行规划")
        if not data:
            self._route_cache[cache_key] = None
            return None

        routes = data.get("result", {}).get("routes", [])
        if not routes:
            self._route_cache[cache_key] = None
            return None

        best = min(routes, key=lambda x: x.get("duration", 9999))
        result = CommuteResult(
            map_provider=MapProvider.TENCENT,
            mode=CommuteMode.RIDING,
            duration_min=max(1, round(best.get("duration", 0) / 60)),
            distance_km=round(best.get("distance", 0) / 1000, 2),
            raw_response={"source": "tencent"},
        )
        self._route_cache[cache_key] = result
        return result

    async def walking(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
    ) -> Optional[CommuteResult]:
        """步行路径规划"""
        cache_key = ("walking", *origin, *dest)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        params = {
            "from": self._coord_str(*origin),
            "to": self._coord_str(*dest),
        }
        data = await self._get("/ws/direction/v1/walking/", params, label="步行规划")
        if not data:
            self._route_cache[cache_key] = None
            return None

        routes = data.get("result", {}).get("routes", [])
        if not routes:
            self._route_cache[cache_key] = None
            return None

        best = min(routes, key=lambda x: x.get("duration", 9999))
        result = CommuteResult(
            map_provider=MapProvider.TENCENT,
            mode=CommuteMode.WALKING,
            duration_min=max(1, round(best.get("duration", 0) / 60)),
            distance_km=round(best.get("distance", 0) / 1000, 2),
            raw_response={"source": "tencent"},
        )
        self._route_cache[cache_key] = result
        return result


# ── 工具函数 ──────────────────────────────────────────────────────

def _next_workday_9am() -> int:
    """返回下一个工作日 9 点的 Unix 时间戳（公交规划时使用）"""
    import time
    import datetime
    now = datetime.datetime.now()
    days_ahead = 1
    # 跳过周末
    while True:
        candidate = now + datetime.timedelta(days=days_ahead)
        if candidate.weekday() < 5:  # 0=周一 ... 4=周五
            break
        days_ahead += 1
    dt = candidate.replace(hour=9, minute=0, second=0, microsecond=0)
    return int(dt.timestamp())


tencent_client = TencentMapClient()
