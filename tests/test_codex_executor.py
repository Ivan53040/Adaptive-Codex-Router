from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT, runtime_path, test_config

from adaptive_codex_router.executor.codex import CodexExecutor, ExecutorPreflightError
from adaptive_codex_router.router.schemas import (
    FailureType,
    ModelName,
    ModelRoute,
    ReasoningEffort,
)


def event_stream() -> str:
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Implemented and tested."},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 150,
                        "output_tokens": 40,
                        "reasoning_output_tokens": 10,
                    },
                }
            ),
        ]
    )


class FakeProcess:
    def __init__(
        self,
        command: list[str],
        kwargs: dict[str, object],
        *,
        returncode: int = 0,
        timeout: bool = False,
        interrupt: bool = False,
        blocking: bool = False,
        deny_write: bool = False,
        partial_on_deny: bool = False,
    ) -> None:
        self.command = command
        self.kwargs = kwargs
        self.returncode = returncode
        self.timeout = timeout
        self.interrupt = interrupt
        self.blocking = blocking
        self.deny_write = deny_write
        self.partial_on_deny = partial_on_deny
        self.running = True
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.communicate_calls = 0
        self.stdin_value: str | None = None

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        if input is not None:
            self.stdin_value = input
        self.started.set()
        if self.interrupt and self.communicate_calls == 1:
            raise KeyboardInterrupt
        if self.timeout and self.communicate_calls == 1:
            target = Path(str(self.kwargs["cwd"])) / "hello.txt"
            target.write_text("PARTIAL_CHANGE\n", encoding="utf-8")
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.blocking:
            self.stopped.wait(3)
        if self.returncode == 0 and not self.stopped.is_set() and not self.deny_write:
            target = Path(str(self.kwargs["cwd"])) / "hello.txt"
            target.write_text("PHASE3_OK\n", encoding="utf-8")
            output_path = Path(
                self.command[self.command.index("--output-last-message") + 1]
            )
            output_path.write_text("Implemented and tested.", encoding="utf-8")
        elif self.deny_write:
            if self.partial_on_deny:
                target = Path(str(self.kwargs["cwd"])) / "hello.txt"
                target.write_text("PARTIAL_CHANGE\n", encoding="utf-8")
            output_path = Path(
                self.command[self.command.index("--output-last-message") + 1]
            )
            output_path.write_text(
                "I couldn't modify the workspace because it is mounted read-only.",
                encoding="utf-8",
            )
        self.running = False
        return event_stream(), "executor stderr" if self.returncode else ""

    def poll(self):
        return None if self.running else self.returncode

    def terminate(self):
        self.returncode = -15
        self.running = False
        self.stopped.set()

    def kill(self):
        self.returncode = -9
        self.running = False
        self.stopped.set()

    def wait(self, timeout=None):
        self.running = False
        return self.returncode


class FakePopenFactory:
    def __init__(self, **process_options) -> None:
        self.process_options = process_options
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.process: FakeProcess | None = None
        self.created = threading.Event()

    def __call__(self, command: list[str], **kwargs):
        self.calls.append((command, kwargs))
        self.process = FakeProcess(command, kwargs, **self.process_options)
        self.created.set()
        return self.process


class CodexExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / "fixtures" / "executor_repo"
        (self.root / "hello.txt").write_text("PHASE3_PENDING\n", encoding="utf-8")
        base = test_config(runtime_path())
        self.config = replace(
            base,
            executor=replace(
                base.executor,
                mode="codex",
                codex_command=sys.executable,
                output_directory=self.root / "outputs",
                require_git_repository=False,
            ),
        )
        self.route = ModelRoute(
            model=ModelName.TERRA,
            model_id="gpt-5.6-terra",
            effort=ReasoningEffort.MEDIUM,
        )

    def tearDown(self) -> None:
        self.config.telemetry.path.unlink(missing_ok=True)
        (self.root / "hello.txt").write_text("PHASE3_PENDING\n", encoding="utf-8")
        for path in (self.root / "outputs").glob(".executor-output-*.txt"):
            path.unlink(missing_ok=True)

    def test_real_command_is_scoped_and_captures_result_usage_and_files(self) -> None:
        factory = FakePopenFactory()
        executor = CodexExecutor(self.config, popen_factory=factory)
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "hidden", "CODEX_API_KEY": "also-hidden"},
        ):
            result = executor.execute("Change the marker", self.route, self.root)

        self.assertTrue(result.success)
        self.assertEqual(result.output, "Implemented and tested.")
        self.assertEqual(result.changed_files, ("hello.txt",))
        self.assertEqual(result.input_tokens, 200)
        self.assertEqual(result.cached_input_tokens, 150)
        self.assertEqual(result.output_tokens, 40)
        self.assertEqual(result.reasoning_output_tokens, 10)

        command, kwargs = factory.calls[0]
        command_text = " ".join(command)
        self.assertIn("--approve-for-me exec", command_text)
        self.assertIn("--sandbox workspace-write", command_text)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("gpt-5.6-terra", command)
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertNotIn("Change the marker", command_text)
        self.assertEqual(factory.process.stdin_value, "Change the marker")
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", kwargs["env"])

    def test_never_policy_uses_supported_noninteractive_flag(self) -> None:
        config = replace(
            self.config,
            executor=replace(self.config.executor, approval_policy="never"),
        )
        command = CodexExecutor(config)._build_command(
            ["codex"], self.route, self.root, self.root / "out.txt",
        )
        self.assertNotIn("--approve-for-me", command)
        self.assertEqual(command[1:4], ["--ask-for-approval", "never", "exec"])

    def test_timeout_is_terminal_and_preserves_partial_file_detection(self) -> None:
        factory = FakePopenFactory(timeout=True)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result = executor.execute("Change the marker", self.route, self.root)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_type, FailureType.TIMEOUT)
        self.assertEqual(result.exit_code, 124)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.changed_files, ("hello.txt",))

    def test_nonzero_exit_is_an_executor_failure(self) -> None:
        factory = FakePopenFactory(returncode=7)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result = executor.execute("private prompt", self.route, self.root)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_type, FailureType.EXECUTOR)
        self.assertEqual(result.exit_code, 7)
        self.assertNotIn("private prompt", result.output)

    def test_write_denial_with_zero_cli_exit_is_an_executor_failure(self) -> None:
        factory = FakePopenFactory(deny_write=True)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result = executor.execute("Change the marker", self.route, self.root)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_type, FailureType.EXECUTOR)
        self.assertIn("read-only", result.output)

    def test_write_denial_preserves_any_partial_file_changes(self) -> None:
        factory = FakePopenFactory(deny_write=True, partial_on_deny=True)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result = executor.execute("Change the marker", self.route, self.root)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_type, FailureType.EXECUTOR)
        self.assertEqual(result.changed_files, ("hello.txt",))

    def test_keyboard_interrupt_cancels_execution(self) -> None:
        factory = FakePopenFactory(interrupt=True)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result = executor.execute("Change the marker", self.route, self.root)

        self.assertFalse(result.success)
        self.assertEqual(result.failure_type, FailureType.CANCELLED)
        self.assertEqual(result.exit_code, 130)
        self.assertTrue(result.cancelled)

    def test_cancel_stops_an_active_process(self) -> None:
        factory = FakePopenFactory(blocking=True)
        executor = CodexExecutor(self.config, popen_factory=factory)
        result_holder = []
        thread = threading.Thread(
            target=lambda: result_holder.append(
                executor.execute("Change the marker", self.route, self.root)
            )
        )
        thread.start()
        self.assertTrue(factory.created.wait(1))
        self.assertIsNotNone(factory.process)
        self.assertTrue(factory.process.started.wait(1))
        self.assertTrue(executor.cancel())
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder[0].failure_type, FailureType.CANCELLED)
        self.assertTrue(result_holder[0].cancelled)

    def test_preflight_rejects_non_git_directory(self) -> None:
        config = replace(
            self.config,
            executor=replace(self.config.executor, require_git_repository=True),
        )
        executor = CodexExecutor(config, popen_factory=FakePopenFactory())
        with self.assertRaisesRegex(ExecutorPreflightError, "requires a Git working tree"):
            executor.preflight(self.root)


if __name__ == "__main__":
    unittest.main()
