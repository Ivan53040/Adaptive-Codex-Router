"""Phase 4 fixed-model versus adaptive end-to-end benchmark runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4

from ..app import AdaptiveCodexRouter
from ..config import AppConfig, TelemetryConfig
from ..executor.codex import CodexExecutor, MockCodexExecutor
from ..router.availability import ModelUnavailableError
from ..router.classifier import MockLunaClassifier
from ..router.codex_classifier import ClassifierError
from ..router.schemas import ModelName, ReasoningEffort, TaskMetadata, ValidationSpec


STRATEGY_ROUTES: dict[str, tuple[ModelName, ReasoningEffort] | None] = {
    "luna": (ModelName.LUNA, ReasoningEffort.HIGH),
    "terra": (ModelName.TERRA, ReasoningEffort.HIGH),
    "sol": (ModelName.SOL, ReasoningEffort.HIGH),
    "astra": (ModelName.ASTRA, ReasoningEffort.LOW),
    "adaptive": None,
}
MODEL_TIER = {
    ModelName.LUNA: 0,
    ModelName.TERRA: 1,
    ModelName.SOL: 2,
    ModelName.ASTRA: 3,
}


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    prompt: str
    repository: Path
    base_ref: str
    category: str
    metadata: TaskMetadata
    validation: ValidationSpec
    minimum_model: ModelName | None = None
    high_value: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{field} must be an array of non-empty strings")
    return tuple(value)


def load_tasks(path: str | Path) -> tuple[list[BenchmarkTask], str]:
    dataset_path = Path(path).resolve()
    raw = dataset_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    tasks: list[BenchmarkTask] = []
    task_ids: set[str] = set()

    for line_number, raw_line in enumerate(
        raw.decode("utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError("row must be a JSON object")
            task_id = str(value["id"]).strip()
            prompt = str(value["prompt"]).strip()
            repository_value = str(value["repository"]).strip()
            if not task_id or task_id in task_ids:
                raise ValueError(f"task id must be non-empty and unique: {task_id!r}")
            if not prompt:
                raise ValueError("prompt must not be empty")
            if not repository_value:
                raise ValueError("repository must not be empty")

            repository = Path(repository_value)
            if not repository.is_absolute():
                repository = dataset_path.parent / repository

            metadata_value = value.get("metadata", {})
            if not isinstance(metadata_value, dict):
                raise ValueError("metadata must be a JSON object")
            unknown_metadata = set(metadata_value) - set(TaskMetadata.__dataclass_fields__)
            if unknown_metadata:
                raise ValueError(
                    "unsupported metadata fields: "
                    + ", ".join(sorted(unknown_metadata))
                )

            validation_value = value.get("validation", {})
            if not isinstance(validation_value, dict):
                raise ValueError("validation must be a JSON object")
            unknown_validation = set(validation_value) - {
                "required_output",
                "require_changed_files",
                "command",
                "timeout_seconds",
            }
            if unknown_validation:
                raise ValueError(
                    "unsupported validation fields: "
                    + ", ".join(sorted(unknown_validation))
                )
            command = _string_list(validation_value.get("command"), "validation.command")
            timeout_seconds = float(validation_value.get("timeout_seconds", 120))
            if timeout_seconds <= 0:
                raise ValueError("validation.timeout_seconds must be positive")

            minimum_model_value = value.get("minimum_model")
            provenance = value.get("provenance", {})
            if not isinstance(provenance, dict):
                raise ValueError("provenance must be a JSON object")
            tasks.append(
                BenchmarkTask(
                    task_id=task_id,
                    prompt=prompt,
                    repository=repository.resolve(),
                    base_ref=str(value.get("base_ref", "HEAD")),
                    category=str(value.get("category", "uncategorized")),
                    metadata=TaskMetadata(**metadata_value),
                    validation=ValidationSpec(
                        required_output=validation_value.get("required_output"),
                        require_changed_files=bool(
                            validation_value.get("require_changed_files", True)
                        ),
                        command=command,
                        timeout_seconds=timeout_seconds,
                    ),
                    minimum_model=(
                        ModelName(minimum_model_value)
                        if minimum_model_value is not None
                        else None
                    ),
                    high_value=bool(value.get("high_value", False)),
                    provenance=dict(provenance),
                )
            )
            task_ids.add(task_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Phase 4 dataset row {line_number}: {exc}") from exc

    if not tasks:
        raise ValueError(f"Phase 4 dataset is empty: {dataset_path}")
    return tasks, digest


class FreshGitWorkspace:
    """Create an auditable detached worktree for one task/strategy pair."""

    def __init__(
        self,
        root: str | Path,
        *,
        git_command: str = "git",
        keep: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.git_command = git_command
        self.keep = keep
        self._resolved_refs: dict[tuple[Path, str], str] = {}

    def _git(self, args: Sequence[str], *, cwd: Path | None = None) -> str:
        completed = subprocess.run(
            [self.git_command, *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        if completed.returncode != 0:
            detail = " ".join(completed.stderr.strip().split())[-1000:]
            raise ValueError(
                f"Git command failed ({completed.returncode})"
                + (f": {detail}" if detail else "")
            )
        return completed.stdout.strip()

    def resolve_commit(self, task: BenchmarkTask) -> str:
        key = (task.repository, task.base_ref)
        if key in self._resolved_refs:
            return self._resolved_refs[key]
        if not task.repository.is_dir():
            raise ValueError(f"task repository does not exist: {task.repository}")
        inside = self._git(
            ["-C", str(task.repository), "rev-parse", "--is-inside-work-tree"]
        )
        if inside != "true":
            raise ValueError(f"task repository is not a Git working tree: {task.repository}")
        commit = self._git(
            [
                "-C",
                str(task.repository),
                "rev-parse",
                "--verify",
                f"{task.base_ref}^{{commit}}",
            ]
        )
        self._resolved_refs[key] = commit
        return commit

    @contextmanager
    def materialize(self, task: BenchmarkTask, strategy: str) -> Iterator[Path]:
        commit = self.resolve_commit(task)
        self.root.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in task.task_id
        )[:60]
        target = (self.root / f"{safe_id}-{strategy}-{uuid4().hex[:8]}").resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("generated benchmark workspace escaped its configured root")
        registered = False
        try:
            self._git(
                [
                    "-C",
                    str(task.repository),
                    "worktree",
                    "add",
                    "--quiet",
                    "--detach",
                    str(target),
                    commit,
                ]
            )
            registered = True
            yield target
        finally:
            if not target.is_relative_to(self.root):
                raise ValueError("refusing to remove workspace outside configured root")
            if registered and not self.keep:
                self._git(
                    [
                        "-C",
                        str(task.repository),
                        "worktree",
                        "remove",
                        "--force",
                        str(target),
                    ]
                )
            elif target.exists() and not registered:
                shutil.rmtree(target)


def _sum_optional(values: Sequence[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def validate_baseline(
    task: BenchmarkTask,
    workspace: FreshGitWorkspace,
    *,
    run_command: Any = subprocess.run,
) -> None:
    """Require the objective check to fail before a model attempts the task."""
    with workspace.materialize(task, "baseline-check") as target:
        try:
            completed = run_command(
                list(task.validation.command),
                cwd=str(target),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=task.validation.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"baseline validation timed out for task {task.task_id}"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"baseline validation could not start for task {task.task_id}: {exc}"
            ) from exc
        if completed.returncode == 0:
            raise ValueError(
                f"baseline validation already passes for task {task.task_id}; "
                "the task cannot measure a model improvement"
            )


def result_record(
    *,
    task: BenchmarkTask,
    strategy: str,
    dataset_sha256: str,
    result: Any,
    log_prompt: bool,
    mode: str,
) -> dict[str, Any]:
    attempts = list(result.attempts)
    classifier = result.classifier_diagnostics
    planner = result.planner_diagnostics or classifier
    execution_input = _sum_optional([item.execution.input_tokens for item in attempts])
    execution_cached = _sum_optional(
        [item.execution.cached_input_tokens for item in attempts]
    )
    execution_output = _sum_optional([item.execution.output_tokens for item in attempts])
    planner_is_local = bool(planner and planner.local_inference)
    input_tokens = _sum_optional(
        [planner.input_tokens if planner and not planner_is_local else None, execution_input]
    )
    cached_input_tokens = _sum_optional(
        [planner.cached_input_tokens if planner and not planner_is_local else None, execution_cached]
    )
    output_tokens = _sum_optional(
        [planner.output_tokens if planner and not planner_is_local else None, execution_output]
    )
    reasoning_tokens = _sum_optional(
        [item.execution.reasoning_output_tokens for item in attempts]
    )
    estimated_usage = sum(
        item.execution.estimated_usage or 0.0 for item in attempts
    ) or None
    selected = attempts[0].route if attempts else None
    final = attempts[-1].route if attempts else None
    record: dict[str, Any] = {
        "record_type": "benchmark_run",
        "mode": mode,
        "dataset_sha256": dataset_sha256,
        "task_id": task.task_id,
        "category": task.category,
        "strategy": strategy,
        "base_ref": task.base_ref,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": result.classification.to_dict(),
        "classifier": classifier.to_dict() if classifier else None,
        "planner": planner.to_dict() if planner else None,
        "planning_result": (
            result.planning_result.to_dict() if result.planning_result else None
        ),
        "selected_model": selected.model.value if selected else None,
        "selected_model_id": selected.model_id if selected else None,
        "selected_effort": selected.effort.value if selected else None,
        "final_model": final.model.value if final else None,
        "final_model_id": final.model_id if final else None,
        "final_effort": final.effort.value if final else None,
        "minimum_model": task.minimum_model.value if task.minimum_model else None,
        "success": result.success,
        "first_attempt_success": bool(attempts and attempts[0].validation.success),
        "attempts": len(attempts),
        "escalated": len(attempts) > 1,
        "latency_ms": (
            sum(item.execution.duration_ms for item in attempts)
            + (classifier.duration_ms if classifier else 0)
        ),
        "usage": {
            "source": "codex_jsonl" if mode == "real" else "mock_estimate",
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": (
                max(0, input_tokens - cached_input_tokens)
                if mode == "real"
                and input_tokens is not None
                and cached_input_tokens is not None
                else None
            ),
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_tokens,
            "reported_tokens": (
                input_tokens + output_tokens
                if mode == "real"
                and input_tokens is not None
                and output_tokens is not None
                else None
            ),
            "estimated_usage": estimated_usage,
            "local_planning_input_tokens": (
                planner.input_tokens if planner_is_local else None
            ),
            "local_planning_cached_input_tokens": (
                planner.cached_input_tokens if planner_is_local else None
            ),
            "local_planning_output_tokens": (
                planner.output_tokens if planner_is_local else None
            ),
        },
        "validation": [item.to_dict()["validation"] for item in attempts],
        "route_history": [item.to_dict() for item in attempts],
        "stop_reason": result.stop_reason,
    }
    if log_prompt:
        record["prompt"] = task.prompt
    return record


def summarize_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    for strategy in STRATEGY_ROUTES:
        rows = [row for row in records if row.get("strategy") == strategy]
        if not rows:
            continue
        successes = sum(bool(row.get("success")) for row in rows)
        reported = [row.get("usage", {}).get("reported_tokens") for row in rows]
        uncached = [row.get("usage", {}).get("uncached_input_tokens") for row in rows]
        output = [row.get("usage", {}).get("output_tokens") for row in rows]
        reasoning = [
            row.get("usage", {}).get("reasoning_output_tokens") for row in rows
        ]
        estimated = [row.get("usage", {}).get("estimated_usage") for row in rows]
        complete_reported = all(value is not None for value in reported)
        complete_estimated = all(value is not None for value in estimated)
        total_reported = sum(value for value in reported if value is not None)
        total_estimated = sum(value for value in estimated if value is not None)
        under_routed = over_routed = evaluated_routes = 0
        for row in rows:
            minimum = row.get("minimum_model")
            selected = row.get("selected_model")
            if minimum and selected:
                evaluated_routes += 1
                difference = MODEL_TIER[ModelName(selected)] - MODEL_TIER[ModelName(minimum)]
                under_routed += int(difference < 0)
                over_routed += int(difference > 0)
        average_tokens = total_reported / len(rows) if complete_reported else None
        strategies[strategy] = {
            "tasks": len(rows),
            "successes": successes,
            "success_rate": successes / len(rows),
            "first_attempt_success_rate": sum(
                bool(row.get("first_attempt_success")) for row in rows
            )
            / len(rows),
            "escalation_rate": sum(bool(row.get("escalated")) for row in rows)
            / len(rows),
            "total_attempts": sum(int(row.get("attempts", 0)) for row in rows),
            "average_latency_ms": sum(int(row.get("latency_ms", 0)) for row in rows)
            / len(rows),
            "model_distribution": dict(Counter(row.get("selected_model") for row in rows)),
            "effort_distribution": dict(Counter(row.get("selected_effort") for row in rows)),
            "category_distribution": dict(Counter(row.get("category") for row in rows)),
            "usage": {
                "total_reported_tokens": total_reported if complete_reported else None,
                "total_uncached_input_tokens": sum(
                    value for value in uncached if value is not None
                ) if all(value is not None for value in uncached) else None,
                "total_output_tokens": sum(
                    value for value in output if value is not None
                ) if all(value is not None for value in output) else None,
                "total_reasoning_output_tokens": sum(
                    value for value in reasoning if value is not None
                ) if all(value is not None for value in reasoning) else None,
                "usage_per_success": (
                    total_reported / successes
                    if successes and complete_reported
                    else None
                ),
                "estimated_usage": total_estimated if complete_estimated else None,
                "estimated_usage_per_success": (
                    total_estimated / successes
                    if successes and complete_estimated
                    else None
                ),
                "missing_usage_rows": sum(value is None for value in reported),
            },
            "efficiency": (
                (successes / len(rows)) / average_tokens
                if average_tokens and average_tokens > 0
                else None
            ),
            "route_quality": {
                "evaluated": evaluated_routes,
                "under_routed": under_routed,
                "over_routed": over_routed,
            },
        }

    comparisons: dict[str, Any] = {}
    adaptive = strategies.get("adaptive")
    if adaptive:
        for baseline in ("sol", "astra"):
            other = strategies.get(baseline)
            if not other or other["tasks"] != adaptive["tasks"]:
                continue
            adaptive_tokens = adaptive["usage"]["total_reported_tokens"]
            baseline_tokens = other["usage"]["total_reported_tokens"]
            adaptive_estimated = adaptive["usage"]["estimated_usage"]
            baseline_estimated = other["usage"]["estimated_usage"]
            comparisons[f"adaptive_vs_{baseline}"] = {
                "reported_token_saving_percent": (
                    100 * (baseline_tokens - adaptive_tokens) / baseline_tokens
                    if baseline_tokens and adaptive_tokens is not None
                    else None
                ),
                "estimated_usage_saving_percent": (
                    100 * (baseline_estimated - adaptive_estimated) / baseline_estimated
                    if baseline_estimated and adaptive_estimated is not None
                    else None
                ),
                "success_rate_delta": adaptive["success_rate"] - other["success_rate"],
            }
    return {"strategies": strategies, "comparisons": comparisons}


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid result JSONL line {line_number}: {exc}") from exc
        if value.get("record_type") == "benchmark_run":
            records.append(value)
    return records


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _config_for_strategy(
    config: AppConfig,
    strategy: str,
    mode: str,
    telemetry_path: Path,
) -> AppConfig:
    fixed = STRATEGY_ROUTES[strategy] is not None
    return replace(
        config,
        max_attempts=1 if fixed else config.max_attempts,
        classifier=replace(
            config.classifier,
            mode="mock" if fixed or mode == "mock" else "codex",
        ),
        executor=replace(config.executor, mode="mock" if mode == "mock" else "codex"),
        telemetry=TelemetryConfig(path=telemetry_path, log_prompts=False),
    )


@contextmanager
def _existing_workspace(path: Path) -> Iterator[Path]:
    yield path


def run_benchmark(
    *,
    tasks: Sequence[BenchmarkTask],
    dataset_sha256: str,
    config: AppConfig,
    strategies: Sequence[str],
    mode: str,
    output_path: Path,
    workspace: FreshGitWorkspace | None,
    resume: bool,
    log_prompts: bool,
) -> list[dict[str, Any]]:
    existing = _read_records(output_path)
    if existing and not resume:
        raise ValueError(
            f"result file already exists; choose another --output or use --resume: {output_path}"
        )
    completed = {
        (
            row.get("dataset_sha256"),
            row.get("task_id"),
            row.get("strategy"),
            row.get("mode"),
        )
        for row in existing
    }
    telemetry_path = output_path.with_suffix(".telemetry.jsonl")
    current = [
        row
        for row in existing
        if row.get("dataset_sha256") == dataset_sha256 and row.get("mode") == mode
    ]

    for task in tasks:
        for strategy in strategies:
            key = (dataset_sha256, task.task_id, strategy, mode)
            if key in completed:
                print(f"Skip completed: {task.task_id}/{strategy}")
                continue
            strategy_config = _config_for_strategy(config, strategy, mode, telemetry_path)
            fixed_route = STRATEGY_ROUTES[strategy]
            context = (
                workspace.materialize(task, strategy)
                if mode == "real" and workspace is not None
                else _existing_workspace(task.repository)
            )

            print(f"Run: {task.task_id}/{strategy}")
            with context as working_directory:
                executor = (
                    CodexExecutor(strategy_config)
                    if mode == "real"
                    else MockCodexExecutor()
                )
                router = AdaptiveCodexRouter(
                    strategy_config,
                    classifier=(
                        MockLunaClassifier()
                        if strategy_config.classifier.mode == "mock"
                        else None
                    ),
                    executor=executor,
                )
                validation = task.validation
                if mode == "mock":
                    validation = replace(validation, command=())
                result = router.run(
                    task.prompt,
                    metadata=task.metadata,
                    model_override=fixed_route[0] if fixed_route else None,
                    effort_override=fixed_route[1] if fixed_route else None,
                    high_task_value=task.high_value,
                    validation_spec=validation,
                    working_directory=working_directory,
                )
                record = result_record(
                    task=task,
                    strategy=strategy,
                    dataset_sha256=dataset_sha256,
                    result=result,
                    log_prompt=log_prompts,
                    mode=mode,
                )
                record["base_commit"] = (
                    workspace.resolve_commit(task)
                    if mode == "real" and workspace is not None
                    else None
                )
                _append_record(output_path, record)
                current.append(record)
                completed.add(key)
                print(
                    f"Result: {'success' if result.success else 'failed'}; "
                    f"attempts={len(result.attempts)}"
                )
    return current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-codex-benchmark",
        description="Run Phase 4 fixed-model and adaptive coding benchmarks.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dataset", default="benchmarks/phase4_tasks.example.jsonl")
    parser.add_argument("--output", default="data/phase4_results.jsonl")
    parser.add_argument("--workspace-root", default="data/phase4_workspaces")
    parser.add_argument("--git-command", default="git")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=list(STRATEGY_ROUTES),
        default=list(STRATEGY_ROUTES),
    )
    volume = parser.add_mutually_exclusive_group()
    volume.add_argument("--limit", type=int)
    volume.add_argument("--full", action="store_true")
    parser.add_argument("--allow-real-execution", action="store_true")
    parser.add_argument("--allow-astra-baseline", action="store_true")
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-prompts", action="store_true")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Validate inputs and print planned run counts without executing models",
    )
    return parser


def _validate_run_request(
    args: argparse.Namespace,
    tasks: Sequence[BenchmarkTask],
) -> None:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")
    if len(set(args.strategies)) != len(args.strategies):
        raise ValueError("--strategies must not contain duplicates")
    if args.mode != "real":
        return
    planning_only = bool(getattr(args, "plan", False))
    if not args.allow_real_execution and not planning_only:
        raise ValueError("real benchmark requires explicit --allow-real-execution")
    if args.limit is None and not args.full:
        raise ValueError("real benchmark requires --limit N or explicit --full")
    if args.full and len(tasks) < 100:
        raise ValueError(
            f"full Phase 4 benchmark requires at least 100 real tasks; dataset has {len(tasks)}"
        )
    if (
        "astra" in args.strategies
        and not args.allow_astra_baseline
        and not planning_only
    ):
        raise ValueError("Astra baseline requires explicit --allow-astra-baseline")
    missing_validation = [task.task_id for task in tasks if not task.validation.command]
    if missing_validation:
        raise ValueError(
            "real benchmark tasks require an objective validation.command; missing for: "
            + ", ".join(missing_validation[:10])
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tasks, dataset_sha256 = load_tasks(args.dataset)
        if args.limit is not None:
            tasks = tasks[: args.limit]
        _validate_run_request(args, tasks)
        config = AppConfig.load(args.config)
        planned_runs = len(tasks) * len(args.strategies)
        adaptive_calls = len(tasks) if "adaptive" in args.strategies else 0
        fixed_runs = planned_runs - adaptive_calls
        maximum_executor_runs = fixed_runs + adaptive_calls * config.max_attempts
        print(
            f"Plan: tasks={len(tasks)}, strategies={len(args.strategies)}, "
            f"initial executor runs={planned_runs}, max executor runs={maximum_executor_runs}, "
            f"classifier calls={adaptive_calls}, mode={args.mode}"
        )
        if args.plan:
            return 0

        output_path = Path(args.output).resolve()
        workspace = (
            FreshGitWorkspace(
                args.workspace_root,
                git_command=args.git_command,
                keep=args.keep_workspaces,
            )
            if args.mode == "real"
            else None
        )
        if args.mode == "real" and workspace is not None:
            for task in tasks:
                print(f"Baseline validation: {task.task_id}")
                validate_baseline(task, workspace)
        records = run_benchmark(
            tasks=tasks,
            dataset_sha256=dataset_sha256,
            config=config,
            strategies=args.strategies,
            mode=args.mode,
            output_path=output_path,
            workspace=workspace,
            resume=args.resume,
            log_prompts=args.log_prompts,
        )
        summary = {
            "dataset_sha256": dataset_sha256,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "results": summarize_records(records),
        }
        summary_path = output_path.with_suffix(".summary.json")
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (ClassifierError, ModelUnavailableError, OSError, ValueError) as exc:
        print(f"Benchmark blocked: {exc}", file=sys.stderr)
        return 2

    print(f"Results: {output_path}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
