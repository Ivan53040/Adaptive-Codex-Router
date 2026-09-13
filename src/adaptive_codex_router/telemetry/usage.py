"""Mock-only relative usage estimator; it is not Codex billing data."""

from __future__ import annotations

from ..router.schemas import ModelName, ModelRoute, ReasoningEffort

MODEL_WEIGHTS = {
    ModelName.LUNA: 0.35,
    ModelName.TERRA: 0.65,
    ModelName.SOL: 1.0,
    ModelName.ASTRA: 1.2,
}

EFFORT_WEIGHTS = {
    ReasoningEffort.LOW: 0.75,
    ReasoningEffort.MEDIUM: 1.0,
    ReasoningEffort.HIGH: 1.35,
    ReasoningEffort.XHIGH: 1.8,
    ReasoningEffort.MAX: 2.5,
}


def estimate_mock_usage(route: ModelRoute, input_tokens: int, output_tokens: int) -> float:
    """Give tests useful relative numbers without claiming real Plus usage."""
    tokens = input_tokens + output_tokens
    return round(tokens * MODEL_WEIGHTS[route.model] * EFFORT_WEIGHTS[route.effort], 3)

