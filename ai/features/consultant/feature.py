from __future__ import annotations

from ai.core.registry import FeatureRegistry
from ai.core.types import FeatureSpec
from ai.features.consultant.local import consultant_local_fallback
from ai.features.consultant.prompt import CONSULTANT_SYSTEM


def register_consultant(features: FeatureRegistry):
    features.register(
        FeatureSpec(
            id="consultant",
            system_prompt=CONSULTANT_SYSTEM,
            tool_names=["get_service_info", "create_lead"],
            temperature=0.45,
            max_tokens=520,
            local_fallback=consultant_local_fallback,
        )
    )
