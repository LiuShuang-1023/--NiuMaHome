"""搜索 API (v0.3.0 重写)

新流程：
1. 抓取 → 去重 → 成本测算 → 写入 SQLite (按 session_id 隔离)
2. 目的地 geocode (一次)
3. 房源批量 geocode + haversine 直线粗筛 + 离线估算
4. 价格硬过滤 + 通勤时长硬过滤（基于离线估算）
5. ranker 排序 + 分页

新接口：
- POST /search           主入口（抓取 + geocode + 估算）
- POST /search/sort      仅排序（不重抓不重算，毫秒响应）
- POST /search/precise_one  对单条房源精算
- POST /search/precise_batch 批量精算（用户主动触发）
- DELETE /search/session/{session_id}  清空当前会话
- DELETE /search/cache   全局清缓存（保留兼容）
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from app.models import (
    CommuteSummary,
    CostBreakdown,
    Listing,
    ParsedRequirement,
    Recommendation,
)
from app.services.cost.engine import cost_engine
from app.services.crawler.beike import beike_crawler
from app.services.crawler.lianjia import lianjia_crawler
from app.services.crawler.anjuke import anjuke_crawler
from app.services.crawler.wuba import wuba_crawler
from app.services.crawler.region import to_pinyin
from app.services.map.amap import amap_client
from app.services.map.baidu import baidu_client
from app.services.map.tencent_map import tencent_client
from app.services.map.engine import commute_engine
from app.services.map.geo_filter import (
    geocode_and_filter,
    geocode_destination,
    geocode_listing,
)
from app.services.map.offline_estimator import (
    commute_minutes_to_radius_km,
    estimate_commute,
)
from app.services.ranker.engine import ranker
from app.services.storage import session_db
from app.services.storage.daily_cache import daily_cache


router = APIRouter()

SortMode = Literal["综合", "价格", "通勤", "面积"]

# ============================================================
# 全局后台任务注册表
# task_id → {"status": "pending"|"running"|"done"|"error",
#             "result": SearchResponse | None,
#             "error": str}
# 内存存储，重启后清空（session 级别，不需要持久化）
# ============================================================
_tasks: dict[str, dict] = {}


# ============================================================
# 请求/响应模型
# ============================================================
class SearchRequest(BaseModel):
    session_id: str = Field(..., description="前端 sessionStorage 生成的 UUID")
    requirement: ParsedRequirement
    sort_mode: SortMode = "综合"
    platform: str = "all"
    page: int = 1
    page_size: int = 10


class SearchResponse(BaseModel):
    session_id: str
    recommendations: list[Recommendation]
    total_crawled: int
    total_filtered: int
    total_pages: int = 1
    current_page: int = 1
    message: str = ""
    has_commute: bool = True
    sources: dict[str, int] = {}
    counts_by_platform: dict[str, int] = {}
    # v0.3.0 新增
    geo_filter_stats: dict = {}     # 粗筛统计
    commute_source_stats: dict = {} # 各 source 统计 (offline/amap/baidu)
    quota_status: dict = {}
    radius_km: float = 0.0
    # v0.3.0.1: geocode 精度与警示
    geocode_precision: str = ""     # 'exact' / 'district' / 'city' / ''(无目的地)
    geocode_warning: str = ""       # 给用户看的警示文案
    dest_label: str = ""            # 实际命中的目的地标签


class SortRequest(BaseModel):
    session_id: str
    sort_mode: SortMode = "综合"
    platform: str = "all"
    page: int = 1
    page_size: int = 10


class PreciseOneRequest(BaseModel):
    session_id: str
    listing_id: str


class PreciseBatchRequest(BaseModel):
    session_id: str
    max_count: int = 10  # 最多精算多少条（按距离从近到远）
    sort_mode: SortMode = "综合"
    platform: str = "all"
    page: int = 1
    page_size: int = 10


# ============================================================
# 工具
# ============================================================
def _dedupe_listings(listings: list[Listing]) -> list[Listing]:
    seen: dict[tuple, Listing] = {}
    for l in listings:
        key = (l.community or l.title, l.layout or "", l.price_base)
        if key not in seen:
            seen[key] = l
        else:
            existing = seen[key]
            if len(l.missing_fields) < len(existing.missing_fields):
                seen[key] = l
    return list(seen.values())


def _quota_status() -> dict:
    a = amap_client.get_diagnostics()
    b = baidu_client.get_diagnostics()
    t = tencent_client.get_diagnostics()
    return {
        "amap": {
            "available": amap_client.is_available,
            "quota_exhausted": a.get("quota_exhausted", False),
            "key_invalid": a.get("key_invalid", False),
            "rate_limit_hits": a.get("rate_limit_hits", 0),
        },
        "tencent": {
            "available": tencent_client.is_available,
            "quota_exhausted": t.get("quota_exhausted", False),
            "key_invalid": t.get("key_invalid", False),
        },
        "baidu": {
            "available": baidu_client.is_available,
            "quota_exhausted": b.get("quota_exhausted", False),
            "concurrency_limit_hit": b.get("concurrency_limit_hit", False),
            "key_invalid": b.get("key_invalid", False),
        },
    }


def _build_recommendations(
    session_id: str,
    requirement: ParsedRequirement,
    sort_mode: SortMode,
) -> list[Recommendation]:
    """从 DB 重建 Recommendation 列表，跑 ranker 排序"""
    listing_rows = session_db.list_listings(session_id, include_filtered=False)
    cost_rows = session_db.list_costs(session_id)
    commute_rows = session_db.list_commutes(session_id)

    items = []
    for lr in listing_rows:
        try:
            listing = Listing.model_validate_json(lr["raw_json"])
            # 把 DB 里更新过的 geo 写回 listing
            if lr["geo_lng"] is not None:
                listing.geo_lng = lr["geo_lng"]
                listing.geo_lat = lr["geo_lat"]
        except Exception as e:
            logger.warning(f"反序列化 listing 失败 {lr['listing_id']}: {e}")
            continue

        cr = cost_rows.get(lr["listing_id"])
        if not cr:
            continue
        try:
            cost = CostBreakdown.model_validate_json(cr["raw_json"])
        except Exception:
            continue

        commute = None
        cmr = commute_rows.get(lr["listing_id"])
        if cmr and cmr["raw_json"]:
            try:
                commute = CommuteSummary.model_validate_json(cmr["raw_json"])
            except Exception:
                pass

        # 把 source 标识写进 listing.missing_fields，方便前端展示徽章
        # 先剔除老的 "通勤" 标记
        listing.missing_fields = [
            f for f in (listing.missing_fields or [])
            if not f.startswith("通勤")
        ]
        if commute and cmr:
            src = cmr["source"]
            if src == "offline":
                listing.missing_fields.append("通勤数据：📍 离线估算（点详情可查实时）")
        else:
            listing.missing_fields.append("通勤数据：暂未估算")

        items.append((listing, cost, commute))

    # 跑 ranker
    recs = ranker.rank(items, requirement, sort_mode=sort_mode)
    return recs


def _paginate(
    recs: list[Recommendation],
    platform: str,
    page: int,
    page_size: int,
) -> tuple[list[Recommendation], int, int, dict]:
    """平台过滤 + 分页 + 计数（支持 all/lianjia/beike/anjuke/wuba）"""
    KNOWN_PLATFORMS = {"lianjia", "beike", "anjuke", "wuba"}
    if platform in KNOWN_PLATFORMS:
        platform_recs = [r for r in recs if r.listing.platform == platform]
    else:
        platform_recs = recs

    counts = {
        "all": len(recs),
        **{p: sum(1 for r in recs if r.listing.platform == p) for p in KNOWN_PLATFORMS},
    }

    total = len(platform_recs)
    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = max(1, min(page, total_pages))
    start = (current_page - 1) * page_size
    end = start + page_size
    return platform_recs[start:end], total_pages, current_page, counts


# ============================================================
# 异步任务接口（解决 Next.js 代理 60s 超时问题）
# ============================================================
class StartSearchResponse(BaseModel):
    task_id: str
    message: str = "搜索任务已提交，请轮询 /search/status/{task_id} 获取结果"


class SearchStatusResponse(BaseModel):
    task_id: str
    status: str          # "pending" | "running" | "done" | "error"
    progress: str = ""   # 给用户看的进度描述
    result: Optional[SearchResponse] = None
    error: str = ""


@router.post("/start", response_model=StartSearchResponse)
async def search_start(req: SearchRequest) -> StartSearchResponse:
    """异步启动搜索任务，立即返回 task_id（<1s）。
    前端用 /search/status/{task_id} 轮询结果。
    """
    if not req.requirement.destination.city:
        raise HTTPException(400, "请至少告诉我一个城市")
    if not req.session_id:
        raise HTTPException(400, "缺少 session_id")

    task_id = str(uuid.uuid4())
    _tasks[task_id] = {"status": "pending", "result": None, "error": "", "progress": "任务已提交，正在初始化…"}

    # 后台异步跑，不阻塞请求
    asyncio.create_task(_run_search_task(task_id, req))

    logger.info(f"[search_start] task_id={task_id[:8]} session={req.session_id[:8]}")
    return StartSearchResponse(task_id=task_id)


async def _run_search_task(task_id: str, req: SearchRequest):
    """后台任务：跑完整搜索流程，结果写入 _tasks"""
    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["progress"] = "正在跨平台抓取房源…"
    try:
        result = await _search_impl(req)
        _tasks[task_id]["status"] = "done"
        _tasks[task_id]["result"] = result
        _tasks[task_id]["progress"] = "完成"
        logger.info(f"[search_task] {task_id[:8]} 完成，房源={result.total_filtered}")
    except HTTPException as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = e.detail
        logger.warning(f"[search_task] {task_id[:8]} HTTP错误: {e.detail}")
    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
        logger.exception(f"[search_task] {task_id[:8]} 未捕获异常: {e}")
    finally:
        # 任务结果保留 10 分钟后自动清理（防内存泄漏）
        asyncio.create_task(_cleanup_task(task_id, delay=600))


async def _cleanup_task(task_id: str, delay: int = 600):
    await asyncio.sleep(delay)
    _tasks.pop(task_id, None)
    logger.debug(f"[search_task] {task_id[:8]} 已从内存清理")


@router.get("/status/{task_id}", response_model=SearchStatusResponse)
async def search_status(task_id: str) -> SearchStatusResponse:
    """轮询搜索任务状态。前端每 2 秒调一次，直到 status == 'done' 或 'error'"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"任务 {task_id} 不存在或已过期（>10分钟）")
    return SearchStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=task.get("progress", ""),
        result=task.get("result"),
        error=task.get("error", ""),
    )


