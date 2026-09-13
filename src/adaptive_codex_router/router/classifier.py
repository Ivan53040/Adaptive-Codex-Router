"""A deterministic stand-in for the future tiny Luna classification call."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Protocol

from .schemas import (
    Complexity,
    ClassifierDiagnostics,
    ContextRequirement,
    ExpectedTaskLength,
    ModelName,
    ReasoningEffort,
    Scope,
    TaskClassification,
    TaskMetadata,
    TaskType,
)


class TaskClassifier(Protocol):
    last_diagnostics: ClassifierDiagnostics | None

    def classify(
        self,
        prompt: str,
        metadata: TaskMetadata | None = None,
    ) -> TaskClassification: ...


class MockLunaClassifier:
    """Extract semantic task features without calling a model.

    The keyword rules are intentionally small and replaceable. They prove the
    classifier contract and routing flow; they are not presented as a learned
    or production-quality classifier.
    """

    _TASK_PATTERNS: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
        (TaskType.MIGRATION, ("migrate", "migration", "upgrade framework")),
        (TaskType.SECURITY, ("security", "vulnerability", "exploit", "cve")),
        (TaskType.PERFORMANCE, ("performance", "optimise", "optimize", "latency")),
        (TaskType.ARCHITECTURE, ("architecture", "architect", "system design")),
        (TaskType.REFACTOR, ("refactor", "restructure", "redesign")),
        (
            TaskType.DEBUGGING,
            ("debug", "bug", "fix error", "race condition", "deadlock", "failing"),
        ),
        (
            TaskType.REPOSITORY_ANALYSIS,
            ("analyse repository", "analyze repository", "audit repository", "review repo"),
        ),
        (TaskType.DOCUMENTATION, ("documentation", "readme", "docs", "document")),
        (TaskType.TEST_GENERATION, ("write tests", "add tests", "test generation", "unit test")),
        (
            TaskType.SIMPLE_EDIT,
            ("typo", "rename", "formatting", "format ", "change text", "one-line"),
        ),
        (
            TaskType.IMPLEMENTATION,
            ("implement", "build", "create", "add feature", "integrate"),
        ),
    )

    def __init__(self) -> None:
        self.last_diagnostics: ClassifierDiagnostics | None = None

    def classify(
        self,
        prompt: str,
        metadata: TaskMetadata | None = None,
    ) -> TaskClassification:
        started = perf_counter()
        metadata = metadata or TaskMetadata()
        text = " ".join(prompt.lower().split())
        task_type = self._task_type(text)
        scope = self._scope(text, task_type, metadata)
        reasoning = self._reasoning_complexity(text, task_type, scope)
        agentic = self._agentic_complexity(scope, reasoning, metadata)
        context = self._context_requirement(text, scope, reasoning)

        risk = Complexity.LOW
        if task_type in {TaskType.SECURITY, TaskType.MIGRATION}:
            risk = Complexity.VERY_HIGH
        elif task_type in {
            TaskType.DEBUGGING,
            TaskType.ARCHITECTURE,
            TaskType.PERFORMANCE,
            TaskType.REFACTOR,
        }:
            risk = Complexity.HIGH
        elif task_type in {TaskType.IMPLEMENTATION, TaskType.TEST_GENERATION}:
            risk = Complexity.MEDIUM

        verification = Complexity.LOW
        if task_type in {TaskType.DEBUGGING, TaskType.SECURITY, TaskType.PERFORMANCE}:
            verification = Complexity.HIGH
        elif task_type in {
            TaskType.IMPLEMENTATION,
            TaskType.REFACTOR,
            TaskType.MIGRATION,
            TaskType.TEST_GENERATION,
        }:
            verification = Complexity.MEDIUM

        ambiguity = (
            Complexity.HIGH
            if task_type is TaskType.UNKNOWN
            else Complexity.LOW
            if any(word in text for word in ("exactly", "only", "specific", "one-line"))
            else Complexity.MEDIUM
        )

        expected_length = ExpectedTaskLength.SHORT
        if agentic is Complexity.VERY_HIGH:
            expected_length = ExpectedTaskLength.VERY_LONG
        elif agentic is Complexity.HIGH or scope is Scope.REPOSITORY:
            expected_length = ExpectedTaskLength.LONG
        elif reasoning in {Complexity.MEDIUM, Complexity.HIGH}:
            expected_length = ExpectedTaskLength.MEDIUM

        result = TaskClassification(
            task_type=task_type,
            scope=scope,
            reasoning_complexity=reasoning,
            agentic_complexity=agentic,
            ambiguity=ambiguity,
            risk=risk,
            verification_difficulty=verification,
            context_requirement=context,
            expected_task_length=expected_length,
            confidence=0.96 if task_type is not TaskType.UNKNOWN else 0.62,
            number_of_expected_steps=max(1, metadata.number_of_expected_steps),
            cross_module_dependency=metadata.cross_module_dependency,
        )
        self.last_diagnostics = ClassifierDiagnostics(
            source="mock",
            model_id="mock-luna",
            effort=ReasoningEffort.LOW,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=1,
        )
        return result

    def _task_type(self, text: str) -> TaskType:
        for task_type, patterns in self._TASK_PATTERNS:
            if any(pattern in text for pattern in patterns):
                return task_type
        return TaskType.UNKNOWN

    def _scope(self, text: str, task_type: TaskType, metadata: TaskMetadata) -> Scope:
        if "multiple repositories" in text or "multi-repository" in text:
            return Scope.MULTI_REPOSITORY
        if metadata.repository_wide or any(
            phrase in text
            for phrase in ("repository-wide", "entire repository", "whole repository", "whole repo")
        ):
            return Scope.REPOSITORY
        if metadata.files_explicitly_mentioned > 1 or metadata.cross_module_dependency:
            return Scope.MULTI_FILE
        if any(
            phrase in text
            for phrase in ("multi-file", "multiple files", "multiple modules", "cross-module", "across modules")
        ):
            return Scope.MULTI_FILE
        if "single line" in text or "one-line" in text:
            return Scope.SINGLE_LINE
        if metadata.files_explicitly_mentioned == 1 or re.search(
            r"\b[\w./\\-]+\.(?:py|js|ts|tsx|jsx|rs|go|java|md|toml|ya?ml|json)\b",
            text,
        ):
            return Scope.SINGLE_FILE
        if task_type in {TaskType.SIMPLE_EDIT, TaskType.DOCUMENTATION}:
            return Scope.SINGLE_FILE
        return Scope.UNKNOWN

    def _reasoning_complexity(
        self,
        text: str,
        task_type: TaskType,
        scope: Scope,
    ) -> Complexity:
        if (
            task_type is TaskType.IMPLEMENTATION
            and scope in {Scope.SINGLE_LINE, Scope.SINGLE_FILE}
            and any(word in text for word in ("small", "bounded", "tiny", "simple"))
        ):
            return Complexity.LOW
        if any(
            phrase in text
            for phrase in (
                "extremely difficult",
                "very difficult",
                "distributed system",
                "multiple systems",
                "persistent concurrency",
            )
        ) or (task_type is TaskType.MIGRATION and scope in {Scope.REPOSITORY, Scope.MULTI_REPOSITORY}):
            return Complexity.VERY_HIGH
        if task_type in {
            TaskType.ARCHITECTURE,
            TaskType.MIGRATION,
            TaskType.SECURITY,
            TaskType.REFACTOR,
        } or any(
            phrase in text
            for phrase in ("race condition", "deadlock", "concurrent", "cross-module", "complex")
        ):
            return Complexity.HIGH
        if task_type in {TaskType.IMPLEMENTATION, TaskType.DEBUGGING, TaskType.PERFORMANCE}:
            return Complexity.MEDIUM
        return Complexity.LOW

    def _agentic_complexity(
        self,
        scope: Scope,
        reasoning: Complexity,
        metadata: TaskMetadata,
    ) -> Complexity:
        if metadata.number_of_expected_steps >= 8 or (
            scope in {Scope.REPOSITORY, Scope.MULTI_REPOSITORY}
            and reasoning is Complexity.VERY_HIGH
        ):
            return Complexity.VERY_HIGH
        if (
            metadata.number_of_expected_steps >= 5
            or scope in {Scope.REPOSITORY, Scope.MULTI_REPOSITORY}
            or metadata.cross_module_dependency
        ):
            return Complexity.HIGH
        if scope is Scope.MULTI_FILE or metadata.number_of_expected_steps >= 3:
            return Complexity.MEDIUM
        return Complexity.LOW

    def _context_requirement(
        self,
        text: str,
        scope: Scope,
        reasoning: Complexity,
    ) -> ContextRequirement:
        if "very large context" in text or scope is Scope.MULTI_REPOSITORY or (
            scope is Scope.REPOSITORY and reasoning is Complexity.VERY_HIGH
        ):
            return ContextRequirement.VERY_LARGE
        if scope is Scope.REPOSITORY or (
            scope is Scope.MULTI_FILE and reasoning in {Complexity.HIGH, Complexity.VERY_HIGH}
        ):
            return ContextRequirement.LARGE
        if scope is Scope.MULTI_FILE:
            return ContextRequirement.MEDIUM
        return ContextRequirement.SMALL


# Kept here as a convenience import while the implementation stays isolated.
from .codex_classifier import LunaCodexClassifier  # noqa: E402

__all__ = ["LunaCodexClassifier", "MockLunaClassifier", "TaskClassifier"]
