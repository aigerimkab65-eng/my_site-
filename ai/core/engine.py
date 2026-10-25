from __future__ import annotations

from typing import Any

from ai.core.llm import chat_with_tools
from ai.core.registry import FeatureRegistry, ToolRegistry
from ai.core.types import RunResult
from ai.features.consultant.local import prefer_local_price_reply
from ai.features.consultant.prompt import consultant_system_for, reply_matches_lang

_UNAVAILABLE = {
    "en": "Service is temporarily unavailable. Please try again later.",
    "kz": "Сервис уақытша қолжетімсіз. Кейінірек қайталап көріңіз.",
    "ru": "Сервис временно недоступен. Попробуйте позже.",
}


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
        site_lang = lang if lang in {"ru", "kz", "en"} else "ru"
        merged["lang"] = site_lang
        unavailable = _UNAVAILABLE.get(site_lang, _UNAVAILABLE["ru"])

        # Price-list chips + website questions → local reply with public prices.
        # (OpenAI often skips numbers on vague asks like "хочу сайт".)
        if (
            feature_id == "consultant"
            and feature.local_fallback is not None
            and not attachments
            and messages
        ):
            last_text = str(messages[-1].get("content") or "")
            if prefer_local_price_reply(last_text):
                try:
                    local_hit = feature.local_fallback(messages, site_lang, attachments)
                except Exception:
                    local_hit = None
                if (local_hit or "").strip():
                    return RunResult(reply=local_hit, mode="local", tool_calls_used=())

        api_messages = None
        if build_api_messages is not None:
            api_messages, _names = build_api_messages(messages, attachments)
        else:
            api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        if feature_id == "consultant":
            system_prompt = consultant_system_for(site_lang)
        else:
            system_prompt = feature.system_prompt

        try:
            reply, used = chat_with_tools(
                system_prompt=system_prompt,
                api_messages=api_messages,
                tool_registry=self.tools,
                tool_names=list(feature.tool_names or []),
                context=merged,
                temperature=feature.temperature,
                max_tokens=feature.max_tokens,
            )
        except Exception:
            reply, used = None, ()

        if reply and feature_id == "consultant" and not reply_matches_lang(reply, site_lang):
            # Model drifted to the wrong language — prefer deterministic local reply.
            reply = None

        if reply:
            return RunResult(reply=reply, mode="openai", tool_calls_used=used)

        if feature.local_fallback is None:
            return RunResult(
                reply=unavailable,
                mode="local",
                tool_calls_used=used,
            )

        try:
            local_reply = feature.local_fallback(messages, site_lang, attachments)
        except Exception:
            local_reply = unavailable
        if not (local_reply or "").strip():
            local_reply = unavailable
        return RunResult(reply=local_reply, mode="local", tool_calls_used=used)
