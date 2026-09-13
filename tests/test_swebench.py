from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from tests.support import ROOT, SRC  # noqa: F401

from adaptive_codex_router.benchmark.corpus import build_swebench_validation_asset
from adaptive_codex_router.benchmark.runner import BenchmarkTask
from adaptive_codex_router.benchmark.swebench import (
    BASELINE_MARKER_PATCH,
    SWEbenchDockerWorkspace,
    SWEbenchHarnessValidator,
    SWEbenchInfrastructureError,
    load_swebench_assets,
    validate_swebench_baseline,
    validate_task_assets,
)
from adaptive_codex_router.benchmark.swebench_entry import _write_harness_text
from adaptive_codex_router.router.schemas import (
    ExecutionResult,
    TaskMetadata,
    ValidationSpec,
)


def source_row() -> dict:
    return {
        "instance_id": "owner__repo-1",
        "repo": "owner/repo",
        "base_commit": "1" * 40,
        "problem_statement": "Fix the regression",
        "image": "swebench/example:latest",
        "eval_script": "#!/bin/bash\necho tests\n",
        "log_parser": "parse_log_pytest",
        "FAIL_TO_PASS": ["tests/test_bug.py::test_bug"],
        "PASS_TO_PASS": ["tests/test_ok.py::test_ok"],
        "test_patch": "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
        "patch": "gold must not be used",
        "hints_text": "secret hint",
        "created_at": "2025-01-01T00:00:00Z",
        "difficulty": "<15 min fix",
        "version": "1.0",
        "environment_setup_commit": "2" * 40,
        "eval_type": "pass_and_fail",
    }


class SWEbenchIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / "fixtures" / f"swebench-{uuid4().hex}"
        self.root.mkdir(parents=True)
        asset = build_swebench_validation_asset(3, source_row())
        self.asset_path = self.root / "assets.jsonl"
        self.asset_path.write_text(json.dumps(asset) + "\n", encoding="utf-8")
        self.assets = load_swebench_assets(self.asset_path)
        self.task = BenchmarkTask(
            task_id="owner__repo-1",
            prompt="Fix the regression",
            repository=self.root / "missing",
            base_ref="1" * 40,
            category="debugging",
            metadata=TaskMetadata(tests_requested=True),
            validation=ValidationSpec(require_changed_files=True, timeout_seconds=5),
            provenance={
                "dataset": "SWE-bench/SWE-bench_Verified",
                "revision": "78f471bf655a3137b2e8a75af1501690ec009ec3",
                "row_index": 3,
                "source_repo": "owner/repo",
                "validation_backend": "swebench_container",
                "validation_asset_sha256": asset["asset_sha256"],
                "container_image": "swebench/example:latest",
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_asset_is_hash_linked_to_manifest_and_seals_test_patch(self) -> None:
        validate_task_assets([self.task], self.assets)
        asset = self.assets[self.task.task_id]
        self.assertIn("test_patch", asset.instance)
        self.assertEqual(asset.instance["patch"], "")
        self.assertNotIn("hints_text", asset.instance)

    def test_tampered_asset_is_rejected(self) -> None:
        value = json.loads(self.asset_path.read_text(encoding="utf-8"))
        value["instance"]["eval_script"] += "echo tampered\n"
        self.asset_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            load_swebench_assets(self.asset_path)

    def test_manifest_identity_must_match_sealed_asset(self) -> None:
        mismatched = replace(self.task, base_ref="2" * 40)
        with self.assertRaisesRegex(ValueError, "base commit mismatch"):
            validate_task_assets([mismatched], self.assets)

    def test_prepare_requires_explicit_image_pull(self) -> None:
        def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            if args[1] == "version":
                return subprocess.CompletedProcess(args, 0, "29.4.3\n", "")
            if args[0] == "swebench-python":
                return subprocess.CompletedProcess(args, 0, "5.0.2\n", "")
            return subprocess.CompletedProcess(args, 1, "", "not found")

        workspace = SWEbenchDockerWorkspace(
            self.root / "workspaces",
            self.assets,
            run_command=fake_run,
        )
        with self.assertRaisesRegex(ValueError, "allow-image-pull"):
            workspace.prepare([self.task], swebench_python="swebench-python")

    def test_official_report_controls_validation_not_process_exit(self) -> None:
        workspace = self.root / "repo"
        workspace.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.invalid"],
            cwd=workspace,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Router Tests"],
            cwd=workspace,
            check=True,
        )
        (workspace / "fix.py").write_text("before = True\n", encoding="utf-8")
        subprocess.run(["git", "add", "fix.py"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "base"], cwd=workspace, check=True)
        (workspace / "fix.py").write_text("before = False\n", encoding="utf-8")

        def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
            if args[0] == "git":
                return subprocess.run(args, **kwargs)
            report = Path(kwargs["cwd"]) / "logs" / "report.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps({self.task.task_id: {"resolved": True}}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(args, 9, "harness warning", "")

        validator = SWEbenchHarnessValidator(
            self.task,
            self.assets[self.task.task_id],
            evaluation_root=self.root / "evaluations",
            swebench_python="swebench-python",
            run_command=fake_run,
        )
        # This fixture does not use the sealed task commit; compare against the
        # repository's local HEAD for the patch-capture assertion.
        validator.task = replace(self.task, base_ref="HEAD")
        result = validator.validate(
            ExecutionResult(success=True, changed_files=("fix.py",)),
            self.task.validation,
            workspace,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.command_exit_code, 9)

    def test_baseline_uses_noop_patch_and_requires_unresolved_report(self) -> None:
        calls: list[str] = []

        class FakeValidator:
            def evaluate_patch(self, patch: str, **kwargs):
                calls.append(patch)
                return False, 0, 1

        validate_swebench_baseline(
            self.task,
            FakeValidator(),  # type: ignore[arg-type]
            timeout_seconds=5,
        )
        self.assertEqual(calls, [BASELINE_MARKER_PATCH])

    def test_baseline_marker_is_a_valid_git_patch(self) -> None:
        workspace = self.root / "baseline-repo"
        workspace.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        checked = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=workspace,
            input=BASELINE_MARKER_PATCH,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_patch_capture_includes_changes_committed_by_executor(self) -> None:
        workspace = self.root / "committed-repo"
        workspace.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=workspace, check=True)
        subprocess.run(["git", "config", "user.name", "Router Tests"], cwd=workspace, check=True)
        file_path = workspace / "fix.py"
        file_path.write_text("before = True\n", encoding="utf-8")
        subprocess.run(["git", "add", "fix.py"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "base"], cwd=workspace, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, capture_output=True, text=True, check=True).stdout.strip()
        file_path.write_text("before = False\n", encoding="utf-8")
        subprocess.run(["git", "add", "fix.py"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "fix"], cwd=workspace, check=True)
        committed_task = replace(self.task, base_ref=base)
        validator = SWEbenchHarnessValidator(
            committed_task, self.assets[self.task.task_id],
            evaluation_root=self.root / "evaluations", swebench_python="python",
        )
        patch = validator._workspace_patch(workspace)
        self.assertIn("before = False", patch)
        self.assertIn("before = True", patch)

    def test_harness_linux_artifacts_use_utf8_lf(self) -> None:
        for name in ("eval.sh", "patch.diff"):
            target = self.root / name
            _write_harness_text(target, "echo café\n", encoding="ascii", newline="\r\n")
            self.assertEqual(target.read_bytes(), "echo café\n".encode("utf-8"))
        other = self.root / "other.txt"
        _write_harness_text(other, "line\n", newline="\r\n")
        self.assertEqual(other.read_bytes(), b"line\r\n")

    def test_unresolved_report_without_executed_tests_is_not_valid_baseline(self) -> None:
        report = self.root / "report.json"
        report.write_text(json.dumps({self.task.task_id: {
            "resolved": False, "patch_successfully_applied": False,
            "infra_failure": False,
        }}), encoding="utf-8")
        with self.assertRaisesRegex(SWEbenchInfrastructureError, "baseline requires"):
            SWEbenchHarnessValidator._resolved_from_reports(
                self.root, self.task.task_id, require_valid_baseline=True,
            )

    def test_baseline_requires_failing_targets(self) -> None:
        report = self.root / "report.json"
        for target_failures, control_failures, valid in (
            (["bug"], [], True), ([], [], False), (["bug"], ["truncated-alias"], True),
        ):
            report.write_text(json.dumps({self.task.task_id: {
                "resolved": False, "patch_successfully_applied": True,
                "tests_status": {
                    "FAIL_TO_PASS": {"failure": target_failures},
                    "PASS_TO_PASS": {"failure": control_failures},
                },
            }}), encoding="utf-8")
            if valid:
                self.assertFalse(SWEbenchHarnessValidator._resolved_from_reports(
                    self.root, self.task.task_id, require_valid_baseline=True,
                ))
            else:
                with self.assertRaises(SWEbenchInfrastructureError):
                    SWEbenchHarnessValidator._resolved_from_reports(
                        self.root, self.task.task_id, require_valid_baseline=True,
                    )

    def test_infrastructure_failure_aborts_instead_of_model_escalation(self) -> None:
        validator = SWEbenchHarnessValidator(
            self.task, self.assets[self.task.task_id],
            evaluation_root=self.root / "evaluations", swebench_python="python",
        )
        with patch.object(validator, "_workspace_patch", return_value="diff"), patch.object(
            validator, "evaluate_patch", side_effect=SWEbenchInfrastructureError("grader offline"),
        ), self.assertRaisesRegex(SWEbenchInfrastructureError, "grader offline"):
            validator.validate(
                ExecutionResult(success=True, changed_files=("fix.py",)),
                self.task.validation, self.root,
            )


if __name__ == "__main__":
    unittest.main()
