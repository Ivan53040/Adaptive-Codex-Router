"""Tiny JSON-only Luna classifier backed by the logged-in Codex CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from ..config import AppConfig
from .prompts import build_luna_batch_classifier_prompt, build_luna_classifier_prompt
from .schemas import (
    ClassifierDiagnostics,
    ModelName,
    ReasoningEffort,
    TaskClassification,
    TaskMetadata,
)

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
ParsedOutput = TypeVar("ParsedOutput")


class ClassifierError(RuntimeError):
    """Base error for a failed Codex-backed classification."""


class CodexNotFoundError(ClassifierError):
    pass


class ClassifierTimeoutError(ClassifierError):
    pass


class ClassifierInvocationError(ClassifierError):
    pass


class ClassifierOutputError(ClassifierError):
    pass


class LunaCodexClassifier:
    """Run a minimal, isolated Codex exec using Luna with low reasoning."""

    def __init__(
        self,
        config: AppConfig,
        *,
        runner: ProcessRunner = subprocess.run,
        schema_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.settings = config.classifier
        self.model_id = config.model(ModelName.LUNA).model_id
        self.runner = runner
        self.schema_path = Path(schema_path) if schema_path else Path(__file__).with_name(
            "classification.schema.json"
        )
        self.last_diagnostics: ClassifierDiagnostics | None = None

    def classify(
        self,
        prompt: str,
        metadata: TaskMetadata | None = None,
    ) -> TaskClassification:
        metadata = metadata or TaskMetadata()
        return self._classify_output(
            self.schema_path,
            lambda retry: build_luna_classifier_prompt(prompt, metadata, retry=retry),
            self._parse_classification,
            timeout_seconds=self.settings.timeout_seconds,
        )

    def classify_many(
        self,
        tasks: Sequence[tuple[str, str, TaskMetadata]],
    ) -> list[TaskClassification]:
        if not 1 <= len(tasks) <= 50:
            raise ValueError("batch classification requires between 1 and 50 tasks")
        names = [name for name, _, _ in tasks]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise ValueError("batch task names must be non-empty and unique")
        batch_schema = Path(__file__).with_name("classification_batch.schema.json")
        return self._classify_output(
            batch_schema,
            lambda retry: build_luna_batch_classifier_prompt(tasks, retry=retry),
            lambda raw: self._parse_batch_classifications(raw, names),
            timeout_seconds=self.settings.batch_timeout_seconds,
        )

    def _classify_output(
        self,
        schema_path: Path,
        request_builder: Callable[[bool], str],
        parser: Callable[[str], ParsedOutput],
        *,
        timeout_seconds: float,
    ) -> ParsedOutput:
        workspace = self.settings.working_directory.resolve()
        if not workspace.is_dir():
            raise ClassifierInvocationError(
                f"classifier working directory does not exist: {workspace}"
            )
        schema = schema_path.resolve()
        if not schema.is_file():
            raise ClassifierInvocationError(f"classification schema does not exist: {schema}")

        command_prefix = self._resolve_command(self.settings.codex_command)
        started = perf_counter()
        last_error: ClassifierOutputError | None = None
        total_attempts = self.settings.max_malformed_retries + 1

        for attempt in range(1, total_attempts + 1):
            output_path = workspace / f".classifier-output-{uuid4().hex}.json"
            command = self._build_command(command_prefix, workspace, schema, output_path)
            request = request_builder(attempt > 1)
            try:
                completed = self.runner(
                    command,
                    input=request,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    cwd=str(workspace),
                    env=self._chatgpt_auth_environment(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                self._set_diagnostics(started, attempt, None, None, None)
                raise ClassifierTimeoutError(
                    f"Luna classification timed out after {timeout_seconds:g}s"
                ) from exc
            except OSError as exc:
                self._set_diagnostics(started, attempt, None, None, None)
                raise ClassifierInvocationError(f"failed to start Codex CLI: {exc}") from exc

            input_tokens, cached_input_tokens, output_tokens = self._usage_from_jsonl(
                completed.stdout
            )
            if completed.returncode != 0:
                output_path.unlink(missing_ok=True)
                self._set_diagnostics(
                    started, attempt, input_tokens, cached_input_tokens, output_tokens
                )
                detail = self._safe_error_detail(completed.stderr or completed.stdout)
                raise ClassifierInvocationError(
                    f"Codex CLI classification failed with exit code {completed.returncode}"
                    + (f": {detail}" if detail else "")
                )

            raw = self._read_final_message(output_path, completed.stdout)
            output_path.unlink(missing_ok=True)
            try:
                result = parser(raw)
            except ClassifierOutputError as exc:
                last_error = exc
                if attempt < total_attempts:
                    continue
                self._set_diagnostics(
                    started, attempt, input_tokens, cached_input_tokens, output_tokens
                )
                raise

            self._set_diagnostics(
                started, attempt, input_tokens, cached_input_tokens, output_tokens
            )
            return result

        raise last_error or ClassifierOutputError("Luna returned no classification")

    def _build_command(
        self,
        prefix: Sequence[str],
        workspace: Path,
        schema: Path,
        output_path: Path,
    ) -> list[str]:
        return [
            *prefix,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--json",
            "--model",
            self.model_id,
            "--config",
            'model_reasoning_effort="low"',
            "--config",
            'model_reasoning_summary="none"',
            "--config",
            'model_verbosity="low"',
            "--cd",
            str(workspace),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output_path),
            "-",
        ]

    @staticmethod
    def _resolve_command(command: str) -> list[str]:
        explicit = Path(command)
        if explicit.is_file():
            return [str(explicit.resolve())]
        if os.name == "nt":
            native = shutil.which(f"{command}.exe") if not command.lower().endswith(".exe") else None
            if native:
                return [native]
        resolved = shutil.which(command)
        if not resolved:
            raise CodexNotFoundError(
                f"Codex CLI command was not found: {command!r}; install it or set classifier.codex_command"
            )
        if os.name == "nt" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", resolved]
        return [resolved]

    @staticmethod
    def _chatgpt_auth_environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("CODEX_API_KEY", None)
        return environment

    @classmethod
    def _read_final_message(cls, output_path: Path, stdout: str) -> str:
        if output_path.is_file():
            return output_path.read_text(encoding="utf-8-sig")
        for line in reversed(stdout.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    return item["text"]
        raise ClassifierOutputError("Codex CLI did not produce a final classification message")

    @staticmethod
    def _parse_classification(raw: str) -> TaskClassification:
        stripped = raw.strip()
        candidates = [stripped]
        candidates.extend(
            match.group(1).strip()
            for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
        )
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(stripped[first_brace : last_brace + 1])

        errors: list[str] = []
        for candidate in dict.fromkeys(candidates):
            try:
                value = json.loads(candidate)
                if not isinstance(value, dict):
                    raise ValueError("classification root must be a JSON object")
                return TaskClassification.from_dict(value)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(str(exc))
        detail = errors[-1] if errors else "empty output"
        raise ClassifierOutputError(f"invalid Luna classification output: {detail}")

    @staticmethod
    def _parse_batch_classifications(
        raw: str,
        expected_names: Sequence[str],
    ) -> list[TaskClassification]:
        stripped = raw.strip()
        candidates = [stripped]
        candidates.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"```(?:json)?\s*(.*?)\s*```",
                stripped,
                re.DOTALL | re.IGNORECASE,
            )
        )
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(stripped[first_brace : last_brace + 1])

        errors: list[str] = []
        for candidate in dict.fromkeys(candidates):
            try:
                value = json.loads(candidate)
                if not isinstance(value, dict) or set(value) != {"results"}:
                    raise ValueError("batch root must contain only 'results'")
                results = value["results"]
                if not isinstance(results, list):
                    raise ValueError("batch results must be an array")
                if len(results) != len(expected_names):
                    raise ValueError(
                        f"expected {len(expected_names)} results, received {len(results)}"
                    )
                classifications: list[TaskClassification] = []
                for index, (item, expected_name) in enumerate(
                    zip(results, expected_names, strict=True)
                ):
                    if not isinstance(item, dict) or set(item) != {
                        "name",
                        "classification",
                    }:
                        raise ValueError(f"batch result {index} has invalid fields")
                    if item["name"] != expected_name:
                        raise ValueError(
                            f"batch result {index} name mismatch: {item['name']!r}"
                        )
                    classification = item["classification"]
                    if not isinstance(classification, dict):
                        raise ValueError(f"batch result {index} classification must be an object")
                    classifications.append(TaskClassification.from_dict(classification))
                return classifications
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(str(exc))
        detail = errors[-1] if errors else "empty output"
        raise ClassifierOutputError(f"invalid Luna batch classification output: {detail}")

    @staticmethod
    def _usage_from_jsonl(
        stdout: str,
    ) -> tuple[int | None, int | None, int | None]:
        found: tuple[int | None, int | None, int | None] = (None, None, None)

        def visit(value: Any) -> None:
            nonlocal found
            if isinstance(value, dict):
                usage = value.get("usage")
                if isinstance(usage, dict):
                    input_tokens = usage.get("input_tokens")
                    cached_input_tokens = usage.get("cached_input_tokens")
                    output_tokens = usage.get("output_tokens")
                    if (
                        isinstance(input_tokens, int)
                        or isinstance(cached_input_tokens, int)
                        or isinstance(output_tokens, int)
                    ):
                        found = (
                            input_tokens if isinstance(input_tokens, int) else None,
                            cached_input_tokens
                            if isinstance(cached_input_tokens, int)
                            else None,
                            output_tokens if isinstance(output_tokens, int) else None,
                        )
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        for line in stdout.splitlines():
            try:
                visit(json.loads(line))
            except json.JSONDecodeError:
                continue
        return found

    def _set_diagnostics(
        self,
        started: float,
        attempts: int,
        input_tokens: int | None,
        cached_input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        self.last_diagnostics = ClassifierDiagnostics(
            source="codex_cli",
            model_id=self.model_id,
            effort=ReasoningEffort.LOW,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=attempts,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _safe_error_detail(value: str) -> str:
        return " ".join(value.strip().split())[-1000:]
