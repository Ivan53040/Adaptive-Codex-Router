"""Planning provider contract and provider-level failures."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..router.schemas import (
    PlanningDiagnostics,
    PlanningResult,
    ProviderStatus,
    TaskMetadata,
)


class PlannerError(RuntimeError):
    """Base error for an unavailable or invalid planning provider."""


class PlannerUnavailableError(PlannerError):
    pass


class PlannerOutputError(PlannerError):
    pass


class PlanningProvider(Protocol):
    name: str
    last_diagnostics: PlanningDiagnostics | None

    def status(self) -> ProviderStatus: ...

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult: ...
