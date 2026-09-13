"""Deterministic model-and-effort policy plus guarded escalation."""

from __future__ import annotations

from ..config import AppConfig
from .schemas import (
    Complexity,
    ContextRequirement,
    FailureType,
    ModelName,
    ModelRoute,
    PlanningResult,
    ReasoningEffort,
    Scope,
    TaskClassification,
    TaskType,
)


class GuardrailError(ValueError):
    pass


class RoutingPolicy:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def select_initial(self, task: PlanningResult | TaskClassification) -> ModelRoute:
        if task.context_requirement is ContextRequirement.VERY_LARGE or (
            task.scope in {Scope.REPOSITORY, Scope.MULTI_REPOSITORY}
            and task.reasoning_complexity is Complexity.VERY_HIGH
            and task.agentic_complexity in {Complexity.HIGH, Complexity.VERY_HIGH}
        ) or (
            task.scope in {Scope.REPOSITORY, Scope.MULTI_REPOSITORY}
            and task.context_requirement is ContextRequirement.LARGE
            and task.number_of_expected_steps >= 5
            and task.agentic_complexity in {Complexity.HIGH, Complexity.VERY_HIGH}
        ):
            effort = (
                ReasoningEffort.MEDIUM
                if task.reasoning_complexity is Complexity.VERY_HIGH
                else ReasoningEffort.LOW
            )
            return self._route(
                ModelName.ASTRA,
                effort,
                "very large context or difficult repository-wide agentic task",
            )

        if (
            task.confidence < self.config.reliability_threshold
            and task.task_type is TaskType.UNKNOWN
        ):
            return self._route(
                ModelName.TERRA,
                ReasoningEffort.MEDIUM,
                "classifier confidence below reliability threshold; using balanced route",
            )

        if task.task_type in {
            TaskType.ARCHITECTURE,
            TaskType.MIGRATION,
            TaskType.SECURITY,
            TaskType.REFACTOR,
        } or task.reasoning_complexity in {Complexity.HIGH, Complexity.VERY_HIGH}:
            return self._route(
                ModelName.SOL,
                ReasoningEffort.HIGH,
                "high reasoning complexity or high-risk task type",
            )

        if task.scope is Scope.MULTI_FILE or task.task_type is TaskType.DEBUGGING:
            return self._route(
                ModelName.TERRA,
                ReasoningEffort.HIGH,
                "multi-file scope or moderate debugging",
            )

        if task.task_type in {TaskType.SIMPLE_EDIT, TaskType.DOCUMENTATION}:
            return self._route(
                ModelName.LUNA,
                ReasoningEffort.LOW,
                "bounded low-complexity edit",
            )

        if task.task_type is TaskType.TEST_GENERATION:
            return self._route(
                ModelName.LUNA,
                ReasoningEffort.MEDIUM,
                "bounded test generation",
            )

        if (
            task.task_type is TaskType.IMPLEMENTATION
            and task.scope in {Scope.SINGLE_LINE, Scope.SINGLE_FILE}
            and task.reasoning_complexity is Complexity.LOW
        ):
            return self._route(
                ModelName.LUNA,
                ReasoningEffort.HIGH,
                "small bounded implementation",
            )

        return self._route(
            ModelName.TERRA,
            ReasoningEffort.MEDIUM,
            "normal coding task or uncertain task requiring a balanced route",
        )

    def manual_route(
        self,
        task: PlanningResult | TaskClassification,
        model: ModelName | None,
        effort: ReasoningEffort | None,
        *,
        allow_max: bool,
        high_task_value: bool,
    ) -> ModelRoute:
        automatic = self.select_initial(task)
        selected_model = model or automatic.model
        selected_effort = effort or (
            automatic.effort if selected_model is automatic.model else self._default_effort(selected_model)
        )
        route = self._route(selected_model, selected_effort, "manual override")
        self.enforce_guardrails(
            route,
            is_initial=True,
            is_manual=True,
            previous_failures=0,
            allow_max=allow_max,
            high_task_value=high_task_value,
        )
        return route

    def escalate(
        self,
        current: ModelRoute,
        task: PlanningResult | TaskClassification,
        failure_type: FailureType,
        *,
        previous_failures: int,
        allow_max: bool,
        high_task_value: bool,
    ) -> ModelRoute:
        context_failure = failure_type is FailureType.CONTEXT or task.context_requirement in {
            ContextRequirement.LARGE,
            ContextRequirement.VERY_LARGE,
        }
        reasoning_failure = failure_type is FailureType.REASONING

        if current.model is ModelName.LUNA:
            if context_failure:
                next_route = self._route(ModelName.ASTRA, ReasoningEffort.LOW, "context failure")
            elif reasoning_failure or task.reasoning_complexity in {
                Complexity.HIGH,
                Complexity.VERY_HIGH,
            }:
                next_route = self._route(ModelName.SOL, ReasoningEffort.HIGH, "reasoning failure")
            else:
                effort = (
                    ReasoningEffort.HIGH
                    if task.scope is Scope.MULTI_FILE
                    else ReasoningEffort.MEDIUM
                )
                next_route = self._route(ModelName.TERRA, effort, "Luna capability failure")
        elif current.model is ModelName.TERRA:
            if context_failure and task.agentic_complexity in {
                Complexity.HIGH,
                Complexity.VERY_HIGH,
            }:
                next_route = self._route(ModelName.ASTRA, ReasoningEffort.LOW, "large-context failure")
            else:
                next_route = self._route(ModelName.SOL, ReasoningEffort.HIGH, "Terra capability failure")
        elif current.model is ModelName.SOL:
            next_route = self._route(ModelName.ASTRA, ReasoningEffort.LOW, "Sol capability failure")
        elif current.effort is ReasoningEffort.LOW:
            next_route = self._route(ModelName.ASTRA, ReasoningEffort.MEDIUM, "Astra Low failed")
        elif current.effort is ReasoningEffort.MEDIUM:
            next_route = self._route(ModelName.ASTRA, ReasoningEffort.HIGH, "Astra Medium failed")
        elif current.effort is ReasoningEffort.HIGH:
            next_route = self._route(ModelName.ASTRA, ReasoningEffort.XHIGH, "Astra High failed")
        elif current.effort is ReasoningEffort.XHIGH:
            next_route = self._route(ModelName.ASTRA, ReasoningEffort.MAX, "Astra XHigh failed")
        else:
            raise GuardrailError("Astra Max has no automatic escalation route")

        next_route = ModelRoute(
            model=next_route.model,
            model_id=next_route.model_id,
            effort=next_route.effort,
            reasons=next_route.reasons,
            is_escalation=True,
        )
        self.enforce_guardrails(
            next_route,
            is_initial=False,
            is_manual=False,
            previous_failures=previous_failures,
            allow_max=allow_max,
            high_task_value=high_task_value,
        )
        return next_route

    def enforce_guardrails(
        self,
        route: ModelRoute,
        *,
        is_initial: bool,
        is_manual: bool,
        previous_failures: int,
        allow_max: bool,
        high_task_value: bool,
    ) -> None:
        if route.effort not in self.config.model(route.model).efforts:
            raise GuardrailError(
                f"{route.model.value} does not support {route.effort.value} reasoning"
            )
        if route.effort is ReasoningEffort.XHIGH and is_initial and not is_manual:
            raise GuardrailError("XHigh is escalation-only")
        if route.model is ModelName.ASTRA and route.effort is ReasoningEffort.XHIGH:
            if self.config.astra.xhigh_escalation_only and not route.is_escalation:
                raise GuardrailError("Astra XHigh is escalation-only")
            if not high_task_value:
                raise GuardrailError("Astra XHigh requires a high-value task")
        if route.model is ModelName.ASTRA and route.effort is ReasoningEffort.MAX:
            if is_initial and not is_manual and not self.config.astra.max_automatic:
                raise GuardrailError("Astra Max cannot be selected automatically as an initial route")
            if self.config.astra.max_require_explicit_permission and not allow_max:
                raise GuardrailError("Astra Max requires explicit --allow-max permission")
            if self.config.astra.max_require_high_task_value and not high_task_value:
                raise GuardrailError("Astra Max requires --high-value")
            if (
                not is_manual
                and self.config.astra.max_require_previous_failure
                and previous_failures < 1
            ):
                raise GuardrailError("Astra Max requires a previous failed attempt")

    def _route(
        self,
        model: ModelName,
        effort: ReasoningEffort,
        reason: str,
    ) -> ModelRoute:
        model_config = self.config.model(model)
        if effort not in model_config.efforts:
            raise GuardrailError(f"{model.value} does not support {effort.value} reasoning")
        return ModelRoute(
            model=model,
            model_id=model_config.model_id,
            effort=effort,
            reasons=(reason,),
        )

    @staticmethod
    def _default_effort(model: ModelName) -> ReasoningEffort:
        return {
            ModelName.LUNA: ReasoningEffort.MEDIUM,
            ModelName.TERRA: ReasoningEffort.MEDIUM,
            ModelName.SOL: ReasoningEffort.HIGH,
            ModelName.ASTRA: ReasoningEffort.LOW,
        }[model]
