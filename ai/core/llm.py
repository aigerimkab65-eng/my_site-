from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from ai.core.registry import ToolRegistry

MAX_TOOL_ROUNDS = 3
REQUEST_TIMEOUT = 20


def _load_dotenv():
    """Best-effort .env load so OPENAI_* works even if server.load_env was not called."""
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env_path = os.path.join(root, ".env")
        if not os.path.isfile(env_path):
            return
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:
        return


def _api_config():
    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return api_key, model, base


def _post_chat(base: str, api_key: str, payload: dict) -> dict | None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _assistant_tool_message(message: dict) -> dict:
    """Normalize assistant+tool_calls payload for OpenAI-compatible APIs."""
    content = message.get("content")
    if content is None:
        content = ""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": message.get("tool_calls") or [],
    }


def chat_with_tools(
    system_prompt: str,
    api_messages: list[dict],
    tool_registry: ToolRegistry,
    tool_names: list[str],
    context: dict,
    temperature: float = 0.45,
    max_tokens: int = 520,
) -> tuple[str | None, tuple[str, ...]]:
    """Call OpenAI-compatible chat with optional tool loop. Returns (reply, tool_names_used)."""
    cfg = _api_config()
    if not cfg:
        return None, ()
    api_key, model, base = cfg

    messages: list[dict] = [{"role": "system", "content": system_prompt}] + list(api_messages)
    tools = tool_registry.schemas_for_openai(tool_names)
    used: list[str] = []
    tool_rounds = 0

    while True:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        allow_tools = bool(tools) and tool_rounds < MAX_TOOL_ROUNDS
        if tools:
            payload["tools"] = tools
            # After tool budget is spent, force a text answer.
            payload["tool_choice"] = "auto" if allow_tools else "none"

        data = _post_chat(base, api_key, payload)
        if not data:
            return None, tuple(used)

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, AttributeError):
            return None, tuple(used)

        tool_calls = message.get("tool_calls") or []
        if tool_calls and allow_tools:
            tool_rounds += 1
            messages.append(_assistant_tool_message(message))
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                name = str(fn.get("name") or "").strip()
                call_id = str(call.get("id") or "")
                args = _parse_args(fn.get("arguments"))
                if name:
                    used.append(name)
                result = tool_registry.execute(name, args, context)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result,
                    }
                )
            continue

        content = (message.get("content") or "").strip()
        if not content:
            return None, tuple(used)
        return content[:2500], tuple(used)
