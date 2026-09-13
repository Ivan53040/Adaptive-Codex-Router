"""Phase 5 planner and Astra efficiency benchmark matrix."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..app import AdaptiveCodexRouter
from ..config import AppConfig, TelemetryConfig
from ..executor.codex import CodexExecutor, MockCodexExecutor
from ..planning import MockLunaPlanner, MockQwenPlanner, PlanningCore
from ..planning.types import PlannerError
from ..router.availability import ModelUnavailableError
from ..router.schemas import ModelName, ReasoningEffort
from .runner import (
    BenchmarkTask,
    FreshGitWorkspace,
    _append_record,
    _read_records,
    load_tasks,
    result_record,
    validate_baseline,
)
from .swebench import (
    SWEbenchDockerWorkspace,
    SWEbenchHarnessValidator,
    load_swebench_assets,
    validate_swebench_baseline,
    validate_task_assets,
)

PHASE5_CATEGORIES = (
    "simple_coding",
    "normal_implementation",
    "debugging",
    "large_refactor",
    "architecture",
    "repository_analysis",
    "long_agentic",
    "large_context",
)
PLANNER_MODES = ("qwen", "luna", "none")
FIXED_ROUTES = {
    "sol": (ModelName.SOL, ReasoningEffort.HIGH),
    "astra": (ModelName.ASTRA, ReasoningEffort.LOW),
}


@dataclass(frozen=True)
class Phase5Scenario:
    planner: str
    strategy: str

    @property
    def key(self) -> str:
        return f"{self.planner}_{self.strategy}"

    @property
    def label(self) -> str:
        return f"{self.planner}+{self.strategy}"


def build_scenarios(
    planners: Sequence[str],
    *,
    include_planned_sol_controls: bool = False,
    selected_keys: Sequence[str] | None = None,
) -> tuple[Phase5Scenario, ...]:
    if not planners:
        raise ValueError("at least one planner is required")
    if len(set(planners)) != len(planners):
        raise ValueError("planner modes must not contain duplicates")
    unknown = set(planners) - set(PLANNER_MODES)
    if unknown:
        raise ValueError(f"unsupported Phase 5 planner: {', '.join(sorted(unknown))}")

    scenarios = [Phase5Scenario(planner, "adaptive") for planner in planners]
    scenarios.extend(
        [
            Phase5Scenario("none", "sol"),
            Phase5Scenario("none", "astra"),
        ]
    )
    if include_planned_sol_controls:
        scenarios.extend(
            Phase5Scenario(planner, "sol")
            for planner in planners
            if planner != "none"
        )
    scenarios = list(dict.fromkeys(scenarios))
    if selected_keys is not None:
        if not selected_keys or len(set(selected_keys)) != len(selected_keys):
            raise ValueError("selected scenarios must be nonempty and unique")
        unknown = set(selected_keys) - {scenario.key for scenario in scenarios}
        if unknown:
            raise ValueError(
                "scenarios not enabled by the planner/control options: "
                + ", ".join(sorted(unknown))
            )
        scenarios = [scenario for scenario in scenarios if scenario.key in selected_keys]
    return tuple(scenarios)


def _scenario_config(
    config: AppConfig,
    scenario: Phase5Scenario,
    *,
    mode: str,
    telemetry_path: Path,
) -> AppConfig:
    return replace(
        config,
        max_attempts=(1 if scenario.strategy in FIXED_ROUTES else config.max_attempts),
        planning=replace(config.planning, default_provider=scenario.planner),
        executor=replace(config.executor, mode="mock" if mode == "mock" else "codex"),
        telemetry=TelemetryConfig(path=telemetry_path, log_prompts=False),
    )


def _mock_planning_core(mode: str) -> PlanningCore:
    return PlanningCore(
        mode,
        qwen=MockQwenPlanner(),
        luna=MockLunaPlanner(),
    )


@contextmanager
def _existing_workspace(path: Path) -> Iterator[Path]:
    yield path


def run_phase5_benchmark(
    *,
    tasks: Sequence[BenchmarkTask],
    dataset_sha256: str,
    config: AppConfig,
    scenarios: Sequence[Phase5Scenario],
    mode: str,
    output_path: Path,
    workspace: Any | None,
    resume: bool,
    log_prompts: bool,
    validator_factory: Callable[[BenchmarkTask], Any] | None = None,
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
            row.get("scenario"),
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
        for scenario in scenarios:
            key = (dataset_sha256, task.task_id, scenario.key, mode)
            if key in completed:
                print(f"Skip completed: {task.task_id}/{scenario.label}")
                continue
            scenario_config = _scenario_config(
                config,
                scenario,
                mode=mode,
                telemetry_path=telemetry_path,
            )
            target_context = (
                workspace.materialize(task, scenario.key)
                if mode == "real" and workspace is not None
                else _existing_workspace(task.repository)
            )
            print(f"Run: {task.task_id}/{scenario.label}")
            with target_context as working_directory:
                executor = (
                    CodexExecutor(scenario_config)
                    if mode == "real"
                    else MockCodexExecutor()
                )
                planner = (
                    None
                    if mode == "real"
                    else _mock_planning_core(scenario.planner)
                )
                router = AdaptiveCodexRouter(
                    scenario_config,
                    planner=planner,
                    executor=executor,
                    validator=(
                        validator_factory(task)
                        if mode == "real" and validator_factory
                        else None
                    ),
                )
                validation = task.validation
                if mode == "mock":
                    validation = replace(validation, command=())
                fixed_route = FIXED_ROUTES.get(scenario.strategy)
                result = router.run(
                    task.prompt,
                    metadata=task.metadata,
                    model_override=fixed_route[0] if fixed_route else None,
                    effort_override=fixed_route[1] if fixed_route else None,
                    high_task_value=task.high_value,
                    validation_spec=validation,
                    working_directory=working_directory,
                    on_progress=lambda message: print(message, flush=True),
                )
                record = result_record(
                    task=task,
                    strategy=scenario.strategy,
                    dataset_sha256=dataset_sha256,
                    result=result,
                    log_prompt=log_prompts,
                    mode=mode,
                )
                record.update(
                    {
                        "phase": 5,
                        "scenario": scenario.key,
                        "scenario_label": scenario.label,
                        "planner_requested": scenario.planner,
                        "planner_used": (
                            result.planning_result.planner
                            if result.planning_result
                            else None
                        ),
                        "base_commit": (
                            workspace.resolve_commit(task)
                            if mode == "real" and workspace is not None
                            else None
                        ),
                    }
                )
                _append_record(output_path, record)
                current.append(record)
                completed.add(key)
                print(
                    f"Result: {'success' if result.success else 'failed'}; "
                    f"attempts={len(result.attempts)}; planner={record['planner_used']}"
                )
    return current


def _metric_block(rows: Sequence[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    count = len(rows)
    successes = sum(bool(row.get("success")) for row in rows)
    reported = [row.get("usage", {}).get("reported_tokens") for row in rows]
    estimated = [row.get("usage", {}).get("estimated_usage") for row in rows]
    primary = reported if mode == "real" else estimated
    complete_primary = bool(rows) and all(value is not None for value in primary)
    total_primary = sum(float(value) for value in primary if value is not None)
    average_usage = total_primary / count if complete_primary and count else None
    planner_diagnostics = [row.get("planner") or {} for row in rows]
    planning_latencies = [
        value.get("duration_ms")
        for value in planner_diagnostics
        if isinstance(value.get("duration_ms"), int)
    ]
    fallback_rows = [
        value for value in planner_diagnostics if value.get("fallback_reasons")
    ]
    planner_failure_rows = [
        row
        for row in rows
        if row.get("planner_requested") not in {None, "none"}
        and row.get("planner_used") != row.get("planner_requested")
    ]
    return {
        "tasks": count,
        "successes": successes,
        "success_rate": successes / count if count else 0.0,
        "first_attempt_success_rate": (
            sum(bool(row.get("first_attempt_success")) for row in rows) / count
            if count
            else 0.0
        ),
        "escalation_rate": (
            sum(bool(row.get("escalated")) for row in rows) / count if count else 0.0
        ),
        "average_attempts": (
            sum(int(row.get("attempts", 0)) for row in rows) / count if count else 0.0
        ),
        "average_latency_ms": (
            sum(int(row.get("latency_ms", 0)) for row in rows) / count if count else 0.0
        ),
        "average_planning_latency_ms": (
            sum(planning_latencies) / len(planning_latencies)
            if planning_latencies
            else None
        ),
        "planner_fallback_rate": len(fallback_rows) / count if count else 0.0,
        "planner_failure_rate": (
            len(planner_failure_rows) / count if count else 0.0
        ),
        "planner_status_distribution": dict(
            Counter(value.get("status") for value in planner_diagnostics)
        ),
        "planner_used_distribution": dict(
            Counter(row.get("planner_used") for row in rows)
        ),
        "model_distribution": dict(
            Counter(row.get("selected_model") for row in rows)
        ),
        "usage": {
            "metric": "codex_reported_tokens" if mode == "real" else "mock_estimated_usage",
            "total": total_primary if complete_primary else None,
            "average": average_usage,
            "per_success": (
                total_primary / successes
                if complete_primary and successes
                else None
            ),
            "missing_rows": sum(value is None for value in primary),
            "local_planning_input_tokens": sum(
                int(row.get("usage", {}).get("local_planning_input_tokens") or 0)
                for row in rows
            )
            or None,
            "local_planning_output_tokens": sum(
                int(row.get("usage", {}).get("local_planning_output_tokens") or 0)
                for row in rows
            )
            or None,
        },
        "efficiency": (
            (successes / count) / average_usage
            if count and average_usage and average_usage > 0
            else None
        ),
    }


def _comparison(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    candidate_usage = candidate["usage"]["total"]
    baseline_usage = baseline["usage"]["total"]
    same_volume = candidate["tasks"] == baseline["tasks"]
    return {
        "same_task_volume": same_volume,
        "usage_saving_percent": (
            100 * (baseline_usage - candidate_usage) / baseline_usage
            if same_volume and baseline_usage and candidate_usage is not None
            else None
        ),
        "success_rate_delta": candidate["success_rate"] - baseline["success_rate"],
        "first_attempt_success_rate_delta": (
            candidate["first_attempt_success_rate"]
            - baseline["first_attempt_success_rate"]
        ),
        "average_latency_ms_delta": (
            candidate["average_latency_ms"] - baseline["average_latency_ms"]
        ),
    }


def summarize_phase5(
    records: Sequence[dict[str, Any]],
    *,
    mode: str,
) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for scenario in sorted({str(row.get("scenario")) for row in records}):
        rows = [row for row in records if row.get("scenario") == scenario]
        scenarios[scenario] = _metric_block(rows, mode=mode)

    categories: dict[str, Any] = {}
    for category in PHASE5_CATEGORIES:
        category_rows = [row for row in records if row.get("category") == category]
        if not category_rows:
            continue
        categories[category] = {
            scenario: _metric_block(
                [row for row in category_rows if row.get("scenario") == scenario],
                mode=mode,
            )
            for scenario in sorted(
                {str(row.get("scenario")) for row in category_rows}
            )
        }

    comparison_pairs = {
        "qwen_adaptive_vs_luna_adaptive": ("qwen_adaptive", "luna_adaptive"),
        "qwen_adaptive_vs_none_adaptive": ("qwen_adaptive", "none_adaptive"),
        "luna_adaptive_vs_none_adaptive": ("luna_adaptive", "none_adaptive"),
        "none_astra_vs_none_sol": ("none_astra", "none_sol"),
        "qwen_adaptive_vs_none_astra": ("qwen_adaptive", "none_astra"),
        "qwen_sol_vs_none_sol": ("qwen_sol", "none_sol"),
        "luna_sol_vs_none_sol": ("luna_sol", "none_sol"),
        "qwen_sol_vs_luna_sol": ("qwen_sol", "luna_sol"),
    }
    comparisons = {
        name: _comparison(scenarios[candidate], scenarios[baseline])
        for name, (candidate, baseline) in comparison_pairs.items()
        if candidate in scenarios and baseline in scenarios
    }
    category_comparisons = {
        category: {
            name: _comparison(values[candidate], values[baseline])
            for name, (candidate, baseline) in comparison_pairs.items()
            if candidate in values and baseline in values
        }
        for category, values in categories.items()
    }
    required_scenarios = (
        "qwen_adaptive",
        "luna_adaptive",
        "none_adaptive",
        "none_sol",
        "none_astra",
    )
    unique_tasks = len({row.get("task_id") for row in records})
    all_task_ids = {row.get("task_id") for row in records}
    scenario_task_ids = {
        scenario: {
            row.get("task_id")
            for row in records
            if row.get("scenario") == scenario
        }
        for scenario in required_scenarios
    }
    missing_categories = [
        category for category in PHASE5_CATEGORIES if category not in categories
    ]
    claim_blockers: list[str] = []
    if mode != "real":
        claim_blockers.append("results are not from real execution")
    if unique_tasks < 100:
        claim_blockers.append(f"only {unique_tasks} unique tasks; at least 100 required")
    if missing_categories:
        claim_blockers.append("required task categories are missing")
    for scenario in required_scenarios:
        if scenario not in scenarios:
            claim_blockers.append(f"required scenario is missing: {scenario}")
        elif scenario_task_ids[scenario] != all_task_ids:
            claim_blockers.append(f"scenario does not cover the full task set: {scenario}")
        elif scenarios[scenario]["usage"]["missing_rows"]:
            claim_blockers.append(f"scenario has missing usage data: {scenario}")
    return {
        "scenarios": scenarios,
        "categories": categories,
        "comparisons": comparisons,
        "category_comparisons": category_comparisons,
        "missing_required_categories": missing_categories,
        "claim_blockers": claim_blockers,
        "claims_ready": not claim_blockers,
    }


def _validate_phase5_request(
    args: argparse.Namespace,
    tasks: Sequence[BenchmarkTask],
    scenarios: Sequence[Phase5Scenario],
) -> None:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")
    if getattr(args, "check_environment", False) and args.mode != "real":
        raise ValueError("--check-environment requires --mode real")
    if args.mode != "real":
        return
    planning_only = bool(args.plan or getattr(args, "check_environment", False))
    if not args.allow_real_execution and not planning_only:
        raise ValueError("real Phase 5 benchmark requires --allow-real-execution")
    if args.limit is None and not args.full:
        raise ValueError("real Phase 5 benchmark requires --limit N or --full")
    if args.full and len(tasks) < 100:
        raise ValueError(
            f"full Phase 5 benchmark requires at least 100 real tasks; dataset has {len(tasks)}"
        )
    if (
        any(scenario.strategy == "astra" for scenario in scenarios)
        and not args.allow_astra_baseline
        and not planning_only
    ):
        raise ValueError("Astra baseline requires explicit --allow-astra-baseline")
    workspace_backend = getattr(args, "workspace_backend", "local_git")
    if workspace_backend == "swebench_container":
        invalid_backend = [
            task.task_id
            for task in tasks
            if task.provenance.get("validation_backend") != "swebench_container"
        ]
        if invalid_backend:
            raise ValueError(
                "tasks are missing swebench_container provenance: "
                + ", ".join(invalid_backend[:10])
            )
        if not getattr(args, "validation_assets", None):
            raise ValueError("SWE-bench workspace requires --validation-assets")
    else:
        missing_validation = [
            task.task_id for task in tasks if not task.validation.command
        ]
        if missing_validation:
            raise ValueError(
                "real benchmark tasks require validation.command; missing for: "
                + ", ".join(missing_validation[:10])
            )
    if args.full:
        present = {task.category for task in tasks}
        missing = set(PHASE5_CATEGORIES) - present
        if missing:
            raise ValueError(
                "full Phase 5 corpus is missing categories: "
                + ", ".join(sorted(missing))
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-codex-phase5",
        description="Compare planning providers and Astra/Sol efficiency.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dataset", default="benchmarks/phase4_tasks.example.jsonl")
    parser.add_argument("--output", default="data/phase5_results.jsonl")
    parser.add_argument("--workspace-root", default="data/phase5_workspaces")
    parser.add_argument("--git-command", default="git")
    parser.add_argument(
        "--workspace-backend",
        choices=("local_git", "swebench_container"),
        default="local_git",
    )
    parser.add_argument("--validation-assets")
    parser.add_argument("--docker-command", default="docker")
    parser.add_argument("--swebench-python", default=sys.executable)
    parser.add_argument("--evaluation-root", default="data/swebench_evaluations")
    parser.add_argument(
        "--allow-image-pull",
        action="store_true",
        help="Authorize potentially large SWE-bench Docker image downloads",
    )
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument(
        "--planners",
        nargs="+",
        choices=list(PLANNER_MODES),
        default=list(PLANNER_MODES),
    )
    parser.add_argument("--include-planned-sol-controls", action="store_true")
    parser.add_argument(
        "--scenarios",
        nargs="+",
        help="Run only these scenario keys (for example qwen_adaptive) for a bounded pilot",
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
        help="Validate inputs and report call counts without running models",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Check Docker, official SWE-bench, and images without running models",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tasks, dataset_sha256 = load_tasks(args.dataset)
        if args.limit is not None:
            tasks = tasks[: args.limit]
        scenarios = build_scenarios(
            args.planners,
            include_planned_sol_controls=args.include_planned_sol_controls,
            selected_keys=args.scenarios,
        )
        _validate_phase5_request(args, tasks, scenarios)
        assets = None
        if args.mode == "real" and args.workspace_backend == "swebench_container":
            assets = load_swebench_assets(args.validation_assets)
            validate_task_assets(tasks, assets)
        config = AppConfig.load(args.config)
        if args.mode == "real" and args.workspace_backend == "swebench_container":
            # The extracted /testbed is the only workspace-write boundary. Use
            # auto-review so the executor can edit it; hidden grading assets remain
            # outside the target and are never copied into the model workspace.
            config = replace(
                config,
                executor=replace(config.executor, approval_policy="auto-review"),
            )
        adaptive_scenarios = sum(
            scenario.strategy == "adaptive" for scenario in scenarios
        )
        fixed_scenarios = len(scenarios) - adaptive_scenarios
        initial_runs = len(tasks) * len(scenarios)
        maximum_runs = len(tasks) * (
            fixed_scenarios + adaptive_scenarios * config.max_attempts
        )
        planner_calls = Counter(
            scenario.planner
            for scenario in scenarios
            if scenario.planner != "none"
        )
        print(
            f"Plan: tasks={len(tasks)}, scenarios={len(scenarios)}, "
            f"initial executor runs={initial_runs}, max executor runs={maximum_runs}, "
            f"planner calls/task={dict(planner_calls)}, mode={args.mode}, "
            f"workspace={args.workspace_backend}"
        )
        if args.check_environment:
            if args.workspace_backend != "swebench_container":
                raise ValueError(
                    "--check-environment currently requires --workspace-backend "
                    "swebench_container"
                )
            assert assets is not None
            environment = SWEbenchDockerWorkspace(
                args.workspace_root,
                assets,
                docker_command=args.docker_command,
                git_command=args.git_command,
                allow_image_pull=args.allow_image_pull,
                keep=args.keep_workspaces,
            )
            environment.prepare(tasks, swebench_python=args.swebench_python)
            print("SWE-bench environment: ready")
            return 0
        if args.plan:
            return 0

        output_path = Path(args.output).resolve()
        workspace = None
        validator_factory = None
        if args.mode == "real" and args.workspace_backend == "swebench_container":
            assert assets is not None
            workspace = SWEbenchDockerWorkspace(
                args.workspace_root,
                assets,
                docker_command=args.docker_command,
                git_command=args.git_command,
                allow_image_pull=args.allow_image_pull,
                keep=args.keep_workspaces,
            )
            workspace.prepare(tasks, swebench_python=args.swebench_python)
            validator_factory = lambda task: SWEbenchHarnessValidator(
                task,
                assets[task.task_id],
                evaluation_root=args.evaluation_root,
                swebench_python=args.swebench_python,
                git_command=args.git_command,
            )
        elif args.mode == "real":
            workspace = FreshGitWorkspace(
                args.workspace_root,
                git_command=args.git_command,
                keep=args.keep_workspaces,
            )
        if mode_is_real := args.mode == "real":
            assert workspace is not None
            for task in tasks:
                print(f"Baseline validation: {task.task_id}")
                if validator_factory:
                    validate_swebench_baseline(
                        task,
                        validator_factory(task),
                        timeout_seconds=task.validation.timeout_seconds,
                    )
                else:
                    validate_baseline(task, workspace)
        records = run_phase5_benchmark(
            tasks=tasks,
            dataset_sha256=dataset_sha256,
            config=config,
            scenarios=scenarios,
            mode="real" if mode_is_real else "mock",
            output_path=output_path,
            workspace=workspace,
            resume=args.resume,
            log_prompts=args.log_prompts,
            validator_factory=validator_factory,
        )
        summary = {
            "dataset_sha256": dataset_sha256,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "results": summarize_phase5(records, mode=args.mode),
        }
        summary_path = output_path.with_suffix(".summary.json")
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (PlannerError, ModelUnavailableError, OSError, ValueError) as exc:
        print(f"Phase 5 benchmark blocked: {exc}", file=sys.stderr)
        return 2

    print(f"Results: {output_path}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
