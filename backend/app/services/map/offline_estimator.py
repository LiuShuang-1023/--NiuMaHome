"""离线通勤估算 (v0.3.1)

优先级：
  1. commute_store.get_baseline()  —— 历史精算7日均值（最准，用过精算的路线直接用）
  2. 离线公式（直线距离 × 迂回系数 ÷ 速度）—— 无历史数据时兜底

误差预估（离线公式，历史均值无误差）：
- 短距离 <3km: ±15%
- 中距离 3-10km: ±25%
- 长距离 >10km: ±35%
"""
from typing import Optional

from loguru import logger

from app.models import (
    CommuteMode,
    CommuteResult,
    CommuteSummary,
    MapProvider,
)
from app.services.map.address_cleaner import haversine_km


# ============================================================
# 经验系数表
# ============================================================
# (路网迂回系数, 平均速度km/h, 固定加成min)
ESTIMATE_PARAMS: dict[CommuteMode, tuple[float, float, int]] = {
    CommuteMode.WALKING: (1.3, 5.0,  0),
    CommuteMode.RIDING:  (1.4, 15.0, 0),
    CommuteMode.TRANSIT: (1.6, 20.0, 8),  # +8 min 等车换乘
    CommuteMode.DRIVING: (1.4, 30.0, 0),
}


# 通勤上限 → 推荐粗筛半径（km）
def commute_minutes_to_radius_km(max_minutes: int) -> float:
    """根据通勤上限估算最大直线距离

    保守估算：以最快交通方式（公交 20km/h × 0.6 = 直线 12km/h）算
    例：20min → 4km 直线，但留 2x 余量 → 8km
    """
    if not max_minutes or max_minutes <= 0:
        return 0  # 不限
    # 经验：max_minutes × 0.4 km/min ≈ 直线最大距离
    # 这是公交场景的保守估算（实际公交直达可能能跑更远）
    radius = max_minutes * 0.4
    # 最低 5km（避免太小），最高 30km（避免太宽）
    return max(5.0, min(30.0, radius))


# ============================================================
# 核心估算函数
# ============================================================
def estimate_one_mode(
    distance_km: float,
    mode: CommuteMode,
) -> tuple[int, float]:
    """估算单种出行方式的时长

    Args:
        distance_km: 起终点直线距离（haversine）
        mode: 出行方式

    Returns:
        (duration_min, route_distance_km)
    """
    detour, speed_kmh, fixed_add = ESTIMATE_PARAMS.get(mode, (1.5, 15.0, 0))
    route_distance = distance_km * detour
    duration_min = int(round(route_distance / speed_kmh * 60 + fixed_add))
    return max(1, duration_min), round(route_distance, 2)


def estimate_commute(
    origin: tuple[float, float],
    dest: tuple[float, float],
    dest_address: str,
    listing_id: str = "",
    modes: Optional[list[CommuteMode]] = None,
    origin_address: str = "",   # 用于查询 commute_store baseline
) -> CommuteSummary:
    """根据起终点坐标估算通勤（多模式）

    优先级：
      1. commute_store baseline（历史精算均值） → source 标记为 "baseline"
      2. 离线公式 → source 标记为 "offline"

    Args:
        origin:         (lng, lat)
        dest:           (lng, lat)
        dest_address:   目的地展示名（同时用作 commute_store 的 dest key）
        listing_id:     房源 ID（写入 summary）
        modes:          要估算的出行方式
        origin_address: 起点地址/小区名（用于查询 baseline，可选）
    """
    # 延迟导入避免循环依赖
    from app.services.storage.commute_store import commute_store

    modes = modes or [CommuteMode.TRANSIT, CommuteMode.RIDING, CommuteMode.WALKING]
    distance_km = haversine_km(origin, dest)

    # ── 1. 先查历史精算均值 ──────────────────────────────
    baseline_hits: dict[str, int] = {}
    if origin_address and dest_address:
        for m in modes:
            hit = commute_store.get_baseline(origin_address, dest_address, str(m))
            if hit:
                baseline_min, sample_count = hit
                baseline_hits[str(m)] = int(round(baseline_min))
                logger.debug(
                    f"[estimator] baseline 命中 {m} = {baseline_min:.1f}min (n={sample_count}): "
                    f"{origin_address} → {dest_address}"
                )

    # ── 2. 构建结果（baseline 优先，无则离线公式）──────────
    results = []
    source_used = "offline"  # 默认
    all_from_baseline = len(baseline_hits) == len(modes)

    for m in modes:
        mode_key = str(m)
        if mode_key in baseline_hits:
            duration = baseline_hits[mode_key]
            # baseline 来的距离用离线公式补（展示用，不影响时长）
            _, route_km = estimate_one_mode(distance_km, m)
            raw = {"source": "commute_store_baseline", "straight_km": round(distance_km, 2)}
        else:
            duration, route_km = estimate_one_mode(distance_km, m)
            raw = {"source": "offline_estimate", "straight_km": round(distance_km, 2)}

        results.append(CommuteResult(
            map_provider=MapProvider.AMAP,
            mode=m,
            duration_min=duration,
            distance_km=route_km,
            direction="home_to_work",   # 离线估算只有单向，默认家→公司
            raw_response=raw,
        ))

    if all_from_baseline:
        source_used = "baseline"

    best = min((r.duration_min for r in results), default=0)
    transit_durations = [r.duration_min for r in results if r.mode == CommuteMode.TRANSIT]
    avg_transit = transit_durations[0] if transit_durations else None

    summary = CommuteSummary(
        listing_id=listing_id,
        destination_address=dest_address,
        results=results,
        best_duration_min=best,
        avg_transit_min=avg_transit,
    )
    # 在 raw_response 里标记数据来源，供上层(geo_filter)识别
    summary.__dict__["_estimate_source"] = source_used
    return summary


# ============================================================
# 自检（dev only）
# ============================================================
if __name__ == "__main__":
    # 广州塔 → 北京路（直线 ~3km）
    gz_tower = (113.324520, 23.106570)
    bj_road = (113.270774, 23.129163)
    s = estimate_commute(gz_tower, bj_road, "北京路")
    print(f"广州塔 → 北京路 (直线 {haversine_km(gz_tower, bj_road):.2f}km)")
    for r in s.results:
        print(f"  {r.mode.value}: {r.duration_min} min ({r.distance_km} km)")
    print(f"  最快: {s.best_duration_min} min")
