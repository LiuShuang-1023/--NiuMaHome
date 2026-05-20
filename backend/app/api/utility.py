"""智能水电估算 API (v0.4)

POST /api/utility/estimate
  根据用户习惯问卷精算水/电/燃气，返回精算结果。

POST /api/utility/apply
  将精算结果写入指定 listing 的成本明细（更新 session DB 里的 cost 记录）。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.services.cost.utility_wizard import (
    AcLevel, ShowerLevel, CookLevel,
    UtilityWizardInput, compute_utility,
    AC_LABEL, SHOWER_LABEL, COOK_LABEL,
)
from app.services.storage import session_db
from app.models import CostBreakdown


router = APIRouter()


# ── 请求 / 响应模型 ────────────────────────────────────────────

class UtilityEstimateRequest(BaseModel):
    ac_level: AcLevel = "moderate"
    shower_level: ShowerLevel = "normal"
    cook_level: CookLevel = "daily"
    people_count: int = Field(default=1, ge=1, le=6)
    has_gas: bool = True
    water_heater_type: str = "gas"       # "gas" | "electric" | "central"
    listing_area: float = Field(default=70.0, ge=0)


class UtilityEstimateResponse(BaseModel):
    electricity: int      # 月电费（元）
    water: int            # 月水费（元）
    gas: int              # 月燃气费（元）
    total_utility: int
    electricity_kwh: float
    water_tons: float
    gas_m3: float
    notes: dict[str, str]
    delta_vs_default: int   # 与默认估算的差值（元/月）
    delta_label: str        # 人性化文案


class UtilityApplyRequest(BaseModel):
    session_id: str
    listing_id: str
    ac_level: AcLevel = "moderate"
    shower_level: ShowerLevel = "normal"
    cook_level: CookLevel = "daily"
    people_count: int = Field(default=1, ge=1, le=6)
    has_gas: bool = True
    water_heater_type: str = "gas"
    listing_area: float = 70.0
    # 手动覆盖（优先于问卷计算结果，-1 表示不覆盖）
    override_electricity: int = -1
    override_water: int = -1
    override_gas: int = -1


class UtilityApplyResponse(BaseModel):
    listing_id: str
    success: bool
    new_total: int = 0
    message: str = ""


# ── 接口：估算（不写库，纯计算）──────────────────────────────────

@router.post("/estimate", response_model=UtilityEstimateResponse)
async def estimate_utility(req: UtilityEstimateRequest) -> UtilityEstimateResponse:
    """根据问卷精算水电燃气，不修改任何数据库"""
    try:
        wh = req.water_heater_type  # type: ignore
        if wh not in ("gas", "electric", "central"):
            wh = "gas"
        inp = UtilityWizardInput(
            ac_level=req.ac_level,
            shower_level=req.shower_level,
            cook_level=req.cook_level,
            people_count=req.people_count,
            has_gas=req.has_gas,
            water_heater_type=wh,
        )
        result = compute_utility(inp, listing_area=req.listing_area)
    except Exception as e:
        logger.exception(f"[utility] 估算失败: {e}")
        raise HTTPException(500, f"估算失败: {e}")

    delta = result.delta_vs_default
    if delta > 0:
        delta_label = f"比默认估算多 ¥{delta}/月"
    elif delta < 0:
        delta_label = f"比默认估算少 ¥{abs(delta)}/月"
    else:
        delta_label = "与默认估算相同"

    return UtilityEstimateResponse(
        electricity=result.electricity,
        water=result.water,
        gas=result.gas,
        total_utility=result.total_utility,
        electricity_kwh=result.electricity_kwh,
        water_tons=result.water_tons,
        gas_m3=result.gas_m3,
        notes=result.notes,
        delta_vs_default=delta,
        delta_label=delta_label,
    )


# ── 接口：应用精算结果到指定房源 ──────────────────────────────────

@router.post("/apply", response_model=UtilityApplyResponse)
async def apply_utility(req: UtilityApplyRequest) -> UtilityApplyResponse:
    """将精算结果写回 session DB 的成本记录，覆盖水电燃气默认值"""
    if not session_db.session_exists(req.session_id):
        raise HTTPException(404, "会话不存在或已过期")

    # 读取现有 cost
    cost_rows = session_db.list_costs(req.session_id)
    cr = cost_rows.get(req.listing_id)
    if not cr:
        raise HTTPException(404, f"房源 {req.listing_id} 的成本记录不存在")

    try:
        cost = CostBreakdown.model_validate_json(cr["raw_json"])
    except Exception as e:
        raise HTTPException(500, f"成本记录反序列化失败: {e}")

    # 执行精算（即使有手动覆盖也先算一次，用于生成 notes）
    try:
        wh = req.water_heater_type
        if wh not in ("gas", "electric", "central"):
            wh = "gas"
        listing_row = session_db.get_listing(req.session_id, req.listing_id)
        area = 70.0
        if listing_row:
            from app.models import Listing
            try:
                listing = Listing.model_validate_json(listing_row["raw_json"])
                area = listing.area or 70.0
            except Exception:
                pass

        inp = UtilityWizardInput(
            ac_level=req.ac_level,
            shower_level=req.shower_level,
            cook_level=req.cook_level,
            people_count=req.people_count,
            has_gas=req.has_gas,
            water_heater_type=wh,
        )
        result = compute_utility(inp, listing_area=area)
    except Exception as e:
        logger.exception(f"[utility] 精算失败: {e}")
        raise HTTPException(500, f"精算失败: {e}")

    # 手动覆盖优先
    final_elec  = req.override_electricity if req.override_electricity >= 0 else result.electricity
    final_water = req.override_water        if req.override_water        >= 0 else result.water
    final_gas   = req.override_gas          if req.override_gas          >= 0 else result.gas

    # 更新 notes
    elec_note  = f"手动填写 ¥{final_elec}" if req.override_electricity >= 0 else result.notes.get("electricity", "")
    water_note = f"手动填写 ¥{final_water}" if req.override_water        >= 0 else result.notes.get("water", "")
    gas_note   = f"手动填写 ¥{final_gas}"   if req.override_gas          >= 0 else result.notes.get("gas", "")

    # 更新 cost 字段
    cost.electricity = final_elec
    cost.water       = final_water
    cost.gas         = final_gas
    cost.notes.update({
        "electricity": elec_note,
        "water":       water_note,
        "gas":         gas_note,
    })

    # 写回 DB
    session_db.upsert_costs(req.session_id, {req.listing_id: cost})

    logger.info(
        f"[utility] apply: listing={req.listing_id[:8]} "
        f"elec={result.electricity} water={result.water} gas={result.gas} "
        f"total={cost.total}"
    )

    return UtilityApplyResponse(
        listing_id=req.listing_id,
        success=True,
        new_total=cost.total,
        message=f"水电燃气已按你的习惯精算，月总支出更新为 ¥{cost.total}",
    )


# ── 接口：返回问卷选项（供前端渲染）──────────────────────────────

class WizardOptions(BaseModel):
    ac: list[dict]
    shower: list[dict]
    cook: list[dict]


@router.get("/options", response_model=WizardOptions)
async def get_wizard_options() -> WizardOptions:
    """返回问卷所有选项（value + label），供前端渲染选择"""
    return WizardOptions(
        ac=[{"value": k, "label": v} for k, v in AC_LABEL.items()],
        shower=[{"value": k, "label": v} for k, v in SHOWER_LABEL.items()],
        cook=[{"value": k, "label": v} for k, v in COOK_LABEL.items()],
    )
