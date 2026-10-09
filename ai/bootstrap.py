from __future__ import annotations

from ai.core.engine import Engine
from ai.core.registry import FeatureRegistry, ToolRegistry
from ai.features.consultant import register_consultant
from ai.tools import register_builtin_tools

_engine: Engine | None = None


def init(*, create_order=None) -> Engine:
    """Build tool/feature registries and the shared Engine. Safe to call once at startup."""
    global _engine
    tools = ToolRegistry()
    features = FeatureRegistry()
    register_builtin_tools(tools, create_order=create_order)
    register_consultant(features)
    _engine = Engine(
        features=features,
        tools=tools,
        default_context={"create_order": create_order},
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("AI engine is not initialized. Call ai.bootstrap.init() first.")
    return _engine
