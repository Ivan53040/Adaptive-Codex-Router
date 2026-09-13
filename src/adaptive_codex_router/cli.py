"""Command-line interface for the planner-aware adaptive router."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .app import AdaptiveCodexRouter
from .config import AppConfig
from .executor.codex import CodexExecutor, MockCodexExecutor
from .planning import PlannerError
from .router.availability import ModelUnavailableError
from .router.codex_classifier import ClassifierError
from .router.policy import GuardrailError
from .router.schemas import (
    FailureType,
    ModelName,
    ReasoningEffort,
    TaskMetadata,
    ValidationSpec,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-codex",
        description="Plan, route, and execute a coding task.",
    )
    parser.add_argument("prompt", help="Original coding task prompt")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--classifier",
        choices=["codex", "mock"],
        help="Deprecated compatibility alias: codex=luna, mock=none",
    )
    parser.add_argument(
        "--planner",
        choices=["qwen", "luna", "auto", "none"],
        help="Override the configured planning provider",
    )
    parser.add_argument(
        "--executor",
        choices=["codex", "mock"],
        help="Override the configured executor (Phase 3 defaults to codex)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use the mock executor; classification and routing still run",
    )
    parser.add_argument("--explain", action="store_true", help="Show classification and route facts")
    parser.add_argument("--model", choices=[item.value for item in ModelName])
    parser.add_argument("--effort", choices=[item.value for item in ReasoningEffort])
    parser.add_argument("--allow-max", action="store_true", help="Explicitly permit Astra Max")
    parser.add_argument(
        "--high-value",
        action="store_true",
        help="Mark the task high-value for protected Astra efforts",
    )
    parser.add_argument(
        "--mock-fail",
        action="append",
        default=[],
        choices=[item.value for item in ModelName],
        metavar="MODEL",
        help="Make a model fail so escalation can be exercised; repeatable",
    )
    parser.add_argument(
        "--failure-type",
        default=FailureType.CAPABILITY.value,
        choices=[item.value for item in FailureType],
        help="Failure type reported by models selected with --mock-fail",
    )
    parser.add_argument(
        "--astra-unavailable",
        action="store_true",
        help="Simulate Astra being unavailable and exercise the Sol fallback",
    )
    parser.add_argument(
        "--metadata-json",
        default="{}",
        help="Small classification metadata object; repository contents are never accepted",
    )
    parser.add_argument(
        "--require-changed-files",
        action="store_true",
        help="Treat a run that changes no files as a validation failure",
    )
    parser.add_argument(
        "--required-output",
        help="Treat a run as failed unless the final Codex message contains this text",
    )
    parser.add_argument("--working-directory", default=".")
    return parser


def _metadata(raw: str) -> TaskMetadata:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--metadata-json must contain a JSON object")
    allowed = set(TaskMetadata.__dataclass_fields__)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unsupported metadata fields: {', '.join(sorted(unknown))}")
    return TaskMetadata(**value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = AppConfig.load(Path(args.config))
        if args.planner and args.classifier:
            raise ValueError("--planner conflicts with deprecated --classifier")
        if args.planner:
            config = config.with_planner_mode(args.planner)
        if args.classifier:
            config = config.with_planner_mode(
                "luna" if args.classifier == "codex" else "none"
            )
        if args.executor:
            config = config.with_executor_mode(args.executor)
        if args.dry_run:
            if args.executor == "codex":
                raise ValueError("--dry-run conflicts with --executor codex")
            config = config.with_executor_mode("mock")
        if args.astra_unavailable:
            config = config.with_model_availability(ModelName.ASTRA, False)
        metadata = _metadata(args.metadata_json)
        failed_models = {ModelName(item) for item in args.mock_fail}
        failure_type = FailureType(args.failure_type)
        if failed_models and config.executor.mode != "mock":
            raise ValueError("--mock-fail requires --executor mock or --dry-run")
        executor = (
            CodexExecutor(config)
            if config.executor.mode == "codex"
            else MockCodexExecutor(
                fail_models=failed_models,
                failure_types={model: failure_type for model in failed_models},
            )
        )
        router = AdaptiveCodexRouter(config, executor=executor)
        if config.planning.default_provider == "qwen":
            print(
                "Planner: qwen "
                f"({config.planning.qwen_model}/high via {config.planning.qwen_base_url})"
            )
        elif config.planning.default_provider == "luna":
            print(f"Planner: luna ({config.model(ModelName.LUNA).model_id}/low via Codex CLI)")
        elif config.planning.default_provider == "auto":
            print("Planner: auto (qwen -> luna -> deterministic none)")
        else:
            print("Planner: none (deterministic routing features only)")
        if config.executor.mode == "codex":
            print(
                "Executor: Codex CLI "
                f"({config.executor.sandbox}, approvals={config.executor.approval_policy})"
            )
        else:
            print("Executor: deterministic mock (no files will be changed)")
        result = router.run(
            args.prompt,
            metadata=metadata,
            model_override=ModelName(args.model) if args.model else None,
            effort_override=ReasoningEffort(args.effort) if args.effort else None,
            allow_max=args.allow_max,
            high_task_value=args.high_value,
            validation_spec=ValidationSpec(
                required_output=args.required_output,
                require_changed_files=args.require_changed_files,
            ),
            working_directory=args.working_directory,
            on_progress=lambda message: print(message),
        )
    except (
        ClassifierError,
        PlannerError,
        GuardrailError,
        ModelUnavailableError,
        ValueError,
        OSError,
    ) as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        return 2

    suffix = (
        " (executor mocked; coding task was not executed)"
        if config.executor.mode == "mock"
        else ""
    )
    print(f"Result: {'success' if result.success else 'failed'}{suffix}")
    if result.stop_reason:
        print(f"Stop reason: {result.stop_reason}")
    if result.attempts:
        final_execution = result.attempts[-1].execution
        if final_execution.output:
            print("Executor output:")
            print(final_execution.output)
        if final_execution.changed_files:
            print("Changed files: " + ", ".join(final_execution.changed_files))
    if args.explain:
        print("Planning result:")
        print(json.dumps(result.planning_result.to_dict(), indent=2))
        if result.planner_diagnostics:
            print("Planner diagnostics:")
            print(json.dumps(result.planner_diagnostics.to_dict(), indent=2))
        print("Routes:")
        for attempt in result.attempts:
            print(json.dumps(attempt.route.to_dict(), indent=2))
        print(f"Telemetry: {config.telemetry.path}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