# ============================================================
# 主搜索接口（保留兼容，新客户端请用 /start + /status）
# ============================================================
@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """主搜索流程（v0.3.0，同步版本，可能触发代理超时，建议用 /start）"""
    try:
        return await _search_impl(req)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[search] 未捕获异常: {e}")
        raise HTTPException(500, f"搜索内部错误: {type(e).__name__}: {e}") from e


async def _search_impl(req: SearchRequest) -> SearchResponse:
    """search 的实际实现，异常统一在外层捕获"""
    requirement = req.requirement
    dest = requirement.destination
    if not dest.city:
        raise HTTPException(400, "请至少告诉我一个城市")
    if not req.session_id:
        raise HTTPException(400, "缺少 session_id")

    session_id = req.session_id

    # ===== Step 1: 清掉旧 session 数据（同一 session_id 重新搜索） =====
    if session_db.session_exists(session_id):
        session_db.delete_session(session_id)
        logger.info(f"[search] 清掉旧 session {session_id}")

    # ===== Step 2: 多平台抓取（先查今日缓存，命中则跳过网络请求）=====
    district_py = to_pinyin(dest.district) if dest.district else ""
    max_price = (requirement.price.base_rent_max
                 or requirement.price.total_cost_max)

    logger.info(
        f"[search] {session_id[:8]} 开始: city={dest.city} "
        f"district={dest.district or '(全市)'} landmark={dest.landmark or '(无)'}"
    )

    # 价格档位tag（用于缓存 key，区分不同价格段的查询）
    price_tag = f"max{max_price}" if max_price else "any"

    async def _fetch_platform(platform: str, crawler, city: str, district_py: str, max_price, max_pages: int):
        """单平台抓取：先查日缓存，命中则直接反序列化；否则网络爬取后写缓存"""
        cache_key = daily_cache.listing_cache_key(city, district_py or "全市", price_tag, platform)
        cached_jsons = daily_cache.get_listings(cache_key)
        if cached_jsons is not None:
            # 缓存命中 → 反序列化
            results = []
            for rj in cached_jsons:
                try:
                    results.append(Listing.model_validate_json(rj))
                except Exception:
                    pass
            logger.info(f"[daily_cache] {platform} 房源缓存命中: {len(results)} 条")
            return results

        # 缓存未命中 → 网络爬取
        crawled = await crawler.search(
            city=city, district_py=district_py,
            max_price=max_price, max_pages=max_pages,
        )
        # 写入今日缓存
        if crawled:
            daily_cache.save_listings(
                cache_key, platform,
                [(l.id, l.model_dump_json()) for l in crawled],
            )
        return crawled

    lianjia_results, beike_results, anjuke_results, wuba_results = await asyncio.gather(
        _fetch_platform("lianjia", lianjia_crawler, dest.city, district_py, max_price, 5),
        _fetch_platform("beike", beike_crawler, dest.city, district_py, max_price, 5),
        _fetch_platform("anjuke", anjuke_crawler, dest.city, district_py, max_price, 3),
        _fetch_platform("wuba", wuba_crawler, dest.city, district_py, max_price, 3),
        return_exceptions=True,
    )
    if isinstance(lianjia_results, Exception):
        logger.error(f"链家抓取异常: {lianjia_results}")
        lianjia_results = []
    if isinstance(beike_results, Exception):
        logger.error(f"贝壳抓取异常: {beike_results}")
        beike_results = []
    if isinstance(anjuke_results, Exception):
        logger.error(f"安居客抓取异常: {anjuke_results}")
        anjuke_results = []
    if isinstance(wuba_results, Exception):
        logger.error(f"58同城抓取异常: {wuba_results}")
        wuba_results = []

    sources = {
        "lianjia": len(lianjia_results),
        "beike": len(beike_results),
        "anjuke": len(anjuke_results),
        "wuba": len(wuba_results),
    }
    all_listings = (
        list(lianjia_results) + list(beike_results) +
        list(anjuke_results) + list(wuba_results)
    )
    listings = _dedupe_listings(all_listings)
    logger.info(f"[search] 抓取={sources} 去重={len(listings)}")

    if not listings:
        return SearchResponse(
            session_id=session_id,
            recommendations=[], total_crawled=0, total_filtered=0,
            sources=sources, has_commute=False, message="暂未抓取到房源",
        )

    # ===== Step 3: 价格预筛（在写 DB 之前减少 IO） =====
    price = requirement.price
    pre_listings = []
    for l in listings:
        if price.base_rent_max and l.price_base > price.base_rent_max * 1.2:
            continue
        if price.base_rent_min and l.price_base > 0 and l.price_base < price.base_rent_min * 0.8:
            continue
        pre_listings.append(l)
    logger.info(f"[search] 价格预筛后: {len(pre_listings)}")

    # ===== Step 4: 成本测算 =====
    costs: dict[str, CostBreakdown] = {}
    for listing in pre_listings:
        c = cost_engine.compute(listing)
        listing.price_total = c.total
        costs[listing.id] = c

    # ===== Step 5: 目的地 geocode =====
    has_destination = bool(dest.landmark or dest.address)
    dest_coord: Optional[tuple[float, float]] = None
    dest_label = dest.landmark or dest.address or dest.district or dest.city
    radius_km = 0.0
    geocode_precision = ""    # 'exact' / 'district' / 'city'
    geocode_warning = ""

    if has_destination:
        geo = await geocode_destination(requirement)
        if geo:
            dest_coord = geo["coord"]
            dest_label = geo["label"]
            geocode_precision = geo["precision"]
            geocode_warning = geo["warning"]
            radius_km = commute_minutes_to_radius_km(requirement.commute.max_minutes)
            # 如果是区/市级兜底，把粗筛半径放大（因为目的地坐标本就不准）
            if geocode_precision == "district":
                radius_km = max(radius_km * 1.5, 12.0)
            elif geocode_precision == "city":
                radius_km = 0  # 市级兜底不粗筛（避免误杀）
        else:
            logger.warning("[search] 目的地 geocode 完全失败，跳过通勤估算")

    # ===== Step 6: 写入 session + listings + costs =====
    session_db.upsert_session(
        session_id=session_id,
        requirement=requirement,
        dest_lng=dest_coord[0] if dest_coord else None,
        dest_lat=dest_coord[1] if dest_coord else None,
        dest_label=dest_label,
        geo_radius_km=radius_km,
    )
    session_db.upsert_listings(session_id, pre_listings)
    session_db.upsert_costs(session_id, costs)

    # ===== Step 7: 房源 geocode + 粗筛 + 离线估算 =====
    geo_stats = {}
    if dest_coord:
        geo_stats = await geocode_and_filter(
            session_id=session_id,
            listings=pre_listings,
            requirement=requirement,
            dest_coord=dest_coord,
            radius_km=radius_km,
        )

    # ===== Step 8: 构造响应 =====
    recs = _build_recommendations(session_id, requirement, req.sort_mode)
    page_recs, total_pages, current_page, counts = _paginate(
        recs, req.platform, req.page, req.page_size,
    )

    commute_src_stats = session_db.count_commute_sources(session_id)

    platform_parts = []
    for p, label in [("lianjia", "链家"), ("beike", "贝壳"), ("anjuke", "安居客"), ("wuba", "58同城")]:
        cnt = sources.get(p, 0)
        if cnt > 0:
            platform_parts.append(f"{label} {cnt}")
    msg_parts = [
        f"抓取 {' + '.join(platform_parts) if platform_parts else '0'}",
        f"去重 {len(listings)}",
    ]
    if has_destination and dest_coord:
        if geocode_precision == "exact":
            msg_parts.append(
                f"粗筛半径 {radius_km:.0f}km → 范围内 {geo_stats.get('within_radius', 0)} 套"
            )
            msg_parts.append(
                f"离线估算 {geo_stats.get('offline_estimated', 0)} 套"
            )
        else:
            # 兜底模式
            msg_parts.append(
                f"⚠️ 目的地仅 {('区级' if geocode_precision=='district' else '市级')} 兜底"
            )
            if radius_km > 0:
                msg_parts.append(f"粗筛半径 {radius_km:.0f}km → {geo_stats.get('within_radius', 0)} 套")
    elif has_destination:
        msg_parts.append(f"⚠️ 无法识别目的地 “{dest.landmark or dest.address}”，请尝试更常见地名")
    else:
        msg_parts.append("（未指定目的地，无通勤估算）")
    message = " · ".join(msg_parts)

    return SearchResponse(
        session_id=session_id,
        recommendations=page_recs,
        total_crawled=len(listings),
        total_filtered=len(recs),
        total_pages=total_pages,
        current_page=current_page,
        message=message,
        has_commute=has_destination and dest_coord is not None,
        sources=sources,
        counts_by_platform=counts,
        geo_filter_stats=geo_stats,
        commute_source_stats=commute_src_stats,
        quota_status=_quota_status(),
        radius_km=radius_km,
        geocode_precision=geocode_precision,
        geocode_warning=geocode_warning,
        dest_label=dest_label,
    )


