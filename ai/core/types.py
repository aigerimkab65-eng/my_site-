from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, dict], Any]


@dataclass
class FeatureSpec:
    id: str
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)
    temperature: float = 0.45
    max_tokens: int = 520
    local_fallback: Optional[Callable[..., str]] = None


@dataclass(frozen=True)
class RunResult:
    reply: str
    mode: str  # "openai" | "local"
    tool_calls_used: tuple[str, ...] = ()
