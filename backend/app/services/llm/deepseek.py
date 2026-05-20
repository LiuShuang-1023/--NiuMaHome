"""DeepSeek 客户端

DeepSeek 使用 OpenAI 兼容协议
文档: https://api-docs.deepseek.com/zh-cn/

价格（截至 2025）：
- deepseek-chat: ¥1/百万 输入 token, ¥2/百万 输出 token（极便宜）
- 国内直连，无需梯子
"""
import asyncio

from loguru import logger
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.services.llm.base import BaseLLMClient


class DeepSeekClient(BaseLLMClient):
    """DeepSeek - OpenAI 兼容协议"""

    provider_name = "deepseek"

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY
        self.model = settings.DEEPSEEK_MODEL
        self.base_url = settings.DEEPSEEK_BASE_URL
        if self.api_key:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0,  # 加大超时到 60 秒，DeepSeek 高峰期可能慢
                max_retries=0,  # 关闭 SDK 自带重试，我们手动控制
            )
        else:
            self.client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and self.client is not None

    async def _call_api(self, system_prompt: str, messages: list[dict]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        # 手动重试：超时/连接错误时重试 2 次，间隔 2 秒
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                logger.info(f"[DeepSeek] 调用 attempt={attempt + 1}/3, 消息数={len(full_messages)}")
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    max_tokens=2048,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                logger.info(f"[DeepSeek] 成功返回 {len(content)} 字符")
                logger.debug(f"[DeepSeek RAW] {content[:600]}")
                return content

            except APITimeoutError as e:
                last_error = e
                logger.warning(f"[DeepSeek] 超时 (尝试 {attempt + 1}/3): {e}")
            except APIConnectionError as e:
                last_error = e
                logger.warning(f"[DeepSeek] 连接错误 (尝试 {attempt + 1}/3): {e}")
            except RateLimitError as e:
                last_error = e
                logger.warning(f"[DeepSeek] 限流 (尝试 {attempt + 1}/3): {e}")
            except Exception as e:
                # 其他错误不重试
                logger.exception(f"[DeepSeek] 非超时错误，不重试: {e}")
                raise

            # 重试前等一下
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

        # 三次都失败
        raise last_error or RuntimeError("DeepSeek 调用失败")
