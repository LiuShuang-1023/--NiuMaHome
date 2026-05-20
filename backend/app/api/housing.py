"""
保障房 / 人才公寓 / 青年公寓政策查询 API  (v0.9.0)

GET  /api/housing/policy_info?city=广州&type=all
POST /api/housing/policy_ai          AI 搜索生成城市政策摘要（DeepSeek）并写入本地缓存
GET  /api/housing/stale_check        手动触发"过期城市"刷新（4个月自查）
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, BackgroundTasks
from pydantic import BaseModel, Field
from loguru import logger

from app.services.llm.factory import llm_client
from app.api.agent import _extract_text
from app.services.storage.housing_cache import (
    get_cached,
    save_cache,
    list_stale_cities,
)

router = APIRouter()

# ── 静态政策数据库（各城市官方入口 + 核心条件摘要）────────────────
POLICY_DB: dict[str, dict] = {
    "广州": {
        "public_rental": {
            "name": "公共租赁住房（公租房）",
            "apply_url": "https://zfcj.gz.gov.cn/zfbz/ggzlzf/",
            "app": "穗好办",
            "conditions": [
                "广州市户籍，或具有1年以上合法稳定就业证明",
                "家庭年人均收入 ≤ 49952 元",
                "无自有产权住房，或人均住房面积 < 15m²",
                "未享受其他购房保障优惠政策",
            ],
            "rent_discount": "市场价 60%-80%",
            "notes": "轮候期约1-3年；低保户可免租金",
        },
        "talent_apartment": {
            "name": "人才公寓",
            "apply_url": "https://zfcj.gz.gov.cn/",
            "app": "穗好办 / 各区住建局公众号",
            "conditions": [
                "本科及以上学历或中级以上职称",
                "在穗就业并缴纳社保",
                "申请人及配偶在广州无自有产权住房",
                "不符合学历条件者年薪需 ≥ 30 万元",
            ],
            "rent_discount": "市场价 70%-85%（各区不同）",
            "notes": "租期一般3年，到期可续租；各区名额有限，按需申请",
        },
        "youth_apartment": {
            "name": "青年公寓（港澳台青年住房）",
            "apply_url": "https://zfcj.gz.gov.cn/",
            "conditions": [
                "年龄 ≤ 44 周岁，持有效港澳台居民居住证",
                "在穗就业创业，连续缴纳养老保险 ≥ 3 个月",
                "大专及以上学历",
                "无广州市自有产权住房",
            ],
            "rent_discount": "低于市场评估价 20%（南沙可达 50%）",
            "notes": "租金补贴：大专6000元、本科9000元、硕士15000元、博士20000元",
        },
    },
    "北京": {
        "public_rental": {
            "name": "公共租赁住房（公租房）",
            "apply_url": "https://www.bphc.com.cn/home",
            "app": "京通小程序 / i-Beijing APP",
            "conditions": [
                "北京市户籍家庭，或具有本市工作居住证（工作证）",
                "无本市自有产权住房或人均住房面积不足",
                "家庭收入符合当年公示的准入标准",
            ],
            "rent_discount": "市场价 60%-80%",
            "notes": "海淀区青年公寓面向近3年毕业大学生，可通过北京保障房中心官网申请",
        },
        "talent_apartment": {
            "name": "人才公寓 / 青年公寓",
            "apply_url": "https://www.bphc.com.cn/home",
            "app": "北京海淀APP / 各区政务网",
            "conditions": [
                "近3年毕业的本科及以上大学毕业生（海淀区）",
                "在京就业并缴纳社保",
                "无本市自有产权住房",
            ],
            "rent_discount": "市场价 70%-85%",
            "notes": "各区政策不同，请以具体区住建局通知为准",
        },
        "youth_apartment": {
            "name": "青年人才驿站（短期过渡）",
            "apply_url": "https://www.beijing.gov.cn/",
            "conditions": [
                "应届高校毕业生（毕业当年），在京求职",
                "未在北京落实工作单位",
                "提前在网上预约",
            ],
            "rent_discount": "免费入住 14 天（部分驿站可延至 30 天）",
            "notes": "主要为求职过渡，非长期租赁；部分驿站提供餐饮补贴",
        },
    },
    "上海": {
        "public_rental": {
            "name": "公共租赁住房（公租房）",
            "apply_url": "http://fgj.sh.gov.cn/ggzlzfgsgg/index.html",
            "app": "随申办 小程序 / APP",
            "conditions": [
                "具有上海市常住户口，或持有效期内《上海市居住证》",
                "与上海就业单位签订 ≥ 1 年劳动合同并缴纳社保",
                "家庭人均住房面积 < 15m²",
                "未享受其他保障性住房政策",
            ],
            "rent_discount": "市场价 80%-90%",
            "notes": "审核通过后随机摇号分配；可在随申办查询轮候进度",
        },
        "talent_apartment": {
            "name": "人才公寓（临港、张江等科技园区）",
            "apply_url": "https://rcfw.lingang.gov.cn/",
            "app": "临港人才公寓官网（仅PC端）",
            "conditions": [
                "在临港/张江科学城就业或创业",
                "具有大专及以上学历或中级以上职称",
                "无上海市自有产权住房",
            ],
            "rent_discount": "低于市场价 20%-30%",
            "notes": "各园区名额有限，需联系所在企业人事统一申请；杨浦、宝山等区亦有人才公寓",
        },
        "youth_apartment": {
            "name": "青年人才公寓",
            "apply_url": "https://www.shanghai.gov.cn/",
            "conditions": [
                "全日制本科及以上学历，年龄 ≤ 35 周岁",
                "在沪工作或创业，缴纳社保",
                "无上海市自有产权住房",
            ],
            "rent_discount": "低于市场价 15%-25%",
            "notes": "具体项目以各区住建委通知为准，建议关注所在区官方公众号",
        },
    },
    "深圳": {
        "public_rental": {
            "name": "公共租赁住房（公租房）",
            "apply_url": "http://zjj.sz.gov.cn/ztfw/zfbz/",
            "app": "i深圳 APP",
            "conditions": [
                "具有深圳户籍，或持有效深圳市居住证",
                "在深圳连续缴纳社保 ≥ 1 年",
                "无深圳市自有产权住房",
                "家庭收入符合当年公示准入标准",
            ],
            "rent_discount": "市场价 60%-80%",
            "notes": "轮候申请通过 i深圳 APP 或深圳市住建局官网进行",
        },
        "talent_apartment": {
            "name": "人才住房（租住型 / 可售型）",
            "apply_url": "http://zjj.sz.gov.cn/ztfw/zfbz/",
            "app": "i深圳 APP → 青年人才服务保障专区",
            "conditions": [
                "全日制本科及以上学历，应届毕业5年内（部分项目）",
                "在深就业并缴纳社保",
                "无深圳市自有产权住房",
            ],
            "rent_discount": "市场价 70%-85%",
            "notes": "福田区2024年已面向港澳台及外籍人才配租保障性租赁住房",
        },
        "youth_apartment": {
            "name": "青年人才驿站 / 过渡性住房",
            "apply_url": "http://zjj.sz.gov.cn/",
            "app": "i深圳 APP → 青年人才服务保障专区",
            "conditions": [
                "应届高校毕业生，在深求职",
                "提前在线预约，免费入住最长30天",
            ],
            "rent_discount": "免费（过渡性）",
            "notes": "过渡性住房解决短期住宿问题；长期可申请青年人才租住型住房",
        },
    },
    "成都": {
        "public_rental": {
            "name": "公共租赁住房",
            "apply_url": "https://zw.cdzjryb.com/hsweb_portal/#/",
            "app": "天府市民云 APP",
            "conditions": [
                "具有成都市户籍，或在蓉就业并连续缴纳社保 ≥ 6 个月",
                "无成都市自有产权住房",
                "家庭月人均可支配收入 ≤ 当年公示标准",
            ],
            "rent_discount": "市场价 70%-85%",
            "notes": "成都市住房保障服务平台 zw.cdzjryb.com 可在线申请",
        },
        "talent_apartment": {
            "name": "人才公寓 / 青年公寓",
            "apply_url": "https://rc.chengdu.gov.cn/",
            "conditions": [
                "全日制本科及以上学历或中级以上职称",
                "在蓉就业创业，缴纳社保",
                "无成都市自有产权住房",
            ],
            "rent_discount": "低于市场价 20%-30%",
            "notes": "蓉漂人才驿站提供免费短期（7天）过渡住房给应届毕业生",
        },
    },
    "杭州": {
        "public_rental": {
            "name": "公共租赁住房",
            "apply_url": "https://www.hangzhou.gov.cn/",
            "app": "浙里办 APP",
            "conditions": [
                "具有杭州市区户籍，或在杭工作并连续缴纳社保 ≥ 1 年",
                "无杭州市区自有产权住房",
                "家庭月人均可支配收入符合公示标准",
            ],
            "rent_discount": "市场价 70%-80%",
            "notes": "可通过浙里办 APP 一键申请，支持在线审核",
        },
        "talent_apartment": {
            "name": "人才专项租赁住房",
            "apply_url": "https://rsj.hangzhou.gov.cn/",
            "conditions": [
                "大专及以上学历，在杭就业创业",
                "缴纳杭州社保，无市区自有产权住房",
            ],
            "rent_discount": "低于市场价 20%-25%",
            "notes": "杭州推行「房票」制度，部分人才可领取租房补贴",
        },
    },
}

_POLICY_AI_SYSTEM = """你是一个中国租房政策专家助手。请根据用户提供的城市名，简要介绍该城市最新的：
1. 公共租赁住房（公租房）申请条件和官方渠道
2. 人才公寓申请条件
3. 青年公寓政策
每部分控制在 100 字以内，列出要点即可。结尾给出官方查询建议（搜索引擎关键词或官网名称）。
用中文输出，不要 markdown 标题，自然分段即可。"""


# ── 响应模型 ──────────────────────────────────────────────────────

class PolicyAIRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=20)
    housing_type: str = "all"


class HousingTypeInfo(BaseModel):
    name: str
    apply_url: str = ""
    app: str = ""
    conditions: list[str] = []
    rent_discount: str = ""
    notes: str = ""


class PolicyInfoResponse(BaseModel):
    city: str
    source: str                     # "db" | "ai" | "ai_cache" | "not_found"
    public_rental: HousingTypeInfo | None = None
    talent_apartment: HousingTypeInfo | None = None
    youth_apartment: HousingTypeInfo | None = None
    ai_summary: str = ""
    fetched_at: str = ""            # 首次获取时间（ISO8601 UTC）
    updated_at: str = ""            # 最近更新时间
    is_stale: bool = False          # True = 超过4个月，建议重新 AI 查询
    disclaimer: str = "政策信息仅供参考，请以城市住建局官网最新公告为准。"


# ── 工具函数 ───────────────────────────────────────────────────────

def _build_type_info(data: dict, key: str) -> HousingTypeInfo | None:
    d = data.get(key)
    return HousingTypeInfo(**d) if d else None


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ── 接口 ──────────────────────────────────────────────────────────

@router.get("/policy_info", response_model=PolicyInfoResponse)
async def get_policy_info(
    city: str = Query(..., min_length=1, max_length=20),
) -> PolicyInfoResponse:
    """
    优先从本地缓存读取（静态DB城市永不过期；AI城市超120天标记 is_stale）。
    若本地无缓存且不在静态DB中，返回 not_found，前端引导调用 /policy_ai。
    """
    # 1. 静态DB命中
    data = POLICY_DB.get(city)
    if data:
        # 把静态DB也写入缓存（便于追踪入库时间）
        payload = {
            "public_rental": data.get("public_rental"),
            "talent_apartment": data.get("talent_apartment"),
            "youth_apartment": data.get("youth_apartment"),
        }
        cached = get_cached(city)
        if not cached:
            fetched_at = save_cache(city, "db", payload)
        else:
            fetched_at = cached["fetched_at"]
        updated_at = _now_iso()

        return PolicyInfoResponse(
            city=city,
            source="db",
            public_rental=_build_type_info(data, "public_rental"),
            talent_apartment=_build_type_info(data, "talent_apartment"),
            youth_apartment=_build_type_info(data, "youth_apartment"),
            fetched_at=fetched_at,
            updated_at=updated_at,
            is_stale=False,
        )

    # 2. 本地AI缓存命中
    cached = get_cached(city)
    if cached:
        p = cached["payload"]
        def _rebuild(key: str) -> HousingTypeInfo | None:
            d = p.get(key)
            return HousingTypeInfo(**d) if d else None
        return PolicyInfoResponse(
            city=city,
            source="ai_cache",
            public_rental=_rebuild("public_rental"),
            talent_apartment=_rebuild("talent_apartment"),
            youth_apartment=_rebuild("youth_apartment"),
            ai_summary=p.get("ai_summary", ""),
            fetched_at=cached["fetched_at"],
            updated_at=cached["updated_at"],
            is_stale=cached["is_stale"],
        )

    # 3. 未找到
    return PolicyInfoResponse(
        city=city,
        source="not_found",
        disclaimer=f"暂未收录「{city}」的政策数据。请点击「AI 查询」获取实时摘要。",
    )


@router.post("/policy_ai", response_model=PolicyInfoResponse)
async def policy_ai_query(req: PolicyAIRequest) -> PolicyInfoResponse:
    """
    调用 AI 生成指定城市政策摘要，并写入本地缓存（过期城市可重新调用刷新）。
    """
    # 静态DB优先
    data = POLICY_DB.get(req.city)
    if data:
        return await get_policy_info(city=req.city)

    # 调用AI
    if not llm_client.is_configured:
        return PolicyInfoResponse(
            city=req.city,
            source="ai_unavailable",
            ai_summary=(
                f"AI 服务未配置，无法自动查询「{req.city}」政策。"
                f"建议直接搜索「{req.city} 住建局 公租房申请」。"
            ),
        )

    prompt = (
        f"请简要介绍「{req.city}」的公共租赁住房（公租房）、人才公寓、青年公寓政策，"
        f"包括申请条件、租金折扣和官方申请渠道（App 或网站名称）。"
    )
    try:
        raw = await llm_client._call_api(
            _POLICY_AI_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
        summary = _extract_text(raw).strip()
        logger.info(f"[housing/policy_ai] AI 生成成功 city={req.city}")
    except Exception as e:
        logger.warning(f"[housing/policy_ai] AI 失败: {e}")
        summary = (
            f"AI 暂时无法查询「{req.city}」政策。\n"
            f"建议在搜索引擎中搜索：「{req.city} 住建局 公租房」"
        )

    payload = {"ai_summary": summary}
    fetched_at = save_cache(req.city, "ai", payload)

    return PolicyInfoResponse(
        city=req.city,
        source="ai",
        ai_summary=summary,
        fetched_at=fetched_at,
        updated_at=fetched_at,
        is_stale=False,
    )


@router.get("/stale_check")
async def stale_check(background_tasks: BackgroundTasks):
    """
    列出所有过期（>120天）的 AI 缓存城市，后台异步刷新它们。
    可手动调用，也可由外部 cron 定期触发（每4个月一次）。
    """
    stale = list_stale_cities()
    if not stale:
        return {"message": "所有 AI 缓存均在有效期内", "stale_cities": []}

    async def _refresh_all():
        for city in stale:
            try:
                req = PolicyAIRequest(city=city)
                await policy_ai_query(req)
                logger.info(f"[housing/stale_check] 已刷新 {city}")
            except Exception as e:
                logger.warning(f"[housing/stale_check] 刷新 {city} 失败: {e}")

    background_tasks.add_task(_refresh_all)
    return {
        "message": f"后台刷新已启动，共 {len(stale)} 个城市",
        "stale_cities": stale,
    }
