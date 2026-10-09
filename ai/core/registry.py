from __future__ import annotations

import json
from typing import Any

from ai.core.types import FeatureSpec, ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec):
        if not spec.name:
            raise ValueError("Tool name required")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def schemas_for_openai(self, names: list[str] | None = None) -> list[dict]:
        selected = (
            [self._tools[n] for n in names if n in self._tools]
            if names is not None
            else list(self._tools.values())
        )
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in selected
        ]

    def execute(self, name: str, args: dict, context: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"ok": False, "error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            result = tool.handler(args or {}, context or {})
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": str(exc) or "Tool failed"},
                ensure_ascii=False,
            )
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return json.dumps({"ok": True, "result": str(result)}, ensure_ascii=False)


class FeatureRegistry:
    def __init__(self):
        self._features: dict[str, FeatureSpec] = {}

    def register(self, feature: FeatureSpec):
        if not feature.id:
            raise ValueError("Feature id required")
        self._features[feature.id] = feature

    def get(self, feature_id: str) -> FeatureSpec | None:
        return self._features.get(feature_id)

    def ids(self) -> list[str]:
        return list(self._features.keys())
