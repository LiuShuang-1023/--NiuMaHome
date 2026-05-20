"""LLM 提供商工厂 - 按配置选择"""
from loguru import logger

from app.core.config import settings
from app.services.llm.base import BaseLLMClient
from app.services.llm.claude import ClaudeClient
from app.services.llm.deepseek import DeepSeekClient


def create_llm_client() -> BaseLLMClient:
    """根据 settings.LLM_PROVIDER 创建对应客户端"""
    provider = (settings.LLM_PROVIDER or "deepseek").lower().strip()

    if provider == "claude" or provider == "anthropic":
        client = ClaudeClient()
    elif provider == "deepseek":
        client = DeepSeekClient()
    else:
        logger.warning(f"未知 LLM_PROVIDER={provider}，回退到 deepseek")
        client = DeepSeekClient()

    if client.is_configured:
        logger.info(f"✅ LLM Provider: {client.provider_name} (model={getattr(client, 'model', '?')})")
    else:
        logger.warning(f"⚠️ LLM Provider: {client.provider_name} 未配置 API Key，将使用 mock 模式")

    return client


# 全局单例
llm_client: BaseLLMClient = create_llm_client()
