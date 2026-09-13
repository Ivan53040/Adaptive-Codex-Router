"""Configurable model availability and explicit Astra fallback."""

from __future__ import annotations

from ..config import AppConfig
from .schemas import ModelName, ModelRoute, ReasoningEffort


class ModelUnavailableError(RuntimeError):
    pass


class ConfiguredAvailability:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def is_available(self, model: ModelName) -> bool:
        return self._config.model(model).available

    def resolve(self, route: ModelRoute) -> ModelRoute:
        if self.is_available(route.model):
            return route
        if route.model is ModelName.ASTRA:
            sol = self._config.model(ModelName.SOL)
            if not sol.available:
                raise ModelUnavailableError("Astra and its Sol fallback are unavailable")
            return ModelRoute(
                model=ModelName.SOL,
                model_id=sol.model_id,
                effort=ReasoningEffort.HIGH,
                reasons=route.reasons + ("Astra unavailable; fell back to Sol High",),
                is_escalation=route.is_escalation,
                fallback_from=ModelName.ASTRA,
            )
        raise ModelUnavailableError(f"{route.model.value} is unavailable")

    def available_models(self) -> tuple[ModelName, ...]:
        return tuple(model for model in ModelName if self.is_available(model))
