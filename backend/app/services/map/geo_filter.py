"""地理粗筛器 (v0.3.0)

把"通勤 ≤ N 分钟"这个用户语义，转成"直线距离 ≤ R 公里"的粗筛规则，
先用 haversine 把明显超出范围的房源排除掉，再对剩余的精算。

核心流程：
1. 对目的地 geocode 一次（缓存到 session）
2. 对每个房源 geocode（fallback 5 级），失败的标记 geocode_failed
3. 算 haversine 直线距离，超过半径的标记 is_filtered_out
4. 剩余房源走离线估算（毫秒级），写入 commutes 表（source=offline）

地理 geocode 用高德优先（实测准确率高），失败再尝试百度。
节流仍走 amap_client/baidu_client 内部的 Semaphore + 350ms。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from app.models import Listing, ParsedRequirement
from app.services.map.address_cleaner import (
    build_geocode_candidates,
    extract_community_from_title,
    fallback_landmark_address,
    haversine_km,
)
from app.services.map.amap import amap_client
from app.services.map.baidu import baidu_client
from app.services.map.offline_estimator import (
    commute_minutes_to_radius_km,
    estimate_commute,
)
from app.services.ranker.engine import is_parking
from app.services.storage import session_db


# ============================================================
# 目的地 geocode（一次性）
# ============================================================
async def geocode_destination(
    requirement: ParsedRequirement,
) -> Optional[dict]:
    """对用户指定的目的地 geocode

    返回字段：
        coord: (lng, lat)
        label: 展示名
        precision: 'exact' (完整命中 landmark) | 'district' (兜底用区中心) | 'city' (兜底用市中心)
        hit_address: 实际命中的候选地址
        warning: 给用户的警示文案（precision != 'exact' 时有值）

    全部失败返回 None
    """
    dest = requirement.destination
    if not dest.city:
        return None

    # ========== 优先级 1: 精确候选（含 landmark/address） ==========
    precise_candidates = []
    if dest.address:
        precise_candidates.append(dest.address)
    if dest.landmark:
        if dest.district:
            precise_candidates.append(f"{dest.city}{dest.district}{dest.landmark}")
        precise_candidates.append(f"{dest.city}{dest.landmark}")
        fb = fallback_landmark_address(dest.landmark, dest.city)
        if fb and fb not in precise_candidates:
            precise_candidates.append(fb)

    # ========== 优先级 2: 区级兜底 ==========
    district_candidates = []
    if dest.district:
        district_candidates.append(f"{dest.city}{dest.district}")

    # ========== 优先级 3: 市级兜底 ==========
    city_candidates = [dest.city]

    label = dest.landmark or dest.address or dest.district or dest.city

    async def try_geocode_strict(candidates: list[str]) -> Optional[tuple[tuple[float, float], str]]:
        """尝试一组候选，要求 geocode 返回的精度是"非兜底"级别

        高德：level 不在 {省/市/区县/乡镇/街道}
        百度：level 不在 {省/城市/区县}，且 confidence >= 30
        """
        if not candidates:
            return None
        # 高德优先
        if amap_client.is_available:
            for addr in candidates:
                res = await amap_client.geocode_with_level(addr, dest.city)
                if not res:
                    continue
                coord, level, formatted = res
                if level in amap_client.AMAP_FUZZY_LEVELS:
                    logger.debug(
                        f"[geocode] 高德 '{addr}' level={level} 是兜底，formatted={formatted}"
                    )
                    continue
                logger.info(f"[geocode] 高德 '{addr}' level={level} 精确命中 → {coord}")
                return coord, formatted or addr

        # 高德全部 fuzzy → 百度
        if baidu_client.is_available:
            for addr in candidates:
                res = await baidu_client.geocode_with_level(addr, dest.city)
                if not res:
                    continue
                coord, level, confidence, _ = res
                if level in baidu_client.BAIDU_FUZZY_LEVELS:
                    logger.debug(
                        f"[geocode] 百度 '{addr}' level={level} confidence={confidence} 是兜底"
                    )
                    continue
                if confidence < baidu_client.BAIDU_MIN_CONFIDENCE:
                    logger.debug(
                        f"[geocode] 百度 '{addr}' confidence={confidence} 太低（视为兜底）"
                    )
                    continue
                logger.info(
                    f"[geocode] 百度 '{addr}' level={level} confidence={confidence} 精确命中 → {coord}"
                )
                return coord, addr
        return None

    async def try_geocode_loose(candidates: list[str]) -> Optional[tuple[tuple[float, float], str]]:
        """松散尝试，不限 level（用于区/市级兜底场景）"""
        if not candidates:
            return None
        if amap_client.is_available:
            res = await amap_client.geocode_with_fallback(candidates, dest.city)
            if res:
                return res
        if baidu_client.is_available:
            res = await baidu_client.geocode_with_fallback(candidates, dest.city)
            if res:
                return res
        return None

    # 1. 先尝试精确命中（严格 level）
    res = await try_geocode_strict(precise_candidates)
    if res:
        coord, hit = res
        logger.info(f"[目的地geocode] 精确命中: '{hit}' → {coord}")
        return {
            "coord": coord,
            "label": label,
            "precision": "exact",
            "hit_address": hit,
            "warning": "",
        }

    # 2. 精确失败 → 区级兜底（接受 fuzzy）
    if district_candidates:
        res = await try_geocode_loose(district_candidates)
        if res:
            coord, hit = res
            logger.warning(
                f"[目的地geocode] '{dest.landmark}' 无法精确识别，用 {dest.district} 中心点兜底: {coord}"
            )
            return {
                "coord": coord,
                "label": f"{dest.district}（{dest.landmark or '?'} 未识别）",
                "precision": "district",
                "hit_address": hit,
                "warning": (
                    f"⚠️ 无法识别地点 “{dest.landmark}”，已用 {dest.district} 中心点估算通勤。"
                    f"建议改用更常见的地标名（如商圈/地铁站/写字楼）"
                ),
            }

    # 3. 区级也失败 → 市级
    res = await try_geocode_loose(city_candidates)
    if res:
        coord, hit = res
        logger.warning(f"[目的地geocode] 仅市级兜底成功: {coord}")
        return {
            "coord": coord,
            "label": f"{dest.city}（具体位置未识别）",
            "precision": "city",
            "hit_address": hit,
            "warning": (
                f"⚠️ 无法识别 “{dest.landmark or dest.district}”，仅用 {dest.city} 市中心粗略估算，"
                f"通勤数据参考价值低。请确认地点名称是否正确"
            ),
        }

    logger.error(f"[目的地geocode] 全部失败 dest={dest}")
    return None


# ============================================================
# 单条房源 geocode + 距离计算
# ============================================================
async def geocode_listing(
    listing: Listing,
    city: str,
    district: str = "",
) -> Optional[tuple[tuple[float, float], str, str]]:
    """对单条房源 geocode

    Returns:
        ((lng, lat), source, hit_addr) 或 None
    """
    # 兜底取 community
    community = listing.community or extract_community_from_title(listing.title or "")

    candidates = build_geocode_candidates(
        raw_community=community or listing.address,
        address=listing.address,
        city=city,
        district=district,
    )
    if not candidates:
        return None

    if amap_client.is_available:
        res = await amap_client.geocode_with_fallback(candidates, city)
        if res:
            coord, hit = res
            return coord, "amap", hit

    if baidu_client.is_available:
        res = await baidu_client.geocode_with_fallback(candidates, city)
        if res:
            coord, hit = res
            return coord, "baidu", hit

    return None


# ============================================================
# 批量 geocode 所有房源（含粗筛）
# ============================================================
async def geocode_and_filter(
    session_id: str,
    listings: list[Listing],
    requirement: ParsedRequirement,
    dest_coord: tuple[float, float],
    radius_km: float,
) -> dict:
    """对所有房源 geocode、算距离、按半径粗筛

    流程：
    0. 提前剔除车位/极低价非住宅（减少 geocode 调用量）
    1. 并发 geocode（Semaphore=2，高德内部自带 QPS 节流）
    2. 算 haversine 直线距离
    3. 距离 > radius_km → 标记 is_filtered_out
    4. 顺手做离线估算 → 写入 commutes 表
    5. 同一小区多套房共享 geocode 结果（内存缓存避免重复请求）

    Args:
        session_id: 会话 ID
        listings: 已写入 DB 的 listings
        requirement: 用户需求
        dest_coord: 目的地坐标
        radius_km: 粗筛半径（0 表示不粗筛，全部保留）

    Returns:
        统计 dict
    """
    dest = requirement.destination
    dest_address = dest.address or f"{dest.city}{dest.district or ''}{dest.landmark or ''}"

    # ---- Step 0: 提前剔除车位/储藏室（不浪费 geocode 配额）----
    need_geo: list[Listing] = []
    pre_filtered_ids: set[str] = set()
    for l in listings:
        if is_parking(l):
            session_db.update_listing_filter(
                session_id, l.id, is_filtered_out=True, reason="车位/储藏室",
            )
            pre_filtered_ids.add(l.id)
        else:
            need_geo.append(l)

    stats = {
        "total": len(listings),
        "pre_filtered": len(pre_filtered_ids),   # 车位等提前剔除
        "geocoded": 0,
        "geocode_failed": 0,
        "within_radius": 0,
        "out_of_radius": 0,
        "offline_estimated": 0,
    }

    if not need_geo:
        logger.info(f"[geocode_and_filter] 全部被预过滤: {stats}")
        return stats

    logger.info(
        f"[geocode_and_filter] 预过滤剔除 {len(pre_filtered_ids)} 条车位/非住宅，"
        f"剩余 {len(need_geo)} 条需 geocode"
    )

    # ---- 小区名 → geocode 结果缓存（同小区多套房只算一次）----
    # key: (city, community_key)  value: (coord, source, hit_addr) | None
    _community_geo_cache: dict[tuple, Optional[tuple]] = {}

    def _community_key(listing: Listing) -> str:
        """取小区名作为缓存 key（公寓从 title 提取）"""
        return (listing.community
                or extract_community_from_title(listing.title or "")
                or listing.id)  # 实在没有才用 id（不共享缓存）

    # ---- 并发 geocode（Semaphore=2，高德内部自带 QPS 控制，外层不再串行）----
    semaphore = asyncio.Semaphore(2)

    async def process_one(listing: Listing):
        async with semaphore:
            try:
                # 同小区缓存命中 → 直接复用，不再请求高德
                ck = (_community_key(listing), dest.city)
                if ck in _community_geo_cache:
                    geo_res = _community_geo_cache[ck]
                    logger.debug(f"[geocode] 复用小区缓存: {ck[0]}")
                else:
                    geo_res = await geocode_listing(
                        listing, city=dest.city, district=dest.district,
                    )
                    _community_geo_cache[ck] = geo_res

                if not geo_res:
                    session_db.update_listing_geo(
                        session_id, listing.id,
                        None, None, None, None, None,
                    )
                    session_db.update_listing_filter(
                        session_id, listing.id,
                        is_filtered_out=False,
                        reason="geocode 失败，无法算距离",
                    )
                    stats["geocode_failed"] += 1
                    return

                coord, source, hit_addr = geo_res
                distance = haversine_km(coord, dest_coord)
                stats["geocoded"] += 1

                session_db.update_listing_geo(
                    session_id, listing.id,
                    coord[0], coord[1], source, hit_addr, round(distance, 2),
                )

                if radius_km > 0 and distance > radius_km:
                    session_db.update_listing_filter(
                        session_id, listing.id,
                        is_filtered_out=True,
                        reason=f"直线距离 {distance:.1f}km 超出 {radius_km:.0f}km 半径",
                    )
                    stats["out_of_radius"] += 1
                    return

                stats["within_radius"] += 1

                # 传入 origin_address 让 estimate_commute 先查 commute_store baseline
                origin_addr_for_baseline = (
                    listing.community
                    or listing.address
                    or extract_community_from_title(listing.title or "")
                    or ""
                )
                summary = estimate_commute(
                    origin=coord,
                    dest=dest_coord,
                    dest_address=dest_address,
                    listing_id=listing.id,
                    modes=requirement.commute.modes,
                    origin_address=origin_addr_for_baseline,
                )
                # 根据 estimate_commute 内部使用的数据源决定 source 标签
                _src = getattr(summary, "__dict__", {}).get("_estimate_source", "offline")
                source_label = "baseline" if _src == "baseline" else "offline"
                session_db.upsert_commute(
                    session_id, listing.id, summary, source=source_label,
                )
                stats["offline_estimated"] += 1

            except Exception as e:
                logger.warning(f"[geocode] 房源 {listing.id} 处理异常: {e}", exc_info=True)
                stats["geocode_failed"] += 1

    await asyncio.gather(*[process_one(l) for l in need_geo])

    logger.info(f"[geocode_and_filter] 统计: {stats}")
    return stats
