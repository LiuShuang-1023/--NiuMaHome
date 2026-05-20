"""房补政策分析 API (v0.6/v0.7)

POST /api/subsidy/analyze
  解析公司房补政策文本 → 提取通勤限制条件 → 返回结构化筛选参数

POST /api/subsidy/filter
  将房补距离限制（distance_km）应用到当前 session，
  基于 haversine 直线距离过滤，返回符合条件的 listing_id 列表
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from loguru import logger
import json
import re
import math
from typing import Optional

from app.services.llm.factory import llm_client
from app.services.storage import session_db
from app.models import Listing

router = APIRouter()

# ============================================================
# 请求/响应模型
# ============================================================

class SubsidyAnalyzeRequest(BaseModel):
    policy_text: str = Field(..., min_length=5, max_length=3000, description="公司房补政策原文")


class CommuteCondition(BaseModel):
    """单条通勤限制（一个交通方式+时间限制）"""
    mode: str = Field(..., description="交通方式: transit/riding/walking/any")
    max_minutes: int = Field(..., description="最大允许分钟数")
    description: str = Field(..., description="原文描述，如「骑行20分钟以内」")


class SubsidyAnalyzeResponse(BaseModel):
    """AI 解析结果"""
    summary: str = Field(..., description="一句话总结政策核心限制")
    conditions: list[CommuteCondition] = Field(default_factory=list, description="通勤限制条件列表（任满足一条即可）")
    logic: str = Field(default="any", description="条件间关系: any=满足任一 / all=必须全满足")
    recommended_max_minutes: int = Field(..., description="建议的搜索最大通勤时间（取所有条件最大值）")
    recommended_modes: list[str] = Field(default_factory=list, description="建议启用的通勤方式")
    has_distance_limit: bool = Field(default=False, description="是否有距离限制（公里数）")
    distance_km: float | None = Field(default=None, description="距离限制（公里）")
    notes: str = Field(default="", description="补充说明（如需要提交材料、截图等）")
    raw_parsed: dict = Field(default_factory=dict, description="AI返回的原始解析数据")


# ============================================================
# 提示词
# ============================================================

SUBSIDY_ANALYZE_PROMPT = """你是一个专业的 HR 政策分析助手，负责解析公司住房补贴政策文本，提取通勤距离/时间限制条件。

## 分析目标
从政策文本中提取：
1. **通勤限制条件**：如「骑行20分钟以内」「公共交通30分钟以内」「步行30分钟」等
2. **交通方式要求**：具体哪种出行方式算数（注意：有些公司只认自行车骑行，不算电动车/摩托）
3. **逻辑关系**：多条件是"满足任一即可"还是"必须全满足"（通常是任一）
4. **距离限制**：是否有公里数限制（如"5公里以内"）

## 交通方式映射规则
- 骑行/自行车/单车 → mode: "riding"（注意：若说"电动车"或"摩托车"则不算riding，标注为special）
- 公共交通/地铁/公交/轨道交通 → mode: "transit"
- 步行/徒步 → mode: "walking"
- 不限交通方式 / 任意方式 → mode: "any"

## 输出格式（严格 JSON）
```json
{
  "summary": "一句话总结，如：骑行20分钟或公共交通30分钟以内",
  "conditions": [
    {
      "mode": "riding",
      "max_minutes": 20,
      "description": "骑行20分钟以内（仅限自行车）"
    },
    {
      "mode": "transit",
      "max_minutes": 30,
      "description": "公共交通30分钟以内"
    }
  ],
  "logic": "any",
  "recommended_max_minutes": 30,
  "recommended_modes": ["riding", "transit"],
  "has_distance_limit": false,
  "distance_km": null,
  "notes": "补充说明，如需要提交乘车记录截图、只限工作日等"
}
```

## 特殊情况处理
- 如果政策只说「步行X分钟」→ 也要在 recommended_modes 里加 "walking"
- 如果说「公司5公里范围内」→ has_distance_limit=true, distance_km=5.0，mode="any", max_minutes=0（用距离筛）
- 如果政策不清晰或未提通勤限制 → summary 说明，conditions 返回空数组
- recommended_max_minutes 取 conditions 中最大的 max_minutes（距离限制时取 999）
"""


def _parse_subsidy_json(raw: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    # 优先提取 markdown 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 兜底：直接找 { ... }
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return {}


# ============================================================
# 端点
# ============================================================

@router.post("/analyze", response_model=SubsidyAnalyzeResponse)
async def analyze_subsidy(req: SubsidyAnalyzeRequest):
    """
    解析房补政策文本，提取通勤限制条件。
    返回结构化筛选参数，供前端直接用于房源筛选。
    """
    logger.info(f"[subsidy/analyze] 解析政策文本 ({len(req.policy_text)} 字)")

    prompt = f"""请分析以下公司住房补贴政策文本，提取通勤限制条件：

---
{req.policy_text}
---

