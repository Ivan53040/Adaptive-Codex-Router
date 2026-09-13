"""Mock and real Codex CLI executors."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from ..config import AppConfig
from ..router.schemas import ExecutionResult, FailureType, ModelName, ModelRoute
from ..telemetry.usage import estimate_mock_usage


class ExecutorPreflightError(ValueError):
    """The selected target cannot safely be passed to Codex."""


class TaskExecutor(Protocol):
    def preflight(self, working_directory: str | Path) -> Path: ...

    def execute(
        self,
        prompt: str,
        route: ModelRoute,
        working_directory: str | Path,
    ) -> ExecutionResult: ...

    def cancel(self) -> bool: ...


class MockCodexExecutor:
    def __init__(
        self,
        *,
        fail_models: set[ModelName] | None = None,
        failure_types: Mapping[ModelName, FailureType] | None = None,
    ) -> None:
        self.fail_models = fail_models or set()
        self.failure_types = dict(failure_types or {})

    def preflight(self, working_directory: str | Path) -> Path:
        return Path(working_directory).resolve()

    def cancel(self) -> bool:
        return False

    def execute(
        self,
        prompt: str,
        route: ModelRoute,
        working_directory: str | Path,
    ) -> ExecutionResult:
        """Return deterministic fake execution metadata without changing files."""
        started = perf_counter()
        _ = Path(working_directory)
        input_tokens = max(1, len(prompt.split()))

        if route.model in self.fail_models:
            duration_ms = max(1, int((perf_counter() - started) * 1000))
            return ExecutionResult(
                success=False,
                output=f"Mock failure for {route.model_id}",
                exit_code=1,
                duration_ms=duration_ms,
                failure_type=self.failure_types.get(route.model, FailureType.CAPABILITY),
                input_tokens=input_tokens,
                output_tokens=5,
                estimated_usage=estimate_mock_usage(route, input_tokens, 5),
            )

        output = f"Mock execution completed with {route.model_id}/{route.effort.value}"
        output_tokens = len(output.split())
        duration_ms = max(1, int((perf_counter() - started) * 1000))
        return ExecutionResult(
            success=True,
            output=output,
            exit_code=0,
            duration_ms=duration_ms,
            changed_files=("<mock-change>",),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_usage=estimate_mock_usage(route, input_tokens, output_tokens),
        )


class CodexExecutor:
    """Run one routed coding task through the logged-in Codex CLI."""

    def __init__(self, config: AppConfig, *, popen_factory: Any = subprocess.Popen) -> None:
        self.config = config
        self.settings = config.executor
        self.popen_factory = popen_factory
        self._active_process: Any | None = None
        self._active_lock = threading.Lock()
        self._cancel_requested = threading.Event()

    def preflight(self, working_directory: str | Path) -> Path:
        target = Path(working_directory).resolve()
        if not target.is_dir():
            raise ExecutorPreflightError(f"working directory does not exist: {target}")
        if self.settings.require_git_repository and self._find_git_root(target) is None:
            raise ExecutorPreflightError(
                f"real execution requires a Git working tree: {target}"
            )
        self._resolve_command(self.settings.codex_command)
        output_directory = self.settings.output_directory.resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        return target

    def cancel(self) -> bool:
        self._cancel_requested.set()
        with self._active_lock:
            process = self._active_process
        if process is None or process.poll() is not None:
            return False
        self._stop_process(process)
        return True

    def execute(
        self,
        prompt: str,
        route: ModelRoute,
        working_directory: str | Path,
    ) -> ExecutionResult:
        target = self.preflight(working_directory)
        command_prefix = self._resolve_command(self.settings.codex_command)
        output_path = self.settings.output_directory.resolve() / (
            f".executor-output-{uuid4().hex}.txt"
        )
        command = self._build_command(command_prefix, route, target, output_path)
        before = self._workspace_snapshot(target)
        started = perf_counter()
        self._cancel_requested.clear()

        try:
            process = self.popen_factory(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(target),
                env=self._chatgpt_auth_environment(),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
            )
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            return self._failure(
                started,
                exit_code=127,
                failure_type=FailureType.EXECUTOR,
                message=f"failed to start Codex CLI: {exc}",
            )

        with self._active_lock:
            self._active_process = process

        try:
            stdout, stderr = process.communicate(
                input=prompt,
                timeout=self.settings.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            self._stop_process(process)
            stdout, stderr = self._drain_process(process)
            output_path.unlink(missing_ok=True)
            changed_files = tuple(
                sorted(self._changed_paths(before, self._workspace_snapshot(target)))
            )
            return self._failure(
                started,
                exit_code=124,
                failure_type=FailureType.TIMEOUT,
                message=f"Codex execution timed out after {self.settings.timeout_seconds:g}s",
                stdout=stdout,
                changed_files=changed_files,
                timed_out=True,
            )
        except KeyboardInterrupt:
            self._cancel_requested.set()
            self._stop_process(process)
            stdout, stderr = self._drain_process(process)
            output_path.unlink(missing_ok=True)
            changed_files = tuple(
                sorted(self._changed_paths(before, self._workspace_snapshot(target)))
            )
            return self._failure(
                started,
                exit_code=130,
                failure_type=FailureType.CANCELLED,
                message="Codex execution was cancelled",
                stdout=stdout,
                changed_files=changed_files,
                cancelled=True,
            )
        finally:
            with self._active_lock:
                if self._active_process is process:
                    self._active_process = None

        usage = self._usage_from_jsonl(stdout)
        final_message = self._read_final_message(output_path, stdout)
        output_path.unlink(missing_ok=True)
        after = self._workspace_snapshot(target)
        changed_files = tuple(sorted(self._changed_paths(before, after)))

        if self._cancel_requested.is_set():
            return self._failure(
                started,
                exit_code=130,
                failure_type=FailureType.CANCELLED,
                message="Codex execution was cancelled",
                stdout=stdout,
                changed_files=changed_files,
                cancelled=True,
            )
        if process.returncode != 0:
            detail = self._safe_error_detail(stderr or stdout)
            message = f"Codex CLI execution failed with exit code {process.returncode}"
            if detail:
                message += f": {detail}"
            return self._failure(
                started,
                exit_code=process.returncode,
                failure_type=FailureType.EXECUTOR,
                message=message,
                stdout=stdout,
                changed_files=changed_files,
            )
        if self._reports_write_denial(final_message, stderr):
            return self._failure(
                started,
                exit_code=1,
                failure_type=FailureType.EXECUTOR,
                message=final_message or "Codex reported that the workspace is not writable",
                stdout=stdout,
                changed_files=changed_files,
            )

        return ExecutionResult(
            success=True,
            output=final_message or "Codex completed without a final message.",
            exit_code=0,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            changed_files=changed_files,
            input_tokens=usage[0],
            cached_input_tokens=usage[1],
            output_tokens=usage[2],
            reasoning_output_tokens=usage[3],
        )

    def _build_command(
        self,
        prefix: Sequence[str],
        route: ModelRoute,
        target: Path,
        output_path: Path,
    ) -> list[str]:
        approval_args = (
            ["--approve-for-me"]
            if self.settings.approval_policy == "auto-review"
            else ["--ask-for-approval", self.settings.approval_policy]
        )
        return [
            *prefix,
            *approval_args,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            self.settings.sandbox,
            "--color",
            "never",
            "--json",
            "--model",
            route.model_id,
            "--config",
            f'model_reasoning_effort="{route.effort.value}"',
            "--config",
            'model_reasoning_summary="none"',
            "--config",
            'model_verbosity="low"',
            "--cd",
            str(target),
            "--output-last-message",
            str(output_path),
            "-",
        ]

    def _failure(
        self,
        started: float,
        *,
        exit_code: int,
        failure_type: FailureType,
        message: str,
        stdout: str = "",
        changed_files: tuple[str, ...] = (),
        timed_out: bool = False,
        cancelled: bool = False,
    ) -> ExecutionResult:
        usage = self._usage_from_jsonl(stdout)
        return ExecutionResult(
            success=False,
            output=message,
            exit_code=exit_code,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            failure_type=failure_type,
            changed_files=changed_files,
            input_tokens=usage[0],
            cached_input_tokens=usage[1],
            output_tokens=usage[2],
            reasoning_output_tokens=usage[3],
            timed_out=timed_out,
            cancelled=cancelled,
        )

    def _stop_process(self, process: Any) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=self.settings.cancel_grace_seconds)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=self.settings.cancel_grace_seconds)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _drain_process(self, process: Any) -> tuple[str, str]:
        try:
            return process.communicate(timeout=max(1.0, self.settings.cancel_grace_seconds))
        except (OSError, subprocess.TimeoutExpired):
            return "", ""

    @staticmethod
    def _resolve_command(command: str) -> list[str]:
        explicit = Path(command)
        if explicit.is_file():
            return [str(explicit.resolve())]
        if os.name == "nt":
            native = (
                shutil.which(f"{command}.exe")
                if not command.lower().endswith(".exe")
                else None
            )
            if native:
                return [native]
        resolved = shutil.which(command)
        if not resolved:
            raise ExecutorPreflightError(
                f"Codex CLI command was not found: {command!r}"
            )
        if os.name == "nt" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", resolved]
        return [resolved]

    def _chatgpt_auth_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("CODEX_API_KEY", None)
        # Codex Desktop may hold the shared state database open. Give benchmark
        # subprocesses a separate writable state home while carrying over only
        # the login credential needed for ChatGPT authentication.
        source_home = Path(environment.get("CODEX_HOME", Path.home() / ".codex"))
        isolated_home = Path.home() / ".adaptive-codex-router" / "codex-home"
        try:
            isolated_home.mkdir(parents=True, exist_ok=True)
            auth = source_home / "auth.json"
            if auth.is_file():
                shutil.copy2(auth, isolated_home / "auth.json")
            environment["CODEX_HOME"] = str(isolated_home)
        except OSError:
            # Preserve the normal environment if the optional isolation home
            # cannot be prepared; the CLI will report the concrete failure.
            pass
        return environment

    @staticmethod
    def _find_git_root(target: Path) -> Path | None:
        for candidate in (target, *target.parents):
            if (candidate / ".git").exists():
                return candidate
        return None

    @staticmethod
    def _workspace_snapshot(target: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for directory, directory_names, file_names in os.walk(target):
            directory_names[:] = [name for name in directory_names if name != ".git"]
            base = Path(directory)
            for name in file_names:
                path = base / name
                try:
                    stat = path.stat(follow_symlinks=False)
                    relative = path.relative_to(target).as_posix()
                    snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    continue
        return snapshot

    @staticmethod
    def _changed_paths(
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
    ) -> set[str]:
        return {
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        }

    @staticmethod
    def _read_final_message(output_path: Path, stdout: str) -> str:
        if output_path.is_file():
            return output_path.read_text(encoding="utf-8-sig").strip()
        for line in reversed(stdout.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message" and isinstance(
                    item.get("text"), str
                ):
                    return item["text"].strip()
        return ""

    @staticmethod
    def _usage_from_jsonl(stdout: str) -> tuple[int | None, int | None, int | None, int | None]:
        found: tuple[int | None, int | None, int | None, int | None] = (
            None,
            None,
            None,
            None,
        )
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = event.get("usage")
            if not isinstance(usage, dict):
                continue
            values = (
                usage.get("input_tokens"),
                usage.get("cached_input_tokens"),
                usage.get("output_tokens"),
                usage.get("reasoning_output_tokens"),
            )
            if any(isinstance(value, int) for value in values):
                found = tuple(
                    value if isinstance(value, int) else None for value in values
                )  # type: ignore[assignment]
        return found

    @staticmethod
    def _safe_error_detail(value: str) -> str:
        return " ".join(value.strip().split())[-1000:]

    @staticmethod
    def _reports_write_denial(final_message: str, stderr: str) -> bool:
        text = f"{final_message}\n{stderr}".lower()
        markers = (
            "workspace is mounted read-only",
            "workspace is read-only",
            "write approval is disabled",
            "permission denied",
            "access is denied",
            "cannot modify the workspace",
            "couldn't modify",
            "could not modify",
        )
        return any(marker in text for marker in markers)


__all__ = [
    "CodexExecutor",
    "ExecutorPreflightError",
    "MockCodexExecutor",
    "TaskExecutor",
]
