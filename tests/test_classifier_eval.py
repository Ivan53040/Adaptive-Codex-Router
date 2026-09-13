from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from tests.support import ROOT, runtime_path, test_config

from adaptive_codex_router.benchmark.evaluator import (
    EvaluationCase,
    evaluate_cases,
    load_cases,
    main,
)
from adaptive_codex_router.router.policy import RoutingPolicy
from adaptive_codex_router.router.schemas import (
    Complexity,
    ContextRequirement,
    ExpectedTaskLength,
    ModelName,
    Scope,
    TaskClassification,
    TaskMetadata,
    TaskType,
)


def classification(task_type: TaskType, scope: Scope, reasoning: Complexity) -> TaskClassification:
    return TaskClassification(
        task_type=task_type,
        scope=scope,
        reasoning_complexity=reasoning,
        agentic_complexity=Complexity.LOW,
        ambiguity=Complexity.LOW,
        risk=Complexity.LOW,
        verification_difficulty=Complexity.LOW,
        context_requirement=ContextRequirement.SMALL,
        expected_task_length=ExpectedTaskLength.SHORT,
        confidence=0.99,
    )


class SequenceClassifier:
    def __init__(self, values: list[TaskClassification]) -> None:
        self.values = iter(values)
        self.last_diagnostics = None

    def classify(self, prompt: str, metadata: TaskMetadata | None = None) -> TaskClassification:
        return next(self.values)


class ClassifierEvaluationTests(unittest.TestCase):
    def test_phase2_dataset_has_40_unique_valid_cases(self) -> None:
        cases = load_cases(ROOT / "benchmarks" / "phase2_tasks.jsonl")
        self.assertEqual(len(cases), 40)
        self.assertEqual(len({case.name for case in cases}), 40)
        self.assertEqual({case.expected_model for case in cases}, set(ModelName))

    def test_summary_distinguishes_under_and_over_routing(self) -> None:
        cases = [
            EvaluationCase("exact", "a", TaskType.SIMPLE_EDIT, ModelName.LUNA, TaskMetadata()),
            EvaluationCase("under", "b", TaskType.IMPLEMENTATION, ModelName.SOL, TaskMetadata()),
            EvaluationCase("over", "c", TaskType.ARCHITECTURE, ModelName.LUNA, TaskMetadata()),
        ]
        classifier = SequenceClassifier(
            [
                classification(TaskType.SIMPLE_EDIT, Scope.SINGLE_FILE, Complexity.LOW),
                classification(TaskType.IMPLEMENTATION, Scope.UNKNOWN, Complexity.MEDIUM),
                classification(TaskType.ARCHITECTURE, Scope.UNKNOWN, Complexity.HIGH),
            ]
        )
        config = test_config(runtime_path())
        summary, records = evaluate_cases(cases, classifier, RoutingPolicy(config))

        self.assertEqual(summary.completed, 3)
        self.assertEqual(summary.task_type_correct, 3)
        self.assertEqual(summary.route_correct, 1)
        self.assertEqual(summary.under_routed, 1)
        self.assertEqual(summary.over_routed, 1)
        self.assertEqual(len(records), 3)

    def test_real_eval_requires_explicit_volume(self) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            exit_code = main(
                [
                    "--classifier",
                    "codex",
                    "--config",
                    str(ROOT / "config.yaml"),
                    "--dataset",
                    str(ROOT / "benchmarks" / "phase2_tasks.jsonl"),
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertIn("requires --limit N or explicit --full", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
