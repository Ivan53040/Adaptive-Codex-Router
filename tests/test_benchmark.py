from __future__ import annotations

import argparse
import json
import subprocess
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

from tests.support import ROOT, runtime_path, test_config

from adaptive_codex_router.benchmark.runner import (
    FreshGitWorkspace,
    _validate_run_request,
    load_tasks,
    run_benchmark,
    summarize_records,
    validate_baseline,
)


class Phase4BenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = ROOT / "benchmarks" / "phase4_tasks.example.jsonl"
        self.tasks, self.digest = load_tasks(self.dataset)
        self.paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self.paths:
            path.unlink(missing_ok=True)

    def test_example_dataset_is_resolved_and_objectively_validated(self) -> None:
        self.assertEqual(len(self.tasks), 2)
        self.assertEqual(len(self.digest), 64)
        self.assertTrue(self.tasks[0].repository.is_absolute())
        self.assertTrue(self.tasks[0].validation.command)
        self.assertEqual(self.tasks[0].minimum_model.value, "luna")

    def test_dataset_rejects_shell_string_validation_commands(self) -> None:
        path = ROOT / "tests" / "fixtures" / f"invalid-{uuid4().hex}.jsonl"
        self.paths.append(path)
        path.write_text(
            json.dumps(
                {
                    "id": "unsafe",
                    "prompt": "change it",
                    "repository": ".",
                    "validation": {"command": "python -m unittest"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "array of non-empty strings"):
            load_tasks(path)

    def test_real_run_requires_volume_permission_validation_and_astra_permission(self) -> None:
        args = argparse.Namespace(
            limit=1,
            mode="real",
            allow_real_execution=False,
            full=False,
            strategies=["sol"],
            allow_astra_baseline=False,
        )
        with self.assertRaisesRegex(ValueError, "allow-real-execution"):
            _validate_run_request(args, self.tasks)

        args.allow_real_execution = True
        args.strategies = ["astra"]
        with self.assertRaisesRegex(ValueError, "allow-astra-baseline"):
            _validate_run_request(args, self.tasks)

        args.allow_astra_baseline = True
        _validate_run_request(args, self.tasks)

    def test_full_real_run_requires_100_task_corpus(self) -> None:
        args = argparse.Namespace(
            limit=None,
            mode="real",
            allow_real_execution=True,
            full=True,
            strategies=["sol"],
            allow_astra_baseline=False,
        )
        with self.assertRaisesRegex(ValueError, "at least 100 real tasks"):
            _validate_run_request(args, self.tasks)

    def test_mock_benchmark_runs_fixed_and_adaptive_routes(self) -> None:
        output = runtime_path()
        telemetry = output.with_suffix(".telemetry.jsonl")
        self.paths.extend([output, telemetry])
        config = test_config(runtime_path())
        self.paths.append(config.telemetry.path)
        records = run_benchmark(
            tasks=self.tasks[:1],
            dataset_sha256=self.digest,
            config=config,
            strategies=["luna", "adaptive"],
            mode="mock",
            output_path=output,
            workspace=None,
            resume=False,
            log_prompts=False,
        )
        self.assertEqual(len(records), 2)
        self.assertEqual({row["strategy"] for row in records}, {"luna", "adaptive"})
        self.assertTrue(all(row["mode"] == "mock" for row in records))
        self.assertTrue(all(row["success"] for row in records))
        self.assertTrue(all("prompt" not in row for row in records))
        self.assertTrue(all(row["usage"]["estimated_usage"] for row in records))

    def test_summary_compares_adaptive_with_sol_and_astra(self) -> None:
        def row(strategy: str, tokens: int, success: bool = True) -> dict:
            return {
                "strategy": strategy,
                "success": success,
                "first_attempt_success": success,
                "escalated": False,
                "attempts": 1,
                "latency_ms": 10,
                "selected_model": strategy if strategy != "adaptive" else "luna",
                "selected_effort": "low",
                "minimum_model": "luna",
                "usage": {
                    "reported_tokens": tokens,
                    "uncached_input_tokens": tokens - 5,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 1,
                    "estimated_usage": None,
                },
            }

        summary = summarize_records(
            [row("sol", 200), row("astra", 150), row("adaptive", 100)]
        )
        self.assertEqual(
            summary["comparisons"]["adaptive_vs_sol"][
                "reported_token_saving_percent"
            ],
            50.0,
        )
        self.assertAlmostEqual(
            summary["comparisons"]["adaptive_vs_astra"][
                "reported_token_saving_percent"
            ],
            100 / 3,
        )

    def test_fresh_worktree_uses_the_requested_base_and_cleans_up(self) -> None:
        root = ROOT / "tests" / "fixtures" / f"workspaces-{uuid4().hex}"
        workspace = FreshGitWorkspace(root)
        self.assertEqual(len(workspace.resolve_commit(self.tasks[0])), 40)
        with workspace.materialize(self.tasks[0], "sol") as worktree:
            self.assertNotEqual(worktree, self.tasks[0].repository)
            self.assertTrue((worktree / "calculator.py").is_file())
            (worktree / "status.txt").write_text("CHANGED\n", encoding="utf-8")
        self.assertEqual(list(root.iterdir()), [])
        root.rmdir()

    def test_baseline_validation_must_fail_before_models_run(self) -> None:
        root = ROOT / "tests" / "fixtures" / f"workspaces-{uuid4().hex}"
        workspace = FreshGitWorkspace(root)
        passing = Mock(
            return_value=subprocess.CompletedProcess(["test-tool"], 0, "", "")
        )
        with self.assertRaisesRegex(ValueError, "already passes"):
            validate_baseline(self.tasks[0], workspace, run_command=passing)

        failing = Mock(
            return_value=subprocess.CompletedProcess(["test-tool"], 1, "", "")
        )
        validate_baseline(self.tasks[0], workspace, run_command=failing)
        self.assertEqual(list(root.iterdir()), [])
        root.rmdir()


if __name__ == "__main__":
    unittest.main()
