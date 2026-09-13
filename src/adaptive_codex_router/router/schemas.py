"""Typed contracts shared by classifier, policy, executor, and telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TaskType(StringEnum):
    SIMPLE_EDIT = "simple_edit"
    DOCUMENTATION = "documentation"
    TEST_GENERATION = "test_generation"
    IMPLEMENTATION = "implementation"
    REFACTOR = "refactor"
    DEBUGGING = "debugging"
    ARCHITECTURE = "architecture"
    REPOSITORY_ANALYSIS = "repository_analysis"
    MIGRATION = "migration"
    PERFORMANCE = "performance"
    SECURITY = "security"
    UNKNOWN = "unknown"


class Scope(StringEnum):
    SINGLE_LINE = "single_line"
    SINGLE_FILE = "single_file"
    MULTI_FILE = "multi_file"
    REPOSITORY = "repository"
    MULTI_REPOSITORY = "multi_repository"
    UNKNOWN = "unknown"


class Complexity(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ContextRequirement(StringEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


class ExpectedTaskLength(StringEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    VERY_LONG = "very_long"


class ModelName(StringEnum):
    LUNA = "luna"
    TERRA = "terra"
    SOL = "sol"
    ASTRA = "astra"


class ReasoningEffort(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class FailureType(StringEnum):
    CAPABILITY = "capability"
    REASONING = "reasoning"
    CONTEXT = "context"
    VALIDATION = "validation"
    EXECUTOR = "executor"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ProviderStatus(StringEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskMetadata:
    files_explicitly_mentioned: int = 0
    tests_requested: bool = False
    repository_wide: bool = False
    estimated_repo_size: str = "unknown"
    number_of_expected_steps: int = 1
    cross_module_dependency: bool = False


@dataclass(frozen=True)
class TaskClassification:
    task_type: TaskType
    scope: Scope
    reasoning_complexity: Complexity
    agentic_complexity: Complexity
    ambiguity: Complexity
    risk: Complexity
    verification_difficulty: Complexity
    context_requirement: ContextRequirement
    expected_task_length: ExpectedTaskLength
    confidence: float
    number_of_expected_steps: int = 1
    cross_module_dependency: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskClassification":
        required = {
            "task_type",
            "scope",
            "reasoning_complexity",
            "agentic_complexity",
            "ambiguity",
            "risk",
            "verification_difficulty",
            "context_requirement",
            "expected_task_length",
            "confidence",
            "number_of_expected_steps",
            "cross_module_dependency",
        }
        missing = required - set(value)
        extra = set(value) - required
        if missing:
            raise ValueError(f"classification is missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise ValueError(f"classification has unknown fields: {', '.join(sorted(extra))}")
        confidence = value["confidence"]
        expected_steps = value["number_of_expected_steps"]
        cross_module = value["cross_module_dependency"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("classification confidence must be a number")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("classification confidence must be between 0 and 1")
        if isinstance(expected_steps, bool) or not isinstance(expected_steps, int):
            raise ValueError("number_of_expected_steps must be an integer")
        if not 1 <= expected_steps <= 50:
            raise ValueError("number_of_expected_steps must be between 1 and 50")
        if not isinstance(cross_module, bool):
            raise ValueError("cross_module_dependency must be a boolean")
        return cls(
            task_type=TaskType(value["task_type"]),
            scope=Scope(value["scope"]),
            reasoning_complexity=Complexity(value["reasoning_complexity"]),
            agentic_complexity=Complexity(value["agentic_complexity"]),
            ambiguity=Complexity(value["ambiguity"]),
            risk=Complexity(value["risk"]),
            verification_difficulty=Complexity(value["verification_difficulty"]),
            context_requirement=ContextRequirement(value["context_requirement"]),
            expected_task_length=ExpectedTaskLength(value["expected_task_length"]),
            confidence=float(confidence),
            number_of_expected_steps=expected_steps,
            cross_module_dependency=cross_module,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "scope": self.scope.value,
            "reasoning_complexity": self.reasoning_complexity.value,
            "agentic_complexity": self.agentic_complexity.value,
            "ambiguity": self.ambiguity.value,
            "risk": self.risk.value,
            "verification_difficulty": self.verification_difficulty.value,
            "context_requirement": self.context_requirement.value,
            "expected_task_length": self.expected_task_length.value,
            "confidence": self.confidence,
            "number_of_expected_steps": self.number_of_expected_steps,
            "cross_module_dependency": self.cross_module_dependency,
        }


@dataclass(frozen=True)
class PlanningResult:
    """Provider-neutral task analysis consumed by the routing policy."""

    task_type: TaskType
    scope: Scope
    reasoning_complexity: Complexity
    agentic_complexity: Complexity
    ambiguity: Complexity
    risk: Complexity
    verification_difficulty: Complexity
    context_requirement: ContextRequirement
    expected_task_length: ExpectedTaskLength
    confidence: float
    number_of_expected_steps: int
    cross_module_dependency: bool
    relevant_files: tuple[str, ...] = ()
    implementation_plan: tuple[str, ...] = ()
    verification_steps: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    suggested_execution_tier: ModelName | None = None
    planner: str = "none"

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, planner: str) -> "PlanningResult":
        classification_fields = set(TaskClassification.__dataclass_fields__)
        planning_fields = {
            "relevant_files",
            "implementation_plan",
            "verification_steps",
            "risks",
            "suggested_execution_tier",
        }
        required = classification_fields | planning_fields
        missing = required - set(value)
        extra = set(value) - required
        if missing:
            raise ValueError(f"planning result is missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise ValueError(f"planning result has unknown fields: {', '.join(sorted(extra))}")

        classification = TaskClassification.from_dict(
            {name: value[name] for name in classification_fields}
        )
        lists: dict[str, tuple[str, ...]] = {}
        for name in ("relevant_files", "implementation_plan", "verification_steps", "risks"):
            items = value[name]
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"{name} must be an array of strings")
            lists[name] = tuple(item.strip() for item in items if item.strip())

        suggested = value["suggested_execution_tier"]
        if suggested is not None and not isinstance(suggested, str):
            raise ValueError("suggested_execution_tier must be a string or null")
        return cls(
            **{
                name: getattr(classification, name)
                for name in TaskClassification.__dataclass_fields__
            },
            **lists,
            suggested_execution_tier=ModelName(suggested) if suggested else None,
            planner=planner,
        )

    @classmethod
    def from_classification(
        cls,
        classification: TaskClassification,
        *,
        planner: str,
        relevant_files: tuple[str, ...] = (),
        implementation_plan: tuple[str, ...] = (),
        verification_steps: tuple[str, ...] = (),
        risks: tuple[str, ...] = (),
        suggested_execution_tier: ModelName | None = None,
    ) -> "PlanningResult":
        return cls(
            **{
                name: getattr(classification, name)
                for name in TaskClassification.__dataclass_fields__
            },
            relevant_files=relevant_files,
            implementation_plan=implementation_plan,
            verification_steps=verification_steps,
            risks=risks,
            suggested_execution_tier=suggested_execution_tier,
            planner=planner,
        )

    @property
    def classification(self) -> TaskClassification:
        return TaskClassification(
            **{
                name: getattr(self, name)
                for name in TaskClassification.__dataclass_fields__
            }
        )

    def to_dict(self) -> dict[str, Any]:
        result = self.classification.to_dict()
        result.update(
            {
                "relevant_files": list(self.relevant_files),
                "implementation_plan": list(self.implementation_plan),
                "verification_steps": list(self.verification_steps),
                "risks": list(self.risks),
                "suggested_execution_tier": (
                    self.suggested_execution_tier.value
                    if self.suggested_execution_tier
                    else None
                ),
                "planner": self.planner,
            }
        )
        return result


@dataclass(frozen=True)
class ModelRoute:
    model: ModelName
    model_id: str
    effort: ReasoningEffort
    reasons: tuple[str, ...] = ()
    is_escalation: bool = False
    fallback_from: ModelName | None = None

    @property
    def key(self) -> tuple[ModelName, ReasoningEffort]:
        return self.model, self.effort

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model.value,
            "model_id": self.model_id,
            "effort": self.effort.value,
            "reasons": list(self.reasons),
            "is_escalation": self.is_escalation,
            "fallback_from": self.fallback_from.value if self.fallback_from else None,
        }


@dataclass(frozen=True)
class ClassifierDiagnostics:
    source: str
    model_id: str
    effort: ReasoningEffort
    duration_ms: int
    attempts: int
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    provider: str | None = None
    status: ProviderStatus = ProviderStatus.UNKNOWN
    fallback_reasons: tuple[str, ...] = ()
    local_inference: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "model_id": self.model_id,
            "effort": self.effort.value,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "provider": self.provider,
            "status": self.status.value,
            "fallback_reasons": list(self.fallback_reasons),
            "local_inference": self.local_inference,
        }


PlanningDiagnostics = ClassifierDiagnostics


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    output: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    failure_type: FailureType | None = None
    changed_files: tuple[str, ...] = ()
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    estimated_usage: float | None = None
    timed_out: bool = False
    cancelled: bool = False


@dataclass(frozen=True)
class ValidationSpec:
    required_output: str | None = None
    require_changed_files: bool = False
    command: tuple[str, ...] = ()
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ValidationResult:
    success: bool
    failures: tuple[str, ...] = ()
    command_exit_code: int | None = None
    command_duration_ms: int | None = None
    command_timed_out: bool = False


@dataclass(frozen=True)
class AttemptRecord:
    number: int
    route: ModelRoute
    execution: ExecutionResult
    validation: ValidationResult
    escalation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "route": self.route.to_dict(),
            "execution": {
                "success": self.execution.success,
                "exit_code": self.execution.exit_code,
                "duration_ms": self.execution.duration_ms,
                "failure_type": (
                    self.execution.failure_type.value
                    if self.execution.failure_type
                    else None
                ),
                "error": (
                    " ".join(self.execution.output.strip().split())[-1000:]
                    if not self.execution.success and self.execution.output
                    else None
                ),
                "changed_files": list(self.execution.changed_files),
                "input_tokens": self.execution.input_tokens,
                "cached_input_tokens": self.execution.cached_input_tokens,
                "output_tokens": self.execution.output_tokens,
                "reasoning_output_tokens": self.execution.reasoning_output_tokens,
                "estimated_usage": self.execution.estimated_usage,
                "timed_out": self.execution.timed_out,
                "cancelled": self.execution.cancelled,
            },
            "validation": {
                "success": self.validation.success,
                "failures": list(self.validation.failures),
                "command_exit_code": self.validation.command_exit_code,
                "command_duration_ms": self.validation.command_duration_ms,
                "command_timed_out": self.validation.command_timed_out,
            },
            "escalation_reason": self.escalation_reason,
        }


@dataclass(frozen=True)
class RunResult:
    task_id: str
    classification: TaskClassification
    attempts: tuple[AttemptRecord, ...] = field(default_factory=tuple)
    stop_reason: str | None = None
    classifier_diagnostics: ClassifierDiagnostics | None = None
    planning_result: PlanningResult | None = None
    planner_diagnostics: PlanningDiagnostics | None = None

    @property
    def success(self) -> bool:
        return bool(self.attempts and self.attempts[-1].validation.success)

    @property
    def final_route(self) -> ModelRoute | None:
        return self.attempts[-1].route if self.attempts else None
