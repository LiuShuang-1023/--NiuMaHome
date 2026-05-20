"""Anthropic Claude 客户端"""
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.services.llm.base import BaseLLMClient


class ClaudeClient(BaseLLMClient):
    """Anthropic Claude"""

    provider_name = "claude"

    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model = settings.ANTHROPIC_MODEL
        self.client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and self.client is not None

    async def _call_api(self, system_prompt: str, messages: list[dict]) -> str:
        # Claude 的 system 是独立参数，不放在 messages 里
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
