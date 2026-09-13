"""Objective result validation used before any escalation decision."""

from __future__ import annotations

import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any

from ..router.schemas import ExecutionResult, ValidationResult, ValidationSpec


class ObjectiveValidator:
    def __init__(self, *, run_command: Any = subprocess.run) -> None:
        self.run_command = run_command

    def validate(
        self,
        execution: ExecutionResult,
        spec: ValidationSpec | None = None,
        working_directory: str | Path | None = None,
    ) -> ValidationResult:
        spec = spec or ValidationSpec()
        failures: list[str] = []
        command_exit_code: int | None = None
        command_duration_ms: int | None = None
        command_timed_out = False

        if not execution.success:
            failures.append("executor reported failure")
        if execution.exit_code != 0:
            failures.append(f"non-zero exit code: {execution.exit_code}")
        if spec.required_output and spec.required_output not in execution.output:
            failures.append("required output is missing")
        if spec.require_changed_files and not execution.changed_files:
            failures.append("required files were unchanged")

        if spec.command and not failures:
            if working_directory is None:
                failures.append("validation command requires a working directory")
            elif spec.timeout_seconds <= 0:
                failures.append("validation command timeout must be positive")
            else:
                started = perf_counter()
                try:
                    completed = self.run_command(
                        list(spec.command),
                        cwd=str(Path(working_directory).resolve()),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=spec.timeout_seconds,
                        shell=False,
                    )
                    command_exit_code = completed.returncode
                    if completed.returncode != 0:
                        failures.append(
                            f"validation command exited with {completed.returncode}"
                        )
                except subprocess.TimeoutExpired:
                    command_timed_out = True
                    failures.append(
                        f"validation command timed out after {spec.timeout_seconds:g}s"
                    )
                except OSError as exc:
                    failures.append(f"validation command failed to start: {exc}")
                finally:
                    command_duration_ms = max(
                        0, int((perf_counter() - started) * 1000)
                    )

        return ValidationResult(
            success=not failures,
            failures=tuple(failures),
            command_exit_code=command_exit_code,
            command_duration_ms=command_duration_ms,
            command_timed_out=command_timed_out,
        )
