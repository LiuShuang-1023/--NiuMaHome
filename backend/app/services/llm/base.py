"""LLM 客户端抽象基类 + 通用响应解析"""
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from loguru import logger

from app.models import ChatMessage, ChatResponse, ListingReview, ParsedRequirement


class BaseLLMClient(ABC):
    """LLM 客户端基类，所有提供商需实现 _call_api"""

    provider_name: str = "base"

    @abstractmethod
    async def _call_api(
        self,
        system_prompt: str,
        messages: list[dict],
    ) -> str:
        """调用具体厂商 API，返回纯文本响应"""
        ...

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """是否已配置（有 API Key）"""
        ...

    async def chat(
        self,
        messages: list[ChatMessage],
        current_requirement: Optional[ParsedRequirement] = None,
    ) -> ChatResponse:
        """统一的对话入口"""
        from app.services.llm.prompts import SYSTEM_PROMPT, build_messages_payload

        if not self.is_configured:
            return self._mock_response(messages)

        # 限制上下文：只保留最近 6 条 + 第一条用户消息（保住原始需求）
        history_full = [{"role": m.role.value, "content": m.content} for m in messages]
        if len(history_full) > 6:
            # 第一条用户消息 + 最近 5 条
            first_user_idx = next(
                (i for i, m in enumerate(history_full) if m["role"] == "user"), 0
            )
            recent = history_full[-5:]
            head = [history_full[first_user_idx]] if first_user_idx < len(history_full) - 5 else []
            # 确保以 user 开始
            history = head + recent
            if history and history[0]["role"] != "user":
                # 找第一条 user
                for i, m in enumerate(history):
                    if m["role"] == "user":
                        history = history[i:]
                        break
            logger.info(f"上下文压缩: {len(history_full)} → {len(history)} 条")
        else:
            history = history_full

        current_req_dict = current_requirement.model_dump() if current_requirement else None
        payload_messages = build_messages_payload(history, current_req_dict)

        try:
            text = await self._call_api(SYSTEM_PROMPT, payload_messages)
            logger.debug(f"[{self.provider_name}] 响应长度: {len(text)} 字符")
            response = self._parse_response(text)

            # 解析失败时的兜底：保留原 requirement，给用户友好提示
            if not response.reply.strip() or "解析失败" in response.reply:
                logger.warning("解析失败，使用兜底响应")
                last_user = next(
                    (m.content for m in reversed(messages) if m.role.value == "user"),
                    "",
                )
                response = ChatResponse(
                    reply=(
                        "抱歉，我刚才没听清。请用一句话告诉我：\n"
                        "「我想在 [城市] 找 [条件] 的房子」\n"
                        f"（你刚才说的是：{last_user[:50]}）"
                    ),
                    requirement=current_requirement,
                    is_ready=bool(current_requirement and current_requirement.destination.city),
                )
            return response
        except Exception as e:
            logger.exception(f"[{self.provider_name}] 调用失败: {e}")
            err_str = str(e).lower()
            if "timed out" in err_str or "timeout" in err_str:
                hint = (
                    "AI 服务连接超时（已自动重试3次仍失败）。\n"
                    "可能原因：\n"
                    "1. DeepSeek 服务高峰期繁忙，请稍后重试\n"
                    "2. 你的网络访问 api.deepseek.com 不稳定\n"
                    "3. DeepSeek 账号余额不足\n"
                    "你之前的需求已保留，可以直接点「直接搜索（按当前条件）」"
                )
            elif "401" in err_str or "unauthorized" in err_str or "api key" in err_str:
                hint = "DeepSeek API Key 无效或过期，请检查 .env.local"
            elif "402" in err_str or "insufficient" in err_str or "balance" in err_str:
                hint = "DeepSeek 账号余额不足，请到 platform.deepseek.com 充值"
            elif "rate" in err_str or "429" in err_str:
                hint = "DeepSeek 请求过于频繁，请稍后重试"
            else:
                hint = f"AI 服务异常：{str(e)[:150]}"
            return ChatResponse(
                reply=hint,
                requirement=current_requirement,  # 保留之前的需求
                is_ready=bool(current_requirement and current_requirement.destination.city),
            )

    def _parse_response(self, text: str) -> ChatResponse:
        """解析模型返回的 JSON（带多层防御）"""
        original_text = text
        text = text.strip()
        # 去除 markdown 代码块
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # === 第一层 JSON 解析 ===
        data = self._safe_json_loads(text)
        if data is None:
            logger.error(f"⚠️ 完全无法解析 JSON, 原文前300字: {original_text[:300]}")
            return ChatResponse(reply=text, is_ready=False)

        # === 第二层：递归剥离嵌套 JSON ===
        # 有时模型会嵌套很多层 {"reply": "{\"reply\": \"...\"}"}
        data = self._unwrap_nested_json(data)

        # === 第三层：reply 字段防污染 ===
        reply_raw = data.get("reply", "")
        reply_clean = self._extract_natural_reply(reply_raw)

        try:
            req = None
            if data.get("requirement"):
                req = ParsedRequirement(**data["requirement"])
            return ChatResponse(
                reply=reply_clean,
                requirement=req,
                is_ready=data.get("is_ready", False),
                clarifying_questions=data.get("clarifying_questions", []),
            )
        except Exception as e:
            logger.exception(f"响应构造失败: {e}")
            return ChatResponse(
                reply=reply_clean or "解析失败",
                is_ready=False,
            )

    @staticmethod
    def _safe_json_loads(text: str) -> dict | None:
        """安全解析 JSON，失败时尝试提取第一个 JSON 对象"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 提取从第一个 { 到最后一个 } 的内容
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(text[first:last + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _unwrap_nested_json(self, data: dict, depth: int = 0) -> dict:
        """递归剥离嵌套 JSON

        例如:
            {"reply": "{\"reply\": \"实际内容\", \"requirement\": {...}}"}
        会被剥成:
            {"reply": "实际内容", "requirement": {...}}
        """
        if depth > 5:  # 防止无限递归
            return data

        reply_val = data.get("reply", "")
        if not isinstance(reply_val, str):
            return data

        stripped = reply_val.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            inner = self._safe_json_loads(stripped)
            if isinstance(inner, dict) and ("reply" in inner or "requirement" in inner):
                logger.warning(f"⚠️ [深度{depth}] 检测到嵌套 JSON，自动剥离")
                # 合并：内层优先，外层兜底
                merged = {**data, **inner}
                return self._unwrap_nested_json(merged, depth + 1)

        return data

    def _extract_natural_reply(self, reply_raw) -> str:
        """从可能被污染的 reply 字段中提取真正的自然语言部分"""
        if not isinstance(reply_raw, str):
            return str(reply_raw) if reply_raw else ""

        reply = reply_raw.strip()
        if not reply:
            return ""

        # 如果还含 "requirement": 说明仍有污染
        if '"requirement"' in reply or '"is_ready"' in reply:
            # 尝试只提取第一个 reply 字段的字符串值
            match = re.search(
                r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"',
                reply
            )
            if match:
                logger.warning("⚠️ reply 字段含污染，正则提取内层 reply")
                extracted = match.group(1)
                # 处理转义
                extracted = extracted.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
                return extracted
            # 实在提不出来，至少把 JSON 标记去掉一些
            logger.warning("⚠️ reply 含污染但无法提取，原样返回")

        return reply

    def _mock_response(self, messages: list[ChatMessage]) -> ChatResponse:
        last = messages[-1].content if messages else ""
        return ChatResponse(
            reply=(
                f"[Mock 模式 - {self.provider_name} 未配置]\n"
                f"你输入的是：{last[:100]}\n\n"
                "请在 .env.local 中配置对应的 API Key 以启用真实 AI 对话。"
            ),
            requirement=ParsedRequirement(raw_text=last),
            is_ready=False,
            clarifying_questions=[
                "（mock）通勤目的地具体在哪？",
                "（mock）你的预算上限是多少？",
            ],
        )

    # ============================================================
    # v0.2 新增：房源 AI 点评
    # ============================================================
    async def review_listing(
        self,
        listing: dict,
        cost: dict,
        commute: Optional[dict] = None,
        requirement: Optional[dict] = None,
    ) -> ListingReview:
        """对单套房源生成 AI 点评（优缺点 + 评分 + 总结）"""
        from app.services.llm.prompts import (
            LISTING_REVIEW_SYSTEM_PROMPT,
            build_listing_review_user_prompt,
        )

        if not self.is_configured:
            return self._mock_review(listing)

        user_prompt = build_listing_review_user_prompt(listing, cost, commute, requirement)
        messages = [{"role": "user", "content": user_prompt}]

        try:
            text = await self._call_api(LISTING_REVIEW_SYSTEM_PROMPT, messages)
            logger.debug(f"[{self.provider_name}] review 响应: {len(text)} 字符")
            return self._parse_review(text)
        except Exception as e:
            logger.exception(f"[{self.provider_name}] review_listing 失败: {e}")
            err_str = str(e).lower()
            if "timed out" in err_str or "timeout" in err_str:
                summary = "AI 分析超时，请稍后重试"
            elif "401" in err_str or "unauthorized" in err_str:
                summary = "AI Key 无效"
            elif "402" in err_str or "balance" in err_str:
                summary = "AI 账号余额不足"
            else:
                summary = f"AI 分析失败：{str(e)[:80]}"
            return ListingReview(
                score=0.0,
                summary=summary,
                pros=[],
                cons=[],
                tags=["生成失败"],
                generated_at=datetime.now().isoformat(timespec="seconds"),
                model=self.provider_name,
            )

    def _parse_review(self, text: str) -> ListingReview:
        """解析房源点评 JSON"""
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        data = self._safe_json_loads(text)
        if data is None:
            logger.warning(f"⚠️ review JSON 解析失败，原文: {text[:200]}")
            return ListingReview(
                score=0.0,
                summary="AI 返回格式异常，无法解析",
                generated_at=datetime.now().isoformat(timespec="seconds"),
                model=self.provider_name,
            )

        # 容错处理
        score = data.get("score", 0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(10.0, score))  # 钳制 0-10

        def _to_str_list(v) -> list[str]:
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str) and v.strip():
                return [v.strip()]
            return []

        return ListingReview(
            score=round(score, 1),
            summary=str(data.get("summary", "")).strip()[:200],
            pros=_to_str_list(data.get("pros"))[:6],
            cons=_to_str_list(data.get("cons"))[:6],
            tags=_to_str_list(data.get("tags"))[:5],
            generated_at=datetime.now().isoformat(timespec="seconds"),
            model=getattr(self, "model", self.provider_name) or self.provider_name,
        )

    def _mock_review(self, listing: dict) -> ListingReview:
        return ListingReview(
            score=7.0,
            summary=f"[Mock] {listing.get('community') or '该房源'} 信息基本完整，可联系看房",
            pros=["mock 优点1", "mock 优点2"],
            cons=["mock 缺点1"],
            tags=["mock"],
            generated_at=datetime.now().isoformat(timespec="seconds"),
            model=f"mock-{self.provider_name}",
        )
