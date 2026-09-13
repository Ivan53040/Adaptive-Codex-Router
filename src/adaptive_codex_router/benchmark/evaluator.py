"""Evaluate Phase 2 classification and initial routing without executing tasks."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import AppConfig
from ..router.classifier import MockLunaClassifier, TaskClassifier
from ..router.codex_classifier import ClassifierError, LunaCodexClassifier
from ..router.policy import RoutingPolicy
from ..router.schemas import (
    ClassifierDiagnostics,
    ModelName,
    TaskClassification,
    TaskMetadata,
    TaskType,
)


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    prompt: str
    expected_task_type: TaskType
    expected_model: ModelName
    metadata: TaskMetadata


@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    completed: int
    task_type_correct: int
    route_correct: int
    under_routed: int
    over_routed: int
    errors: int

    @property
    def task_type_accuracy(self) -> float:
        return self.task_type_correct / self.completed if self.completed else 0.0

    @property
    def route_accuracy(self) -> float:
        return self.route_correct / self.completed if self.completed else 0.0

    def to_dict(self) -> dict[str, int | float]:
        return {
            "total": self.total,
            "completed": self.completed,
            "task_type_correct": self.task_type_correct,
            "task_type_accuracy": self.task_type_accuracy,
            "route_correct": self.route_correct,
            "route_accuracy": self.route_accuracy,
            "under_routed": self.under_routed,
            "over_routed": self.over_routed,
            "errors": self.errors,
        }


_MODEL_TIER = {
    ModelName.LUNA: 0,
    ModelName.TERRA: 1,
    ModelName.SOL: 2,
    ModelName.ASTRA: 3,
}


class _PreclassifiedBatch:
    def __init__(
        self,
        values: Sequence[TaskClassification],
        diagnostics: ClassifierDiagnostics | None,
    ) -> None:
        self._values = iter(values)
        self.last_diagnostics = diagnostics
        self.usage_scope = "batch"

    def classify(
        self,
        prompt: str,
        metadata: TaskMetadata | None = None,
    ) -> TaskClassification:
        return next(self._values)


def load_cases(path: str | Path) -> list[EvaluationCase]:
    dataset_path = Path(path)
    cases: list[EvaluationCase] = []
    names: set[str] = set()
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError("row must be a JSON object")
            name = str(value["name"])
            if not name or name in names:
                raise ValueError(f"case name must be non-empty and unique: {name!r}")
            metadata_value = value.get("metadata", {})
            if not isinstance(metadata_value, dict):
                raise ValueError("metadata must be a JSON object")
            unknown_metadata = set(metadata_value) - set(TaskMetadata.__dataclass_fields__)
            if unknown_metadata:
                raise ValueError(
                    "unsupported metadata fields: " + ", ".join(sorted(unknown_metadata))
                )
            cases.append(
                EvaluationCase(
                    name=name,
                    prompt=str(value["prompt"]),
                    expected_task_type=TaskType(value["expected_task_type"]),
                    expected_model=ModelName(value["expected_model"]),
                    metadata=TaskMetadata(**metadata_value),
                )
            )
            names.add(name)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid dataset row {line_number}: {exc}") from exc
    if not cases:
        raise ValueError(f"evaluation dataset is empty: {dataset_path}")
    return cases


def evaluate_cases(
    cases: Sequence[EvaluationCase],
    classifier: TaskClassifier,
    policy: RoutingPolicy,
    *,
    stop_on_error: bool = False,
) -> tuple[EvaluationSummary, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    type_correct = route_correct = under_routed = over_routed = errors = 0

    for case in cases:
        try:
            classification = classifier.classify(case.prompt, case.metadata)
            route = policy.select_initial(classification)
            type_match = classification.task_type is case.expected_task_type
            route_match = route.model is case.expected_model
            type_correct += int(type_match)
            route_correct += int(route_match)
            if not route_match:
                if _MODEL_TIER[route.model] < _MODEL_TIER[case.expected_model]:
                    under_routed += 1
                else:
                    over_routed += 1
            diagnostics = classifier.last_diagnostics
            records.append(
                {
                    "name": case.name,
                    "expected_task_type": case.expected_task_type.value,
                    "actual_task_type": classification.task_type.value,
                    "task_type_match": type_match,
                    "expected_model": case.expected_model.value,
                    "actual_model": route.model.value,
                    "actual_effort": route.effort.value,
                    "route_match": route_match,
                    "classification": classification.to_dict(),
                    "classifier": diagnostics.to_dict() if diagnostics else None,
                    "classifier_usage_scope": getattr(classifier, "usage_scope", "case"),
                }
            )
        except (ClassifierError, OSError, ValueError) as exc:
            errors += 1
            records.append(
                {
                    "name": case.name,
                    "expected_task_type": case.expected_task_type.value,
                    "expected_model": case.expected_model.value,
                    "error": str(exc),
                }
            )
            if stop_on_error:
                break

    completed = len(records) - errors
    return (
        EvaluationSummary(
            total=len(cases),
            completed=completed,
            task_type_correct=type_correct,
            route_correct=route_correct,
            under_routed=under_routed,
            over_routed=over_routed,
            errors=errors,
        ),
        records,
    )


def _write_results(path: Path, summary: EvaluationSummary, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps({"summary": summary.to_dict()}, separators=(",", ":"))]
    rows.extend(json.dumps(record, separators=(",", ":")) for record in records)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-codex-eval",
        description="Evaluate classification and routing only; coding tasks are never executed.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dataset", default="benchmarks/phase2_tasks.jsonl")
    parser.add_argument("--output", default="data/phase2_eval_results.jsonl")
    parser.add_argument("--classifier", choices=["codex", "mock"], default="codex")
    volume = parser.add_mutually_exclusive_group()
    volume.add_argument("--limit", type=int, help="Run only the first N cases")
    volume.add_argument(
        "--full",
        action="store_true",
        help="Explicitly authorize all cases as sequential calls (40 in the default dataset)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Classify all selected cases in one Luna call (real classifier only)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be at least 1")
        if args.batch and args.classifier != "codex":
            raise ValueError("--batch is available only with --classifier codex")
        if (
            args.classifier == "codex"
            and args.limit is None
            and not args.full
            and not args.batch
        ):
            raise ValueError(
                "real evaluation requires --limit N or explicit --full to prevent accidental usage"
            )
        config = AppConfig.load(args.config).with_classifier_mode(args.classifier)
        cases = load_cases(args.dataset)
        if args.limit:
            cases = cases[: args.limit]
        if args.batch:
            batch_classifier = LunaCodexClassifier(config)
            classifications = batch_classifier.classify_many(
                [(case.name, case.prompt, case.metadata) for case in cases]
            )
            classifier: TaskClassifier = _PreclassifiedBatch(
                classifications,
                batch_classifier.last_diagnostics,
            )
        else:
            classifier = (
                LunaCodexClassifier(config)
                if args.classifier == "codex"
                else MockLunaClassifier()
            )
        summary, records = evaluate_cases(
            cases,
            classifier,
            RoutingPolicy(config),
            stop_on_error=args.classifier == "codex",
        )
        output_path = Path(args.output)
        _write_results(output_path, summary, records)
    except (ClassifierError, OSError, ValueError) as exc:
        print(f"Evaluation blocked: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary.to_dict(), indent=2))
    print(f"Results: {output_path.resolve()}")
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
