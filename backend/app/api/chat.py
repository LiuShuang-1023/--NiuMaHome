"""Chat API - AI 对话接口"""
from fastapi import APIRouter
from loguru import logger

from app.models import ChatRequest, ChatResponse
from app.services.llm.factory import llm_client

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    AI 对话接口

    用户在前端对话框输入需求，后端调用 LLM 解析为结构化需求 JSON。
    AI 会反问澄清模糊点，直到 is_ready=true 才可触发搜索。

    LLM 提供商通过 .env.local 中 LLM_PROVIDER 切换 (deepseek/claude)。
    """
    logger.info(f"收到对话请求，消息数: {len(req.messages)}, provider={llm_client.provider_name}")
    response = await llm_client.chat(
        messages=req.messages,
        current_requirement=req.current_requirement,
    )
    logger.info(f"AI 回复，is_ready={response.is_ready}")
    return response
