from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

from tests.support import ROOT, SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.benchmark.phase5 import (
    PHASE5_CATEGORIES,
    _validate_phase5_request,
    build_parser,
    build_scenarios,
    run_phase5_benchmark,
    summarize_phase5,
)
from adaptive_codex_router.benchmark.runner import load_tasks


def summary_row(
    scenario: str,
    category: str,
    usage: int,
    *,
    success: bool = True,
) -> dict:
    planner = scenario.split("_", 1)[0]
    return {
        "scenario": scenario,
        "category": category,
        "task_id": f"{scenario}-{category}",
        "success": success,
        "first_attempt_success": success,
        "escalated": False,
        "attempts": 1,
        "latency_ms": 100,
        "selected_model": "astra" if scenario.endswith("astra") else "sol",
        "planner_used": planner,
        "planner": {"duration_ms": 20, "fallback_reasons": []},
        "usage": {
            "reported_tokens": usage,
            "estimated_usage": None,
            "local_planning_input_tokens": 10 if planner == "qwen" else None,
            "local_planning_output_tokens": 20 if planner == "qwen" else None,
        },
    }


class Phase5BenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks, self.digest = load_tasks(
            ROOT / "benchmarks" / "phase4_tasks.example.jsonl"
        )
        self.paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self.paths:
            path.unlink(missing_ok=True)

    def test_swebench_harness_defaults_to_current_python(self) -> None:
        self.assertEqual(build_parser().parse_args([]).swebench_python, sys.executable)

    def test_default_scenarios_cover_planners_and_astra_sol_controls(self) -> None:
        scenarios = build_scenarios(["qwen", "luna", "none"])
        self.assertEqual(
            {scenario.key for scenario in scenarios},
            {
                "qwen_adaptive",
                "luna_adaptive",
                "none_adaptive",
                "none_sol",
                "none_astra",
            },
        )

    def test_optional_sol_controls_isolate_planning_effect(self) -> None:
        scenarios = build_scenarios(
            ["qwen", "luna", "none"],
            include_planned_sol_controls=True,
        )
        self.assertIn("qwen_sol", {scenario.key for scenario in scenarios})
        self.assertIn("luna_sol", {scenario.key for scenario in scenarios})

    def test_qwen_only_pilot_does_not_require_astra_baseline_permission(self) -> None:
        args = build_parser().parse_args([
            "--mode", "real", "--limit", "1", "--allow-real-execution",
            "--scenarios", "qwen_adaptive",
        ])
        scenarios = build_scenarios(args.planners, selected_keys=args.scenarios)
        self.assertEqual([scenario.key for scenario in scenarios], ["qwen_adaptive"])
        _validate_phase5_request(args, self.tasks[:1], scenarios)

    def test_explicit_astra_selection_still_requires_permission(self) -> None:
        args = build_parser().parse_args([
            "--mode", "real", "--limit", "1", "--allow-real-execution",
            "--scenarios", "none_astra",
        ])
        scenarios = build_scenarios(args.planners, selected_keys=args.scenarios)
        with self.assertRaisesRegex(ValueError, "allow-astra-baseline"):
            _validate_phase5_request(args, self.tasks[:1], scenarios)

    def test_scenario_selection_rejects_invalid_and_disabled_keys(self) -> None:
        for keys in ([], ["qwen_adaptive", "qwen_adaptive"], ["typo"], ["luna_adaptive"], ["qwen_sol"]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                build_scenarios(["qwen"], selected_keys=keys)

    def test_mock_matrix_records_requested_and_used_planners(self) -> None:
        output = runtime_path()
        telemetry = output.with_suffix(".telemetry.jsonl")
        config = test_config(runtime_path())
        self.paths.extend([output, telemetry, config.telemetry.path])
        records = run_phase5_benchmark(
            tasks=self.tasks[:1],
            dataset_sha256=self.digest,
            config=config,
            scenarios=build_scenarios(["qwen", "luna", "none"]),
            mode="mock",
            output_path=output,
            workspace=None,
            resume=False,
            log_prompts=False,
        )
        self.assertEqual(len(records), 5)
        self.assertTrue(all(record["phase"] == 5 for record in records))
        self.assertTrue(all(record["success"] for record in records))
        self.assertEqual(
            {record["planner_used"] for record in records},
            {"qwen", "luna", "none"},
        )
        self.assertTrue(all("prompt" not in record for record in records))

    def test_summary_computes_efficiency_and_comparisons_by_category(self) -> None:
        rows = [
            summary_row("qwen_adaptive", "debugging", 60),
            summary_row("luna_adaptive", "debugging", 80),
            summary_row("none_adaptive", "debugging", 90),
            summary_row("none_sol", "debugging", 100),
            summary_row("none_astra", "debugging", 75),
        ]
        summary = summarize_phase5(rows, mode="real")
        self.assertEqual(
            summary["scenarios"]["qwen_adaptive"]["usage"]["per_success"],
            60,
        )
        self.assertAlmostEqual(
            summary["scenarios"]["qwen_adaptive"]["efficiency"],
            1 / 60,
        )
        self.assertEqual(
            summary["comparisons"]["none_astra_vs_none_sol"]["usage_saving_percent"],
            25.0,
        )
        self.assertIn("debugging", summary["categories"])
        self.assertIn("simple_coding", summary["missing_required_categories"])
        self.assertFalse(summary["claims_ready"])
        self.assertTrue(
            any("at least 100" in blocker for blocker in summary["claim_blockers"])
        )

    def test_real_execution_and_full_claims_are_guarded(self) -> None:
        scenarios = build_scenarios(["qwen", "luna", "none"])
        args = argparse.Namespace(
            limit=1,
            mode="real",
            allow_real_execution=False,
            full=False,
            allow_astra_baseline=False,
            plan=False,
        )
        with self.assertRaisesRegex(ValueError, "allow-real-execution"):
            _validate_phase5_request(args, self.tasks, scenarios)

        args.allow_real_execution = True
        with self.assertRaisesRegex(ValueError, "allow-astra-baseline"):
            _validate_phase5_request(args, self.tasks, scenarios)

        args.allow_astra_baseline = True
        _validate_phase5_request(args, self.tasks, scenarios)

        args.limit = None
        args.full = True
        repeated = self.tasks * 50
        with self.assertRaisesRegex(ValueError, "missing categories"):
            _validate_phase5_request(args, repeated, scenarios)

    def test_phase5_category_contract_matches_plan(self) -> None:
        self.assertEqual(
            set(PHASE5_CATEGORIES),
            {
                "simple_coding",
                "normal_implementation",
                "debugging",
                "large_refactor",
                "architecture",
                "repository_analysis",
                "long_agentic",
                "large_context",
            },
        )


if __name__ == "__main__":
    unittest.main()
