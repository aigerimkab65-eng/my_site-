from __future__ import annotations

from typing import Any

from ai.core.llm import chat_with_tools
from ai.core.registry import FeatureRegistry, ToolRegistry
from ai.core.types import RunResult


class Engine:
    def __init__(
        self,
        features: FeatureRegistry,
        tools: ToolRegistry,
        default_context: dict | None = None,
    ):
        self.features = features
        self.tools = tools
        self.default_context = dict(default_context or {})

    def run(
        self,
        feature_id: str,
        messages: list[dict],
        lang: str = "ru",
        attachments: list[dict] | None = None,
        context: dict | None = None,
        build_api_messages=None,
    ) -> RunResult:
        feature = self.features.get(feature_id)
        if feature is None:
            raise ValueError(f"Unknown AI feature: {feature_id}")

        attachments = attachments or []
        merged: dict[str, Any] = {**self.default_context, **(context or {})}
        merged["lang"] = lang if lang in {"ru", "kz", "en"} else "ru"

        api_messages = None
        if build_api_messages is not None:
            api_messages, _names = build_api_messages(messages, attachments)
        else:
            api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        try:
            reply, used = chat_with_tools(
                system_prompt=feature.system_prompt,
                api_messages=api_messages,
                tool_registry=self.tools,
                tool_names=list(feature.tool_names or []),
                context=merged,
                temperature=feature.temperature,
                max_tokens=feature.max_tokens,
            )
        except Exception:
            reply, used = None, ()

        if reply:
            return RunResult(reply=reply, mode="openai", tool_calls_used=used)

        if feature.local_fallback is None:
            return RunResult(
                reply="Сервис временно недоступен. Попробуйте позже.",
                mode="local",
                tool_calls_used=used,
            )

        try:
            local_reply = feature.local_fallback(messages, merged["lang"], attachments)
        except Exception:
            local_reply = "Сервис временно недоступен. Попробуйте позже."
        if not (local_reply or "").strip():
            local_reply = "Сервис временно недоступен. Попробуйте позже."
        return RunResult(reply=local_reply, mode="local", tool_calls_used=used)