# ============================================================
# 排序专用接口（毫秒响应）
# ============================================================
@router.post("/sort", response_model=SearchResponse)
async def sort_only(req: SortRequest) -> SearchResponse:
    """仅按当前 session 的数据重排，不重抓不重算"""
    if not session_db.session_exists(req.session_id):
        raise HTTPException(404, "会话不存在或已过期，请重新搜索")

    session_db.touch_session(req.session_id)
    sess = session_db.get_session(req.session_id)
    requirement = ParsedRequirement.model_validate_json(sess["requirement"])

    recs = _build_recommendations(req.session_id, requirement, req.sort_mode)
    page_recs, total_pages, current_page, counts = _paginate(
        recs, req.platform, req.page, req.page_size,
    )
    geo_stats = session_db.count_filter_stats(req.session_id)
    commute_src_stats = session_db.count_commute_sources(req.session_id)

    return SearchResponse(
        session_id=req.session_id,
        recommendations=page_recs,
        total_crawled=geo_stats["total"],
        total_filtered=len(recs),
        total_pages=total_pages,
        current_page=current_page,
        message=f"已排序 · 在范围内 {geo_stats['within_radius']} 套 · 已精算 {commute_src_stats.get('precise', 0)} 套",
        has_commute=sess.get("dest_lng") is not None,
        counts_by_platform=counts,
        geo_filter_stats=geo_stats,
        commute_source_stats=commute_src_stats,
        quota_status=_quota_status(),
        radius_km=sess.get("geo_radius_km") or 0,
    )


