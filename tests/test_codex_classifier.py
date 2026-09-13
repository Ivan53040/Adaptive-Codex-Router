from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.support import SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.router.codex_classifier import (
    ClassifierInvocationError,
    ClassifierOutputError,
    ClassifierTimeoutError,
    LunaCodexClassifier,
)
from adaptive_codex_router.router.schemas import TaskMetadata, TaskType


def valid_payload() -> dict[str, object]:
    return {
        "task_type": "debugging",
        "scope": "multi_file",
        "reasoning_complexity": "high",
        "agentic_complexity": "medium",
        "ambiguity": "medium",
        "risk": "medium",
        "verification_difficulty": "high",
        "context_requirement": "medium",
        "expected_task_length": "medium",
        "confidence": 0.91,
        "number_of_expected_steps": 4,
        "cross_module_dependency": True,
    }


class FakeRunner:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs):
        self.calls.append((command, kwargs))
        outcome = self.outputs.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        returncode = 0
        stderr = ""
        raw = outcome
        if isinstance(outcome, tuple):
            returncode, raw, stderr = outcome
        output_path = Path(command[command.index("--output-last-message") + 1])
        if raw is not None:
            output_path.write_text(str(raw), encoding="utf-8")
        stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "cached_input_tokens": 96,
                    "output_tokens": 35,
                },
            }
        )
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


class LunaCodexClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.telemetry_path = runtime_path()
        base = test_config(self.telemetry_path)
        self.config = replace(
            base,
            classifier=replace(base.classifier, mode="codex", codex_command=sys.executable),
        )

    def tearDown(self) -> None:
        self.telemetry_path.unlink(missing_ok=True)
        for path in self.config.classifier.working_directory.glob(".classifier-output-*.json"):
            path.unlink(missing_ok=True)

    def test_valid_json_uses_isolated_low_effort_codex_call(self) -> None:
        runner = FakeRunner([json.dumps(valid_payload())])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "must-not-be-used",
                "CODEX_API_KEY": "also-must-not-be-used",
            },
        ):
            result = classifier.classify("Fix the private race condition")

        self.assertEqual(result.task_type, TaskType.DEBUGGING)
        command, kwargs = runner.calls[0]
        command_text = " ".join(command)
        self.assertIn("gpt-5.6-luna", command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("read-only", command)
        self.assertNotIn("private race condition", command_text)
        self.assertIn("private race condition", str(kwargs["input"]))
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", kwargs["env"])
        self.assertEqual(classifier.last_diagnostics.input_tokens, 120)
        self.assertEqual(classifier.last_diagnostics.cached_input_tokens, 96)
        self.assertEqual(classifier.last_diagnostics.output_tokens, 35)

    def test_fenced_json_is_recovered_without_another_call(self) -> None:
        runner = FakeRunner([f"```json\n{json.dumps(valid_payload())}\n```"])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        classifier.classify("Debug the failure")
        self.assertEqual(len(runner.calls), 1)

    def test_batch_classifies_multiple_tasks_in_one_codex_call(self) -> None:
        payload = {
            "results": [
                {"name": "first", "classification": valid_payload()},
                {"name": "second", "classification": valid_payload()},
            ]
        }
        runner = FakeRunner([json.dumps(payload)])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        results = classifier.classify_many(
            [
                ("first", "Debug task one", TaskMetadata()),
                ("second", "Debug task two", TaskMetadata()),
            ]
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.task_type is TaskType.DEBUGGING for result in results))
        self.assertEqual(len(runner.calls), 1)
        command, kwargs = runner.calls[0]
        schema = command[command.index("--output-schema") + 1]
        self.assertTrue(schema.endswith("classification_batch.schema.json"))
        self.assertIn("BATCH_INPUT", str(kwargs["input"]))

    def test_malformed_json_retries_once(self) -> None:
        runner = FakeRunner(["not json", json.dumps(valid_payload())])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        classifier.classify("Debug the failure")
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(classifier.last_diagnostics.attempts, 2)
        self.assertIn("prior response was malformed", str(runner.calls[1][1]["input"]))

    def test_timeout_is_reported(self) -> None:
        runner = FakeRunner([subprocess.TimeoutExpired(["codex"], timeout=45)])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        with self.assertRaisesRegex(ClassifierTimeoutError, "timed out"):
            classifier.classify("Debug the failure")

    def test_nonzero_exit_is_reported_without_prompt_echo(self) -> None:
        runner = FakeRunner([(7, None, "authentication unavailable")])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        with self.assertRaisesRegex(ClassifierInvocationError, "exit code 7"):
            classifier.classify("private prompt")

    def test_schema_invalid_output_is_rejected_after_retries(self) -> None:
        invalid = valid_payload()
        invalid["task_type"] = "invented"
        runner = FakeRunner([json.dumps(invalid), json.dumps(invalid)])
        classifier = LunaCodexClassifier(self.config, runner=runner)
        with self.assertRaises(ClassifierOutputError):
            classifier.classify("Debug the failure")
        self.assertEqual(len(runner.calls), 2)


if __name__ == "__main__":
    unittest.main()
