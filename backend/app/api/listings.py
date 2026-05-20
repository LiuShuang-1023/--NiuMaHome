"""房源 API

v0.1: 占位（搜索结果由 /api/search 返回）
v0.2: 新增 /review - AI 生成单套房源的优缺点 + 评分
v0.3: 新增 /{listing_id}/detail - 详情页二次抓取（押付/配套/供暖/用水用电/更多图片）
v0.7: /detail 抓取后自动将押付方式/水电类型写回 cost engine，更新 session DB 成本记录
"""
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.models import (
    CommuteSummary,
    CostBreakdown,
    Listing,
    ListingReview,
    ParsedRequirement,
)
from app.services.llm.factory import llm_client
from app.services.crawler.detail_parser import detail_fetcher
from app.services.cost.engine import cost_engine
from app.services.storage import session_db

router = APIRouter()


@router.get("")
async def list_listings():
    """房源列表 - 占位"""
    return {"items": [], "message": "请使用 /api/search"}


# ============================================================
# AI 点评 (v0.2)
# ============================================================

class ListingReviewRequest(BaseModel):
    """对单套房源生成 AI 点评的请求

    前端从已有的 Recommendation 里取出 listing/cost/commute/requirement 直接传过来。
    """
    listing: Listing
    cost: CostBreakdown
    commute: Optional[CommuteSummary] = None
    requirement: Optional[ParsedRequirement] = None
    force_refresh: bool = False  # 跳过缓存重新生成


class ListingReviewResponse(BaseModel):
    review: ListingReview
    cached: bool = False


# 进程内缓存（key = listing_id + 需求关键字段 hash）
_review_cache: dict[str, ListingReview] = {}
_REVIEW_CACHE_MAX = 200


def _build_cache_key(req: ListingReviewRequest) -> str:
    parts = {
        "lid": req.listing.id,
        "price_base": req.listing.price_base,
        "cost_total": req.cost.total,
    }
    if req.commute:
        parts["commute_best"] = req.commute.best_duration_min
    if req.requirement:
        d = req.requirement.destination
        parts["dest"] = f"{d.city}|{d.district}|{d.landmark}"
        p = req.requirement.price
        parts["budget"] = f"{p.base_rent_max}|{p.total_cost_max}"
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


@router.post("/review", response_model=ListingReviewResponse)
async def review_listing(req: ListingReviewRequest) -> ListingReviewResponse:
    """对单套房源生成 AI 优缺点 + 评分

    用户在详情弹窗点击「让 AI 帮我点评」时调用。
    带进程内缓存，同一房源 + 同一需求组合不重复消耗 token。
    """
    if not req.listing or not req.listing.id:
        raise HTTPException(400, "缺少 listing 数据")

    cache_key = _build_cache_key(req)

    if not req.force_refresh and cache_key in _review_cache:
        logger.info(f"[review 缓存命中] {req.listing.community or req.listing.title[:20]}")
        return ListingReviewResponse(review=_review_cache[cache_key], cached=True)

    logger.info(
        f"[review 生成] {req.listing.platform}/{req.listing.community or req.listing.title[:20]} "
        f"price={req.listing.price_base} cost={req.cost.total}"
    )

    review = await llm_client.review_listing(
        listing=req.listing.model_dump(),
        cost=req.cost.model_dump(),
        commute=req.commute.model_dump() if req.commute else None,
        requirement=req.requirement.model_dump() if req.requirement else None,
    )

    # 写缓存（LRU 简版：超过上限随机踢）
    if len(_review_cache) >= _REVIEW_CACHE_MAX:
        _review_cache.pop(next(iter(_review_cache)))
    _review_cache[cache_key] = review

    return ListingReviewResponse(review=review, cached=False)


@router.delete("/review/cache")
async def clear_review_cache():
    """清空 review 缓存（开发用）"""
    n = len(_review_cache)
    _review_cache.clear()
    return {"message": f"已清空 {n} 条 review 缓存"}


# ============================================================
# 详情页二次抓取 (v0.3)
# ============================================================

class ListingDetailRequest(BaseModel):
    url: str
    platform: str = "lianjia"   # "lianjia" | "beike"
    session_id: Optional[str] = None   # 有则自动将水电/押付数据写回cost
    listing_id: Optional[str] = None   # 与 session_id 配对使用


class ListingDetailResponse(BaseModel):
    success: bool
    deposit_type: Optional[str] = None
    heating_type: Optional[str] = None
    water_type: Optional[str] = None
    electricity_type: Optional[str] = None
    gas_type: Optional[str] = None
    elevator: Optional[bool] = None
    move_in: Optional[str] = None
    facilities: list[str] = []
    images: list[str] = []
    description: Optional[str] = None
    fail_reason: str = ""
    # v0.7 新增：cost 是否已更新
    cost_updated: bool = False
    cost_update_note: str = ""


