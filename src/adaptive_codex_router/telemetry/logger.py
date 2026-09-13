"""Append one complete, secret-minimising routing event per task."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..router.availability import ConfiguredAvailability
from ..router.schemas import ModelName, RunResult


class TelemetryLogger:
    def __init__(self, config: AppConfig, availability: ConfiguredAvailability) -> None:
        self.config = config
        self.availability = availability

    def log(self, result: RunResult, *, prompt: str | None = None) -> dict[str, Any]:
        attempts = list(result.attempts)
        first = attempts[0] if attempts else None
        final = attempts[-1] if attempts else None
        planner = result.planner_diagnostics
        execution_input = sum(a.execution.input_tokens or 0 for a in attempts) or None
        execution_cached = sum(a.execution.cached_input_tokens or 0 for a in attempts) or None
        execution_output = sum(a.execution.output_tokens or 0 for a in attempts) or None
        planning_input = planner.input_tokens if planner else None
        planning_cached = planner.cached_input_tokens if planner else None
        planning_output = planner.output_tokens if planner else None
        codex_planning_input = None if planner and planner.local_inference else planning_input
        codex_planning_cached = None if planner and planner.local_inference else planning_cached
        codex_planning_output = None if planner and planner.local_inference else planning_output

        def combined(*values: int | None) -> int | None:
            present = [value for value in values if value is not None]
            return sum(present) if present else None

        event: dict[str, Any] = {
            "task_id": result.task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": result.classification.task_type.value,
            "scope": result.classification.scope.value,
            "planner": result.planning_result.planner if result.planning_result else None,
            "planner_model": planner.model_id if planner else None,
            "planning": planner.to_dict() if planner else None,
            "planning_result": (
                result.planning_result.to_dict() if result.planning_result else None
            ),
            "planning_input_tokens": planning_input,
            "planning_cached_input_tokens": planning_cached,
            "planning_output_tokens": planning_output,
            "planning_fallback_reasons": list(planner.fallback_reasons) if planner else [],
            "classifier_model": planner.model_id if planner else None,
            "classifier_confidence": result.classification.confidence,
            "planning_confidence": result.classification.confidence,
            "classifier": (
                planner.to_dict()
                if planner
                else None
            ),
            "selected_model": first.route.model_id if first else None,
            "selected_effort": first.route.effort.value if first else None,
            "final_model": final.route.model_id if final else None,
            "final_effort": final.route.effort.value if final else None,
            "success": result.success,
            "first_attempt_success": bool(first and first.validation.success),
            "escalated": len(attempts) > 1,
            "attempts": len(attempts),
            "input_tokens": combined(codex_planning_input, execution_input),
            "cached_input_tokens": combined(codex_planning_cached, execution_cached),
            "output_tokens": combined(codex_planning_output, execution_output),
            "total_compute_input_tokens": combined(planning_input, execution_input),
            "total_compute_cached_input_tokens": combined(planning_cached, execution_cached),
            "total_compute_output_tokens": combined(planning_output, execution_output),
            "execution_input_tokens": execution_input,
            "execution_cached_input_tokens": execution_cached,
            "execution_output_tokens": execution_output,
            "reasoning_output_tokens": (
                sum(a.execution.reasoning_output_tokens or 0 for a in attempts) or None
            ),
            "estimated_usage": round(
                sum(a.execution.estimated_usage or 0 for a in attempts), 3
            )
            or None,
            "duration_ms": (
                sum(a.execution.duration_ms for a in attempts)
                + (planner.duration_ms if planner else 0)
            ),
            "timed_out": any(a.execution.timed_out for a in attempts),
            "cancelled": any(a.execution.cancelled for a in attempts),
            "astra_available": self.availability.is_available(ModelName.ASTRA),
            "astra_used": any(a.route.model is ModelName.ASTRA for a in attempts),
            "astra_xhigh_or_max_used": any(
                a.route.model is ModelName.ASTRA and a.route.effort.value in {"xhigh", "max"}
                for a in attempts
            ),
            "route_history": [attempt.to_dict() for attempt in attempts],
            "stop_reason": result.stop_reason,
        }
        if self.config.telemetry.log_prompts and prompt is not None:
            event["prompt"] = prompt

        path = self.config.telemetry.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        return event

    def read_events(self) -> list[dict[str, Any]]:
        path = self.config.telemetry.path
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
