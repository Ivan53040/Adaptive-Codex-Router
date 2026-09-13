"""Planner selection, health-aware fallback, and interface-neutral status data."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..config import AppConfig
from ..router.schemas import (
    PlanningDiagnostics,
    PlanningResult,
    ProviderStatus,
    ReasoningEffort,
    TaskMetadata,
)
from .providers import LunaCodexPlanner, NoPlanningProvider, QwenLocalPlanner
from .types import PlannerError, PlanningProvider


class PlanningCore:
    """The single planner-selection core reused by CLI and future interfaces."""

    MODES = ("qwen", "luna", "auto", "none")

    def __init__(
        self,
        mode: str,
        *,
        qwen: PlanningProvider,
        luna: PlanningProvider,
        none: PlanningProvider | None = None,
    ) -> None:
        if mode not in self.MODES:
            raise ValueError(f"unsupported planner mode: {mode}")
        self.mode = mode
        self.providers = {
            "qwen": qwen,
            "luna": luna,
            "none": none or NoPlanningProvider(),
        }
        self.last_diagnostics: PlanningDiagnostics | None = None

    def status(self) -> ProviderStatus:
        if self.mode == "none":
            return ProviderStatus.ONLINE
        if self.mode in {"qwen", "luna"}:
            return self.providers[self.mode].status()
        statuses = [self.providers[name].status() for name in ("qwen", "luna")]
        if ProviderStatus.ONLINE in statuses:
            return ProviderStatus.ONLINE
        if ProviderStatus.DEGRADED in statuses or ProviderStatus.UNKNOWN in statuses:
            return ProviderStatus.DEGRADED
        return ProviderStatus.OFFLINE

    def provider_statuses(self) -> dict[str, ProviderStatus]:
        return {
            name: provider.status()
            for name, provider in self.providers.items()
        }

    def public_config(self) -> dict[str, object]:
        """Stable, dashboard/MCP-facing selection data without UI logic."""
        return {
            "mode": self.mode,
            "available_modes": list(self.MODES),
            "statuses": {
                name: status.value for name, status in self.provider_statuses().items()
            },
        }

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        order = {
            "auto": ("qwen", "luna", "none"),
            "qwen": ("qwen", "none"),
            "luna": ("luna", "none"),
            "none": ("none",),
        }[self.mode]
        fallback_reasons: list[str] = []
        for name in order:
            provider = self.providers[name]
            status = provider.status()
            if status is ProviderStatus.OFFLINE:
                fallback_reasons.append(f"{name}: provider offline")
                continue
            try:
                result = provider.plan(prompt, workspace, metadata)
            except PlannerError as exc:
                fallback_reasons.append(f"{name}: {exc}")
                continue
            diagnostics = provider.last_diagnostics or PlanningDiagnostics(
                source="deterministic" if name == "none" else "unknown",
                model_id=name,
                effort=_diagnostic_effort(name),
                duration_ms=0,
                attempts=1,
                provider=name,
                status=status,
            )
            self.last_diagnostics = replace(
                diagnostics,
                provider=name,
                fallback_reasons=tuple(fallback_reasons),
            )
            return result

        # NoPlanningProvider is expected to be infallible. Keep a final defensive
        # deterministic attempt so external planner failures never abort the task.
        deterministic = NoPlanningProvider()
        result = deterministic.plan(prompt, workspace, metadata)
        self.last_diagnostics = replace(
            deterministic.last_diagnostics
            or PlanningDiagnostics(
                source="deterministic",
                model_id="none",
                effort=_diagnostic_effort("none"),
                duration_ms=0,
                attempts=1,
                provider="none",
                status=ProviderStatus.ONLINE,
            ),
            fallback_reasons=tuple(fallback_reasons),
        )
        return result


def _diagnostic_effort(name: str) -> ReasoningEffort:
    return ReasoningEffort.HIGH if name == "qwen" else ReasoningEffort.LOW


def build_planning_core(config: AppConfig) -> PlanningCore:
    return PlanningCore(
        config.planning.default_provider,
        qwen=QwenLocalPlanner(config),
        luna=LunaCodexPlanner(config),
    )