# ============================================================
# 单条精算
# ============================================================
class PreciseOneResponse(BaseModel):
    listing_id: str
    success: bool
    source: str = ""    # 'amap' / 'baidu'
    duration_min: int = 0
    fail_reason: str = ""


@router.post("/precise_one", response_model=PreciseOneResponse)
async def precise_one(req: PreciseOneRequest) -> PreciseOneResponse:
    """对单条房源调高德/百度算精确通勤"""
    if not session_db.session_exists(req.session_id):
        raise HTTPException(404, "会话不存在")
    session_db.touch_session(req.session_id)

    sess = session_db.get_session(req.session_id)
    if not sess.get("dest_lng"):
        raise HTTPException(400, "session 没有目的地坐标，无法精算")

    listing_row = session_db.get_listing(req.session_id, req.listing_id)
    if not listing_row:
        raise HTTPException(404, "房源不存在于当前会话")

    requirement = ParsedRequirement.model_validate_json(sess["requirement"])
    dest_address = sess.get("dest_label") or ""
    dest_coord = (sess["dest_lng"], sess["dest_lat"])

    # 反序列化 listing
    listing = Listing.model_validate_json(listing_row["raw_json"])

    # 用 commute_engine 精算（amap_first）
    origin_addr = (listing.address or listing.community
                   or sess.get("dest_label", ""))
    if not origin_addr:
        from app.services.map.address_cleaner import extract_community_from_title
        origin_addr = extract_community_from_title(listing.title or "")

    if not origin_addr:
        return PreciseOneResponse(
            listing_id=req.listing_id, success=False,
            fail_reason="房源缺少地址信息",
        )

    res = await commute_engine.compute(
        origin_address=f"{requirement.destination.city}{origin_addr}",
        dest_address=dest_address,
        city=requirement.destination.city,
        modes=requirement.commute.modes,
        use_amap="amap" in requirement.commute.maps,
        use_baidu="baidu" in requirement.commute.maps,
        origin_community=listing.community or "",
        origin_district=requirement.destination.district or "",
        dest_landmark=requirement.destination.landmark or "",
        bidirectional=True,
    )
    if res.summary:
        res.summary.listing_id = req.listing_id
        session_db.upsert_commute(
            req.session_id, req.listing_id, res.summary,
            source=res.used_provider or "amap",
        )
        return PreciseOneResponse(
            listing_id=req.listing_id, success=True,
            source=res.used_provider or "amap",
            duration_min=res.summary.best_duration_min,
        )
    else:
        return PreciseOneResponse(
            listing_id=req.listing_id, success=False,
            fail_reason=res.fail_reason or "未知原因",
        )