按照系统指令格式返回 JSON。"""

    try:
        raw = await llm_client._call_api(
            SUBSIDY_ANALYZE_PROMPT,
            [{"role": "user", "content": prompt}],
        )
        logger.debug(f"[subsidy/analyze] LLM 原始回复: {raw[:200]}...")
    except Exception as e:
        logger.error(f"[subsidy/analyze] LLM 调用失败: {e}")
        # 降级：返回一个默认结果，前端可以手动填写
        return SubsidyAnalyzeResponse(
            summary="AI 解析暂时失败，请手动设置通勤限制",
            conditions=[],
            logic="any",
            recommended_max_minutes=30,
            recommended_modes=["transit", "riding", "walking"],
            notes=f"解析失败原因：{str(e)[:100]}",
        )

    parsed = _parse_subsidy_json(raw)
    if not parsed:
        logger.warning("[subsidy/analyze] JSON 解析失败，返回空结果")
        return SubsidyAnalyzeResponse(
            summary="未能识别到明确的通勤限制条件，请检查政策文本",
            conditions=[],
            logic="any",
            recommended_max_minutes=60,
            recommended_modes=["transit", "riding", "walking"],
        )

    # 构建响应
    conditions = []
    for c in parsed.get("conditions", []):
        try:
            conditions.append(CommuteCondition(
                mode=c.get("mode", "any"),
                max_minutes=int(c.get("max_minutes", 30)),
                description=c.get("description", ""),
            ))
        except Exception:
            continue

    recommended_max = int(parsed.get("recommended_max_minutes", 60))
    if not recommended_max and conditions:
        recommended_max = max(c.max_minutes for c in conditions)

    return SubsidyAnalyzeResponse(
        summary=parsed.get("summary", ""),
        conditions=conditions,
        logic=parsed.get("logic", "any"),
        recommended_max_minutes=recommended_max,
        recommended_modes=parsed.get("recommended_modes", ["transit", "riding", "walking"]),
        has_distance_limit=bool(parsed.get("has_distance_limit", False)),
        distance_km=parsed.get("distance_km"),
        notes=parsed.get("notes", ""),
        raw_parsed=parsed,
    )


# ============================================================
# 距离筛选端点（v0.7）
# ============================================================

def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Haversine 公式计算两点直线距离（km）"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


class SubsidyFilterRequest(BaseModel):
    session_id: str = Field(..., description="当前会话 ID")
    distance_km: float = Field(..., gt=0, description="直线距离上限（公里）")


class SubsidyFilterResponse(BaseModel):
    matched_listing_ids: list[str] = Field(default_factory=list, description="符合距离限制的 listing_id 列表")
    total_checked: int = 0
    total_matched: int = 0
    no_coord_count: int = 0     # 无坐标无法判断（默认放行）
    dest_coord: Optional[list[float]] = None  # [lng, lat]
    message: str = ""


@router.post("/filter", response_model=SubsidyFilterResponse)
async def filter_by_distance(req: SubsidyFilterRequest) -> SubsidyFilterResponse:
    """按直线距离过滤当前 session 的所有房源。

    读取 session 中的目的地坐标和所有房源坐标，
    计算 haversine 直线距离，返回距离 <= distance_km 的 listing_id 列表。
    无坐标的房源默认放行（不排除）。
    """
    logger.info(f"[subsidy/filter] session={req.session_id[:8]} distance_km={req.distance_km}")

    if not session_db.session_exists(req.session_id):
        return SubsidyFilterResponse(
            message="会话不存在或已过期，请重新搜索",
        )

    # 读取目的地坐标
    session_row = session_db.get_session(req.session_id)
    if not session_row:
        return SubsidyFilterResponse(message="会话数据不存在")

    dest_lng = session_row.get("dest_lng")
    dest_lat = session_row.get("dest_lat")

    if dest_lng is None or dest_lat is None:
        return SubsidyFilterResponse(
            message="当前搜索无目的地坐标，无法按距离筛选",
        )

    # 读取所有房源
    listing_rows = session_db.list_listings(req.session_id, include_filtered=False)
    matched_ids: list[str] = []
    no_coord = 0

    for lr in listing_rows:
        lid = lr["listing_id"]
        lng = lr.get("geo_lng")
        lat = lr.get("geo_lat")

        # 无坐标：尝试从 raw_json 里读
        if lng is None or lat is None:
            try:
                listing_obj = Listing.model_validate_json(lr["raw_json"])
                lng = listing_obj.geo_lng
                lat = listing_obj.geo_lat
            except Exception:
                pass

        if lng is None or lat is None:
            # 无坐标默认放行
            matched_ids.append(lid)
            no_coord += 1
            continue

        dist = _haversine_km(lng, lat, dest_lng, dest_lat)
        if dist <= req.distance_km:
            matched_ids.append(lid)

    total = len(listing_rows)
    matched = len(matched_ids)
    logger.info(f"[subsidy/filter] 检查={total} 符合={matched} 无坐标放行={no_coord}")

    return SubsidyFilterResponse(
        matched_listing_ids=matched_ids,
        total_checked=total,
        total_matched=matched,
        no_coord_count=no_coord,
        dest_coord=[dest_lng, dest_lat],
        message=f"距目的地 {req.distance_km}km 以内：{matched}/{total} 套房源符合（其中 {no_coord} 套无坐标已默认放行）",
    )
