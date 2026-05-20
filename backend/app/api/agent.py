"""Agent 小助手 API (v0.5)

POST /api/agent/ask
  通用问答，可附带房源上下文

POST /api/agent/inquiry
  生成站内信询问文案（AI生成 or 模板生成）

POST /api/agent/batch_inquiry
  批量为多个收藏房源生成站内信
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from loguru import logger

from app.services.llm.factory import llm_client
from app.services.llm.agent_prompts import (
    AGENT_SYSTEM_PROMPT,
    build_agent_context_prompt,
    build_inquiry_message,
)

router = APIRouter()


# ── 工具函数 ─────────────────────────────────────────────────────

def _extract_text(raw: str) -> str:
    """
    DeepSeek 强制 JSON 模式时会把回答包在 {"answer": "..."} 里。
    先尝试 JSON 解析取 answer/text/content/message 字段；
    若不是 JSON 则直接返回原文。
    """
    import json
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            for key in ("answer", "text", "content", "message", "result"):
                if key in obj and isinstance(obj[key], str):
                    return obj[key]
            values = [v for v in obj.values() if isinstance(v, str)]
            if len(values) == 1:
                return values[0]
        except Exception:
            pass
    return stripped


# ── 请求/响应模型 ────────────────────────────────────────────────

class AgentAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    # 可选：附带当前查看的房源上下文，让 Agent 回答更精准
    listing_context: dict | None = None


class AgentAskResponse(BaseModel):
    answer: str
    is_inquiry_template: bool = False  # 是否包含站内信模板


class InquiryItem(BaseModel):
    listing_id: str
    listing_title: str = ""
    listing_community: str = ""
    listing_url: str = ""
    platform: str = ""
    # 要询问的具体项目（空=全部默认项）
    items_to_ask: list[str] = Field(default_factory=list)


class InquiryRequest(BaseModel):
    listing_id: str
    listing_title: str = ""
    listing_community: str = ""
    listing_url: str = ""
    platform: str = ""
    items_to_ask: list[str] = Field(default_factory=list)
    use_ai: bool = True   # True=AI生成更个性化；False=模板生成（快）


class InquiryResponse(BaseModel):
    listing_id: str
    message: str           # 生成的站内信正文
    listing_url: str       # 房源链接（用于跳转）
    platform_label: str    # 平台名称
    copy_hint: str         # 提示文案


class BatchInquiryRequest(BaseModel):
    listings: list[InquiryItem]
    use_ai: bool = False   # 批量默认用模板（快、不烧token）


class BatchInquiryResponse(BaseModel):
    results: list[InquiryResponse]
    total: int


# ── 工具函数 ─────────────────────────────────────────────────────

PLATFORM_LABEL = {
    "lianjia": "链家",
    "beike": "贝壳",
    "anjuke": "安居客",
    "ziroom": "自如",
}

def _platform_label(platform: str) -> str:
    return PLATFORM_LABEL.get(platform.lower(), platform)


def _copy_hint(platform: str, url: str) -> str:
    label = _platform_label(platform)
    if url:
        return f"请复制上方文案，打开 {label} 房源页面，点击「联系TA」发送私信给经纪人/房东。"
    return f"请复制上方文案，在 {label} App 内找到该房源，点击「联系TA」发送私信。"


# ── 接口：通用问答 ────────────────────────────────────────────────

@router.post("/ask", response_model=AgentAskResponse)
async def agent_ask(req: AgentAskRequest) -> AgentAskResponse:
    """Agent 通用问答（水电怎么算、通勤怎么查等）"""
    user_msg = build_agent_context_prompt(
        question=req.question,
        listing_context=req.listing_context,
    )
    messages = [{"role": "user", "content": user_msg}]

    try:
        raw = await llm_client._call_api(AGENT_SYSTEM_PROMPT, messages)
        text = _extract_text(raw).strip()
        is_inquiry = "---站内信---" in text
        return AgentAskResponse(answer=text, is_inquiry_template=is_inquiry)
    except Exception as e:
        logger.exception(f"[agent/ask] 失败: {e}")
        return AgentAskResponse(
            answer=f"抱歉，AI 暂时不可用（{str(e)[:80]}）。请稍后再试。",
        )


# ── 接口：生成站内信（单条）────────────────────────────────────────

@router.post("/inquiry", response_model=InquiryResponse)
async def generate_inquiry(req: InquiryRequest) -> InquiryResponse:
    """为单套房源生成发给经纪人的询问站内信"""
    msg_body = ""

    if req.use_ai and llm_client.is_configured:
        items_str = "、".join(req.items_to_ask) if req.items_to_ask else "水费单价、电费单价、燃气费、物业费、网络费"
        community = req.listing_community or req.listing_title or "该房源"
        # 不要求特殊格式标记，直接让 AI 输出站内信正文
        # DeepSeek JSON 模式下会包在 {"answer":"..."} 里，_extract_text 负责解包
        prompt = (
            f"请帮我写一条发给房东/经纪人的租房询问站内信。\n"
            f"房源：{community}\n"
            f"需要询问的内容：{items_str}\n"
            f"要求：礼貌真诚、简洁自然，像真实租客写的，100-150字，"
            f"直接输出站内信正文，不要任何标题或说明。"
        )
        try:
            raw = await llm_client._call_api(AGENT_SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
            extracted = _extract_text(raw).strip()
            # 如果提取结果还包含 ---站内信--- 标记则再次清理
            import re as _re
            m = _re.search(r"---站内信---\s*(.*?)\s*(?:---结束---|$)", extracted, _re.DOTALL)
            msg_body = m.group(1).strip() if m else extracted
            logger.info(f"[agent/inquiry] AI 生成成功，长度={len(msg_body)}")
        except Exception as e:
            logger.warning(f"[agent/inquiry] AI 生成失败，降级到模板: {e}")

    # AI 失败 / 未配置 / 结果为空 → 用本地模板
    if not msg_body:
        msg_body = build_inquiry_message(
            req.listing_title, req.listing_community, req.items_to_ask
        )

    return InquiryResponse(
        listing_id=req.listing_id,
        message=msg_body,
        listing_url=req.listing_url,
        platform_label=_platform_label(req.platform),
        copy_hint=_copy_hint(req.platform, req.listing_url),
    )


# ── 接口：批量生成站内信（收藏夹批量发送）────────────────────────────

@router.post("/batch_inquiry", response_model=BatchInquiryResponse)
async def batch_inquiry(req: BatchInquiryRequest) -> BatchInquiryResponse:
    """为多个收藏房源批量生成站内信（默认用模板，快速）"""
    results = []
    for item in req.listings[:10]:
        if req.use_ai and llm_client.is_configured:
            msg_body = await _ai_inquiry(item)
        else:
            msg_body = build_inquiry_message(
                item.listing_title, item.listing_community, item.items_to_ask
            )
        results.append(InquiryResponse(
            listing_id=item.listing_id,
            message=msg_body,
            listing_url=item.listing_url,
            platform_label=_platform_label(item.platform),
            copy_hint=_copy_hint(item.platform, item.listing_url),
        ))

    return BatchInquiryResponse(results=results, total=len(results))


async def _ai_inquiry(item: InquiryItem) -> str:
    """单条 AI 生成，失败降级模板"""
    try:
        items_str = "、".join(item.items_to_ask) if item.items_to_ask else "水费单价、电费单价、燃气费、物业费、网络费"
        community = item.listing_community or item.listing_title or "该房源"
        prompt = (
            f"请帮我写一条发给房东/经纪人的租房询问站内信。\n"
            f"房源：{community}\n"
            f"需要询问的内容：{items_str}\n"
            f"要求：礼貌真诚、简洁自然，100-150字，直接输出正文，不要任何标题。"
        )
        raw = await llm_client._call_api(AGENT_SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
        result = _extract_text(raw).strip()
        return result if result else build_inquiry_message(
            item.listing_title, item.listing_community, item.items_to_ask
        )
    except Exception:
        return build_inquiry_message(item.listing_title, item.listing_community, item.items_to_ask)
