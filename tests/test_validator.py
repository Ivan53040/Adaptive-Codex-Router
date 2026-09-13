from __future__ import annotations

import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock

from tests.support import SRC  # noqa: F401

from adaptive_codex_router.executor.validator import ObjectiveValidator
from adaptive_codex_router.router.schemas import ExecutionResult, ValidationSpec


class ObjectiveValidatorTests(unittest.TestCase):
    def test_objective_failure_signals_are_combined(self) -> None:
        result = ObjectiveValidator().validate(
            ExecutionResult(success=True, output="done", changed_files=()),
            ValidationSpec(required_output="tests passed", require_changed_files=True),
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.failures), 2)

    def test_uncertainty_text_alone_does_not_fail_validation(self) -> None:
        result = ObjectiveValidator().validate(
            ExecutionResult(success=True, output="I am uncertain", exit_code=0)
        )
        self.assertTrue(result.success)

    def test_validation_command_runs_without_a_shell(self) -> None:
        run_command = Mock(
            return_value=subprocess.CompletedProcess(["test-tool"], 0, "ok", "")
        )
        result = ObjectiveValidator(run_command=run_command).validate(
            ExecutionResult(success=True, exit_code=0),
            ValidationSpec(command=("test-tool", "--quiet"), timeout_seconds=9),
            Path("."),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.command_exit_code, 0)
        self.assertGreaterEqual(result.command_duration_ms or 0, 0)
        self.assertFalse(result.command_timed_out)
        self.assertEqual(run_command.call_args.kwargs["shell"], False)
        self.assertEqual(run_command.call_args.kwargs["timeout"], 9)

    def test_failed_validation_command_is_objective_failure(self) -> None:
        run_command = Mock(
            return_value=subprocess.CompletedProcess(["test-tool"], 7, "", "failed")
        )
        result = ObjectiveValidator(run_command=run_command).validate(
            ExecutionResult(success=True, exit_code=0),
            ValidationSpec(command=("test-tool",)),
            Path("."),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.command_exit_code, 7)
        self.assertEqual(result.failures, ("validation command exited with 7",))

    def test_validation_command_is_skipped_when_executor_failed(self) -> None:
        run_command = Mock()
        result = ObjectiveValidator(run_command=run_command).validate(
            ExecutionResult(success=False, exit_code=1),
            ValidationSpec(command=("test-tool",)),
            Path("."),
        )

        self.assertFalse(result.success)
        run_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