# ============================================================
# 批量精算
# ============================================================
class PreciseBatchResponse(SearchResponse):
    round_attempted: int = 0
    round_success: int = 0
    round_fail: int = 0


@router.post("/precise_batch", response_model=PreciseBatchResponse)
async def precise_batch(req: PreciseBatchRequest) -> PreciseBatchResponse:
    """对当前 session 内距离最近的 N 条还没精算的房源做精算"""
    if not session_db.session_exists(req.session_id):
        raise HTTPException(404, "会话不存在")
    session_db.touch_session(req.session_id)

    sess = session_db.get_session(req.session_id)
    if not sess.get("dest_lng"):
        raise HTTPException(400, "session 没有目的地坐标")

    requirement = ParsedRequirement.model_validate_json(sess["requirement"])
    dest_coord = (sess["dest_lng"], sess["dest_lat"])
    dest_address = sess.get("dest_label") or ""

    # 找出"未精算"的房源（source != amap/baidu），按距离升序
    listing_rows = session_db.list_listings(req.session_id, include_filtered=False)
    commute_rows = session_db.list_commutes(req.session_id)

    pending = []
    for lr in listing_rows:
        cmr = commute_rows.get(lr["listing_id"])
        if cmr and cmr["source"] in ("amap", "baidu"):
            continue
        pending.append(lr)
    pending.sort(key=lambda r: r.get("distance_km") or 999)

    targets = pending[: req.max_count]
    success = 0
    fail = 0

    for lr in targets:
        listing = Listing.model_validate_json(lr["raw_json"])
        origin_addr = listing.address or listing.community
        if not origin_addr:
            from app.services.map.address_cleaner import extract_community_from_title
            origin_addr = extract_community_from_title(listing.title or "")
        if not origin_addr:
            fail += 1
            continue

        res = await commute_engine.compute(
            origin_address=f"{requirement.destination.city}{origin_addr}",
            dest_address=dest_address,
            city=requirement.destination.city,
            modes=requirement.commute.modes,
            use_amap="amap" in requirement.commute.maps,
            use_baidu="baidu" in requirement.commute.maps,
            origin_community=listing.community or "",
            origin_district=requirement.destination.district or "",
            dest_landmark=requirement.destination.landmark or "",
            bidirectional=True,
        )
        if res.summary:
            res.summary.listing_id = lr["listing_id"]
            session_db.upsert_commute(
                req.session_id, lr["listing_id"], res.summary,
                source=res.used_provider or "amap",
            )
            success += 1
        else:
            fail += 1

    # 构造响应
    recs = _build_recommendations(req.session_id, requirement, req.sort_mode)
    page_recs, total_pages, current_page, counts = _paginate(
        recs, req.platform, req.page, req.page_size,
    )
    geo_stats = session_db.count_filter_stats(req.session_id)
    commute_src_stats = session_db.count_commute_sources(req.session_id)

    return PreciseBatchResponse(
        session_id=req.session_id,
        recommendations=page_recs,
        total_crawled=geo_stats["total"],
        total_filtered=len(recs),
        total_pages=total_pages,
        current_page=current_page,
        message=f"本轮精算 {len(targets)} 条 · 成功 {success} 失败 {fail}",
        has_commute=True,
        counts_by_platform=counts,
        geo_filter_stats=geo_stats,
        commute_source_stats=commute_src_stats,
        quota_status=_quota_status(),
        radius_km=sess.get("geo_radius_km") or 0,
        round_attempted=len(targets),
        round_success=success,
        round_fail=fail,
    )