@router.post("/detail", response_model=ListingDetailResponse)
async def fetch_listing_detail(req: ListingDetailRequest) -> ListingDetailResponse:
    """抓取单套房源详情页，返回列表页抓不到的增量字段。

    v0.7 新增：若提供 session_id + listing_id，抓取成功后自动将
    押付方式 / 用水类型 / 用电类型 写回 cost engine，更新 DB 成本记录。

    前端在用户打开详情 Modal 时调用，结果用于：
      - 补充押付方式（押一付一 等）→ 成本计算更准
      - 补充配套设施 → AI 点评更准
      - 补充用水/用电类型 → 水电费估算更准
      - 补充更多高清图片
    """
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(400, "url 不合法")

    # 限制只允许链家/贝壳域名，防止被用作 SSRF 探针
    allowed_hosts = ("lianjia.com", "ke.com")
    if not any(h in req.url for h in allowed_hosts):
        raise HTTPException(400, "仅支持链家/贝壳域名")

    logger.info(f"[detail] 抓取详情: {req.url[:80]}")
    result = await detail_fetcher.fetch_and_parse(req.url, req.platform)

    if result is None:
        return ListingDetailResponse(
            success=False,
            fail_reason="详情页请求失败（可能被反爬或网络超时）",
        )

    d = result.to_dict()

    # ── v0.7: 将详情字段写回 cost engine ─────────────────────────────
    cost_updated = False
    cost_update_note = ""

    if req.session_id and req.listing_id:
        try:
            updated = await _update_cost_from_detail(
                session_id=req.session_id,
                listing_id=req.listing_id,
                deposit_type=result.deposit_type,
                water_type=result.water_type,
                electricity_type=result.electricity_type,
            )
            cost_updated = updated["updated"]
            cost_update_note = updated["note"]
        except Exception as e:
            logger.warning(f"[detail] cost写回失败（不影响前端展示）: {e}")

    return ListingDetailResponse(
        success=True,
        cost_updated=cost_updated,
        cost_update_note=cost_update_note,
        **d,
    )


async def _update_cost_from_detail(
    session_id: str,
    listing_id: str,
    deposit_type: Optional[str],
    water_type: Optional[str],
    electricity_type: Optional[str],
) -> dict:
    """将详情页信息写回 session DB 的 cost 记录。

    只更新有变化的字段（水电类型/押付方式），其余保持原值。
    返回 {"updated": bool, "note": str}
    """
    if not session_db.session_exists(session_id):
        return {"updated": False, "note": "会话不存在"}

    # 没有任何有用的字段，跳过
    if not any([deposit_type, water_type, electricity_type]):
        return {"updated": False, "note": "详情页无押付/水电信息"}

    cost_rows = session_db.list_costs(session_id)
    cr = cost_rows.get(listing_id)
    if not cr:
        return {"updated": False, "note": "cost记录不存在"}

    try:
        cost = CostBreakdown.model_validate_json(cr["raw_json"])
    except Exception as e:
        return {"updated": False, "note": f"cost反序列化失败: {e}"}

    # 读取对应的 listing，取面积信息
    listing_row = session_db.get_listing(session_id, listing_id)
    area = 70.0
    listing_obj = None
    if listing_row:
        try:
            listing_obj = Listing.model_validate_json(listing_row["raw_json"])
            area = listing_obj.area or 70.0
        except Exception:
            pass

    if listing_obj is None:
        return {"updated": False, "note": "listing记录不存在"}

    # 用 cost_engine 重新计算水费、电费、押金（只覆盖这三项）
    new_cost = cost_engine.compute(
        listing_obj,
        deposit_type=deposit_type,
        water_type=water_type,
        electricity_type=electricity_type,
    )

    changed_fields = []

    # 仅更新有实际依据的字段（避免用 None 覆盖已有数据）
    if water_type:
        cost.water = new_cost.water
        cost.notes["water"] = new_cost.notes.get("water", cost.notes.get("water", ""))
        changed_fields.append(f"水费→¥{new_cost.water}({water_type})")

    if electricity_type:
        cost.electricity = new_cost.electricity
        cost.notes["electricity"] = new_cost.notes.get("electricity", cost.notes.get("electricity", ""))
        changed_fields.append(f"电费→¥{new_cost.electricity}({electricity_type})")

    if deposit_type:
        cost.deposit_cost = new_cost.deposit_cost
        cost.notes["deposit_cost"] = new_cost.notes.get("deposit_cost", cost.notes.get("deposit_cost", ""))
        changed_fields.append(f"押金成本→¥{new_cost.deposit_cost}({deposit_type})")

    if not changed_fields:
        return {"updated": False, "note": "无可更新字段"}

    session_db.upsert_costs(session_id, {listing_id: cost})
    note = f"已更新：{' / '.join(changed_fields)}"
    logger.info(f"[detail] cost写回成功 listing={listing_id[:8]} {note}")
    return {"updated": True, "note": note}
