"""Routing orchestration with real or mocked Codex components."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from .config import AppConfig
from .executor.codex import CodexExecutor, MockCodexExecutor, TaskExecutor
from .executor.validator import ObjectiveValidator
from .planning import ClassifierPlanningAdapter, PlanningProvider, build_planning_core
from .router.availability import ConfiguredAvailability
from .router.classifier import TaskClassifier
from .router.policy import GuardrailError, RoutingPolicy
from .router.schemas import (
    AttemptRecord,
    FailureType,
    ModelName,
    PlanningResult,
    ReasoningEffort,
    RunResult,
    TaskMetadata,
    ValidationSpec,
)
from .telemetry.logger import TelemetryLogger

ProgressCallback = Callable[[str], None]


class AdaptiveCodexRouter:
    def __init__(
        self,
        config: AppConfig,
        *,
        classifier: TaskClassifier | None = None,
        planner: PlanningProvider | None = None,
        executor: TaskExecutor | None = None,
        validator: ObjectiveValidator | None = None,
        availability: ConfiguredAvailability | None = None,
        telemetry: TelemetryLogger | None = None,
    ) -> None:
        self.config = config
        if classifier is not None and planner is not None:
            raise ValueError("pass either classifier or planner, not both")
        self.classifier = classifier
        self.planner = (
            planner
            or (ClassifierPlanningAdapter(classifier) if classifier else None)
            or build_planning_core(config)
        )
        self.policy = RoutingPolicy(config)
        self.executor = executor or (
            CodexExecutor(config)
            if config.executor.mode == "codex"
            else MockCodexExecutor()
        )
        self.validator = validator or ObjectiveValidator()
        self.availability = availability or ConfiguredAvailability(config)
        self.telemetry = telemetry or TelemetryLogger(config, self.availability)

    def run(
        self,
        prompt: str,
        *,
        metadata: TaskMetadata | None = None,
        model_override: ModelName | None = None,
        effort_override: ReasoningEffort | None = None,
        allow_max: bool = False,
        high_task_value: bool = False,
        validation_spec: ValidationSpec | None = None,
        working_directory: str | Path = ".",
        on_progress: ProgressCallback | None = None,
    ) -> RunResult:
        target = self.executor.preflight(working_directory)
        planning_result = self.planner.plan(prompt, target, metadata)
        classification = planning_result.classification
        if on_progress:
            on_progress(f"Planner: {planning_result.planner}")
        is_manual = model_override is not None or effort_override is not None
        if is_manual:
            requested_route = self.policy.manual_route(
                planning_result,
                model_override,
                effort_override,
                allow_max=allow_max,
                high_task_value=high_task_value,
            )
        else:
            requested_route = self.policy.select_initial(planning_result)
            self.policy.enforce_guardrails(
                requested_route,
                is_initial=True,
                is_manual=False,
                previous_failures=0,
                allow_max=allow_max,
                high_task_value=high_task_value,
            )

        route = self.availability.resolve(requested_route)
        attempts: list[AttemptRecord] = []
        attempted_routes: set[tuple[ModelName, ReasoningEffort]] = set()
        stop_reason: str | None = None

        while len(attempts) < self.config.max_attempts:
            # The deliberately plain loop keeps each expensive decision visible.
            if route.key in attempted_routes:
                stop_reason = "no untried route remains after availability fallback"
                break
            attempted_routes.add(route.key)
            attempt_number = len(attempts) + 1
            if on_progress:
                on_progress(
                    f"Attempt {attempt_number}: {route.model_id}/{route.effort.value}"
                    + (f" (fallback from {route.fallback_from.value})" if route.fallback_from else "")
                )

            execution = self.executor.execute(
                self._execution_prompt(prompt, planning_result), route, target
            )
            validation = self.validator.validate(execution, validation_spec, target)
            escalation_reason: str | None = None
            next_route = None

            terminal_execution_failure = execution.failure_type in {
                FailureType.CANCELLED,
                FailureType.EXECUTOR,
                FailureType.TIMEOUT,
            }
            if terminal_execution_failure:
                stop_reason = {
                    FailureType.CANCELLED: "execution cancelled",
                    FailureType.EXECUTOR: "executor infrastructure failure",
                    FailureType.TIMEOUT: "execution timed out",
                }[execution.failure_type]
            elif not validation.success and attempt_number < self.config.max_attempts:
                failure_type = execution.failure_type or FailureType.VALIDATION
                try:
                    requested_next = self.policy.escalate(
                        route,
                        planning_result,
                        failure_type,
                        previous_failures=attempt_number,
                        allow_max=allow_max,
                        high_task_value=high_task_value,
                    )
                    next_route = self.availability.resolve(requested_next)
                    escalation_reason = (
                        f"{failure_type.value}: {route.model.value}/{route.effort.value} -> "
                        f"{next_route.model.value}/{next_route.effort.value}"
                    )
                    if on_progress:
                        on_progress(f"Escalation: {escalation_reason}")
                except GuardrailError as exc:
                    stop_reason = f"escalation blocked: {exc}"

            attempts.append(
                AttemptRecord(
                    number=attempt_number,
                    route=route,
                    execution=execution,
                    validation=validation,
                    escalation_reason=escalation_reason,
                )
            )
            if validation.success or next_route is None:
                break
            route = next_route

        if attempts and not attempts[-1].validation.success and stop_reason is None:
            stop_reason = f"maximum attempts reached ({self.config.max_attempts})"
        result = RunResult(
            task_id=uuid4().hex[:12],
            classification=classification,
            attempts=tuple(attempts),
            stop_reason=stop_reason,
            classifier_diagnostics=self.planner.last_diagnostics,
            planning_result=planning_result,
            planner_diagnostics=self.planner.last_diagnostics,
        )
        self.telemetry.log(result, prompt=prompt)
        return result

    @staticmethod
    def _execution_prompt(prompt: str, planning_result: PlanningResult) -> str:
        if planning_result.planner in {"none", "classifier_adapter"}:
            return prompt
        sections = [prompt, "PLANNING HANDOFF (advisory; verify against the workspace):"]
        if planning_result.relevant_files:
            sections.append("Relevant files:\n- " + "\n- ".join(planning_result.relevant_files))
        if planning_result.implementation_plan:
            sections.append("Implementation plan:\n- " + "\n- ".join(planning_result.implementation_plan))
        if planning_result.verification_steps:
            sections.append("Verification:\n- " + "\n- ".join(planning_result.verification_steps))
        if planning_result.risks:
            sections.append("Risks:\n- " + "\n- ".join(planning_result.risks))
        return "\n\n".join(sections)

    def cancel(self) -> bool:
        """Cancel the active executor process, if one exists."""
        return self.executor.cancel()