# ============================================================
# 批量精算 SSE 流式进度（v0.5.1）
# GET /search/precise_batch_stream?session_id=xxx&max_count=10&...
# 每精算完一条推一个 JSON 事件，前端实时展示进度
# ============================================================
from fastapi.responses import StreamingResponse


class PreciseBatchStreamParams(BaseModel):
    session_id: str
    max_count: int = 10
    platform: str = "all"
    sort_mode: SortMode = "综合"
    page: int = 1
    page_size: int = 10


@router.post("/precise_batch_stream")
async def precise_batch_stream(req: PreciseBatchStreamParams):
    """SSE 流式批量精算：每完成一条推一次进度事件"""
    if not session_db.session_exists(req.session_id):
        raise HTTPException(404, "会话不存在")
    session_db.touch_session(req.session_id)

    sess = session_db.get_session(req.session_id)
    if not sess.get("dest_lng"):
        raise HTTPException(400, "session 没有目的地坐标")

    requirement = ParsedRequirement.model_validate_json(sess["requirement"])
    dest_coord = (sess["dest_lng"], sess["dest_lat"])
    dest_address = sess.get("dest_label") or ""

    listing_rows = session_db.list_listings(req.session_id, include_filtered=False)
    commute_rows = session_db.list_commutes(req.session_id)

    pending = []
    for lr in listing_rows:
        cmr = commute_rows.get(lr["listing_id"])
        if cmr and cmr["source"] in ("amap", "baidu"):
            continue
        pending.append(lr)
    pending.sort(key=lambda r: r.get("distance_km") or 999)
    targets = pending[: req.max_count]
    total = len(targets)

    async def event_stream():
        success = 0
        fail = 0
        for i, lr in enumerate(targets):
            listing = Listing.model_validate_json(lr["raw_json"])
            origin_addr = listing.address or listing.community
            if not origin_addr:
                from app.services.map.address_cleaner import extract_community_from_title
                origin_addr = extract_community_from_title(listing.title or "")

            label = listing.community or listing.title or lr["listing_id"]

            if not origin_addr:
                fail += 1
            else:
                res = await commute_engine.compute(
                    origin_address=f"{requirement.destination.city}{origin_addr}",
                    dest_address=dest_address,
                    city=requirement.destination.city,
                    modes=requirement.commute.modes,
                    use_amap="amap" in requirement.commute.maps,
                    use_baidu="baidu" in requirement.commute.maps,
                    origin_community=listing.community or "",
                    origin_district=requirement.destination.district or "",
                    dest_landmark=requirement.destination.landmark or "",
                    bidirectional=True,
                )
                if res.summary:
                    res.summary.listing_id = lr["listing_id"]
                    session_db.upsert_commute(
                        req.session_id, lr["listing_id"], res.summary,
                        source=res.used_provider or "amap",
                    )
                    success += 1
                else:
                    fail += 1

            # 推送进度事件
            progress_data = json.dumps({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "success": success,
                "fail": fail,
                "label": label[:20],
            }, ensure_ascii=False)
            yield f"data: {progress_data}\n\n"
            await asyncio.sleep(0)  # 让出控制权，确保事件被推送

        # 精算完成，构造最终结果
        recs = _build_recommendations(req.session_id, requirement, req.sort_mode)
        page_recs, total_pages, current_page, counts = _paginate(
            recs, req.platform, req.page, req.page_size,
        )
        geo_stats = session_db.count_filter_stats(req.session_id)
        commute_src_stats = session_db.count_commute_sources(req.session_id)

        final_resp = PreciseBatchResponse(
            session_id=req.session_id,
            recommendations=page_recs,
            total_crawled=geo_stats["total"],
            total_filtered=len(recs),
            total_pages=total_pages,
            current_page=current_page,
            counts_by_platform=counts,
            has_commute=True,
            commute_source_stats=commute_src_stats,
            geo_filter_stats=geo_stats,
            radius_km=sess.get("radius_km", 0),
            dest_label=dest_address,
            round_attempted=total,
            round_success=success,
            round_fail=fail,
        )
        done_data = json.dumps({
            "type": "done",
            "result": final_resp.model_dump(),
        }, ensure_ascii=False)
        yield f"data: {done_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 会话管理
# ============================================================
@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """用户主动清空当前会话（重新搜索时调用）"""
    n = session_db.delete_session(session_id)
    return {"message": f"已清空会话 {session_id}", "deleted": n}


@router.delete("/cache")
async def clear_cache():
    """全局清缓存（兼容旧接口）—— 现在是清掉所有过期 session"""
    n = session_db.cleanup_expired(ttl_seconds=0)  # 全部清
    return {"message": f"已清除 {n} 个过期会话"}


@router.post("/reset_quota")
async def reset_quota():
    amap_client.reset_quota_flag()
    baidu_client.reset_quota_flag()
    return {"message": "配额标志已重置", "quota_status": _quota_status()}


@router.get("/db_stats")
async def db_stats():
    """开发调试：查看 SQLite 整体状况"""
    return session_db.get_stats()
