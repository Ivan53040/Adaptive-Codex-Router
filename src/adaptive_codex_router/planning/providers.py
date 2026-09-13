"""Built-in local, Codex, mock, and no-planning providers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from ..config import AppConfig
from ..router.classifier import MockLunaClassifier, TaskClassifier
from ..router.codex_classifier import CodexNotFoundError, LunaCodexClassifier
from ..router.schemas import (
    ModelName,
    PlanningDiagnostics,
    PlanningResult,
    ProviderStatus,
    ReasoningEffort,
    TaskClassification,
    TaskMetadata,
)
from .context import build_workspace_context
from .prompts import build_planning_prompt
from .types import PlannerOutputError, PlannerUnavailableError

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
HttpRequester = Callable[[urllib.request.Request, float], bytes]


def _planning_from_text(raw: str, *, planner: str) -> PlanningResult:
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
            if not isinstance(value, dict):
                raise ValueError("planning result root must be a JSON object")
            return PlanningResult.from_dict(value, planner=planner)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
    detail = errors[-1] if errors else "empty output"
    raise PlannerOutputError(f"invalid {planner} planning output: {detail}")


def _mock_result(classification: TaskClassification, *, planner: str) -> PlanningResult:
    return PlanningResult.from_classification(
        classification,
        planner=planner,
        relevant_files=(),
        implementation_plan=("Inspect the affected code and constraints.", "Apply the requested change."),
        verification_steps=("Run the most relevant automated checks.",),
        risks=(),
    )


class _MockPlanner:
    name = "mock"

    def __init__(
        self,
        *,
        status: ProviderStatus = ProviderStatus.ONLINE,
        fail: bool = False,
    ) -> None:
        self._status = status
        self._fail = fail
        self._classifier = MockLunaClassifier()
        self.last_diagnostics: PlanningDiagnostics | None = None

    def status(self) -> ProviderStatus:
        return self._status

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        del workspace
        started = perf_counter()
        if self._fail or self._status is ProviderStatus.OFFLINE:
            raise PlannerUnavailableError(f"{self.name} planner is unavailable")
        classification = self._classifier.classify(prompt, metadata)
        self.last_diagnostics = PlanningDiagnostics(
            source="mock",
            model_id=self.name,
            effort=ReasoningEffort.LOW,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=1,
            provider=self.name,
            status=self._status,
            local_inference=self.name == "qwen",
        )
        return _mock_result(classification, planner=self.name)


class MockQwenPlanner(_MockPlanner):
    name = "qwen"


class MockLunaPlanner(_MockPlanner):
    name = "luna"


class NoPlanningProvider(_MockPlanner):
    """Deterministic classification only; performs no external planning call."""

    name = "none"

    def __init__(self) -> None:
        super().__init__(status=ProviderStatus.ONLINE)

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        del workspace
        started = perf_counter()
        classification = self._classifier.classify(prompt, metadata)
        self.last_diagnostics = PlanningDiagnostics(
            source="deterministic",
            model_id="none",
            effort=ReasoningEffort.LOW,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=1,
            provider=self.name,
            status=ProviderStatus.ONLINE,
        )
        return PlanningResult.from_classification(classification, planner=self.name)


class ClassifierPlanningAdapter:
    """Compatibility bridge for Phase 2 evaluators that inject a classifier."""

    name = "classifier_adapter"

    def __init__(self, classifier: TaskClassifier) -> None:
        self.classifier = classifier
        self.last_diagnostics: PlanningDiagnostics | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus.ONLINE

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        del workspace
        classification = self.classifier.classify(prompt, metadata)
        diagnostics = self.classifier.last_diagnostics
        self.last_diagnostics = (
            replace(
                diagnostics,
                provider=diagnostics.provider or self.name,
                status=ProviderStatus.ONLINE,
            )
            if diagnostics
            else None
        )
        return _mock_result(classification, planner=self.name)


def _default_http_request(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


class QwenLocalPlanner:
    name = "qwen"

    def __init__(
        self,
        config: AppConfig,
        *,
        requester: HttpRequester = _default_http_request,
        schema_path: str | Path | None = None,
    ) -> None:
        self.settings = config.planning
        self.base_url = self.settings.qwen_base_url.rstrip("/")
        self.model_id = self.settings.qwen_model
        self.requester = requester
        self.schema_path = Path(schema_path) if schema_path else Path(__file__).with_name(
            "planning.schema.json"
        )
        self.last_diagnostics: PlanningDiagnostics | None = None
        self._last_status = ProviderStatus.UNKNOWN

    def status(self) -> ProviderStatus:
        try:
            health = self._request_json("/health", method="GET", timeout=5.0)
            if health.get("status") != "ok":
                self._last_status = ProviderStatus.DEGRADED
                return self._last_status
            models = self._request_json("/v1/models", method="GET", timeout=5.0)
            identifiers = {
                item.get("id") or item.get("model") or item.get("name")
                for key in ("data", "models")
                for item in models.get(key, [])
                if isinstance(item, dict)
            }
            self._last_status = (
                ProviderStatus.ONLINE
                if self.model_id in identifiers
                else ProviderStatus.DEGRADED
            )
        except (OSError, ValueError, urllib.error.URLError):
            self._last_status = ProviderStatus.OFFLINE
        return self._last_status

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        metadata = metadata or TaskMetadata()
        started = perf_counter()
        context = build_workspace_context(
            workspace,
            prompt,
            max_chars=self.settings.qwen_max_context_chars,
        )
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        last_error: PlannerOutputError | None = None
        total_attempts = self.settings.max_malformed_retries + 1
        for attempt in range(1, total_attempts + 1):
            request_body = {
                "model": self.model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": build_planning_prompt(
                            prompt,
                            metadata,
                            workspace_context=context,
                            retry=attempt > 1,
                        ),
                    }
                ],
                "temperature": 0.0 if attempt > 1 else 0.2,
                "max_tokens": self.settings.qwen_max_tokens,
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "reasoning_effort": self.settings.qwen_reasoning_effort,
                },
            }
            # Some llama.cpp builds advertise json_schema support but still emit
            # malformed constrained output. The retry keeps the strict prompt
            # contract while letting the model produce ordinary JSON.
            if attempt == 1:
                request_body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "planning_result",
                        "strict": True,
                        "schema": schema,
                    },
                }
            try:
                response = self._request_json(
                    "/v1/chat/completions",
                    method="POST",
                    payload=request_body,
                    timeout=self.settings.qwen_timeout_seconds,
                )
            except (OSError, ValueError, urllib.error.URLError) as exc:
                self._last_status = ProviderStatus.OFFLINE
                self._set_diagnostics(started, attempt, None, ProviderStatus.OFFLINE)
                raise PlannerUnavailableError(f"Qwen planner request failed: {exc}") from exc

            usage = response.get("usage", {})
            try:
                message = response["choices"][0]["message"]
                content = message.get("content") or ""
                reasoning_content = message.get("reasoning_content") or ""
                candidates: list[str] = []
                for value in (content, reasoning_content):
                    if isinstance(value, str) and value.strip():
                        candidates.append(value)
                    elif isinstance(value, list):
                        text = "".join(
                            item.get("text", "")
                            for item in value
                            if isinstance(item, dict) and isinstance(item.get("text"), str)
                        )
                        if text.strip():
                            candidates.append(text)
                if not candidates:
                    raise PlannerOutputError("Qwen response contained no text content")
                parse_errors: list[str] = []
                result = None
                for candidate in candidates:
                    try:
                        result = _planning_from_text(candidate, planner=self.name)
                        break
                    except PlannerOutputError as exc:
                        parse_errors.append(str(exc))
                if result is None:
                    raise PlannerOutputError(parse_errors[-1] or "invalid Qwen output")
            except (KeyError, IndexError, TypeError, PlannerOutputError) as exc:
                last_error = (
                    exc
                    if isinstance(exc, PlannerOutputError)
                    else PlannerOutputError(f"invalid Qwen response envelope: {exc}")
                )
                if attempt < total_attempts:
                    continue
                self._last_status = ProviderStatus.DEGRADED
                self._set_diagnostics(started, attempt, usage, ProviderStatus.DEGRADED)
                raise last_error

            self._last_status = ProviderStatus.ONLINE
            self._set_diagnostics(started, attempt, usage, ProviderStatus.ONLINE)
            return result
        raise last_error or PlannerOutputError("Qwen returned no planning result")

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        timeout: float,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "User-Agent": "adaptive-codex-router"},
        )
        value = json.loads(self.requester(request, timeout).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("server response must be a JSON object")
        return value

    def _set_diagnostics(
        self,
        started: float,
        attempts: int,
        usage: dict[str, Any] | None,
        status: ProviderStatus,
    ) -> None:
        usage = usage or {}
        prompt_details = usage.get("prompt_tokens_details", {})
        self.last_diagnostics = PlanningDiagnostics(
            source="llama_server",
            model_id=self.model_id,
            effort=ReasoningEffort.HIGH,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=attempts,
            input_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
            cached_input_tokens=(
                prompt_details.get("cached_tokens")
                if isinstance(prompt_details, dict)
                and isinstance(prompt_details.get("cached_tokens"), int)
                else None
            ),
            output_tokens=(
                usage.get("completion_tokens")
                if isinstance(usage.get("completion_tokens"), int)
                else None
            ),
            provider=self.name,
            status=status,
            local_inference=True,
        )


class LunaCodexPlanner:
    name = "luna"

    def __init__(
        self,
        config: AppConfig,
        *,
        runner: ProcessRunner = subprocess.run,
        schema_path: str | Path | None = None,
    ) -> None:
        self.settings = config.planning
        self.model_id = config.model(ModelName.LUNA).model_id
        self.runner = runner
        self.schema_path = Path(schema_path) if schema_path else Path(__file__).with_name(
            "planning.schema.json"
        )
        self.output_directory = self.settings.working_directory
        self.last_diagnostics: PlanningDiagnostics | None = None
        self._last_status = ProviderStatus.UNKNOWN

    def status(self) -> ProviderStatus:
        try:
            LunaCodexClassifier._resolve_command(self.settings.luna_codex_command)
        except (CodexNotFoundError, OSError):
            self._last_status = ProviderStatus.OFFLINE
        else:
            self._last_status = (
                ProviderStatus.ONLINE
                if self._last_status is ProviderStatus.ONLINE
                else ProviderStatus.UNKNOWN
            )
        return self._last_status

    def plan(
        self,
        prompt: str,
        workspace: str | Path,
        metadata: TaskMetadata | None = None,
    ) -> PlanningResult:
        metadata = metadata or TaskMetadata()
        target = Path(workspace).resolve()
        if not target.is_dir():
            raise PlannerUnavailableError(f"planning workspace does not exist: {target}")
        try:
            command_prefix = LunaCodexClassifier._resolve_command(
                self.settings.luna_codex_command
            )
        except (CodexNotFoundError, OSError) as exc:
            raise PlannerUnavailableError(f"Luna planner is unavailable: {exc}") from exc
        started = perf_counter()
        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PlannerUnavailableError(
                f"Luna planner output directory is unavailable: {exc}"
            ) from exc
        total_attempts = self.settings.max_malformed_retries + 1
        last_error: PlannerOutputError | None = None
        for attempt in range(1, total_attempts + 1):
            output_path = self.output_directory / f".planner-output-{uuid4().hex}.json"
            command = self._build_command(
                command_prefix,
                target,
                self.schema_path.resolve(),
                output_path,
            )
            try:
                completed = self.runner(
                    command,
                    input=build_planning_prompt(prompt, metadata, retry=attempt > 1),
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.settings.luna_timeout_seconds,
                    cwd=str(target),
                    env=LunaCodexClassifier._chatgpt_auth_environment(),
                    check=False,
                )
                usage = LunaCodexClassifier._usage_from_jsonl(completed.stdout)
                if completed.returncode != 0:
                    self._last_status = ProviderStatus.DEGRADED
                    self._set_diagnostics(started, attempt, usage, ProviderStatus.DEGRADED)
                    detail = LunaCodexClassifier._safe_error_detail(
                        completed.stderr or completed.stdout
                    )
                    raise PlannerUnavailableError(
                        f"Luna planner failed with exit code {completed.returncode}"
                        + (f": {detail}" if detail else "")
                    )
                try:
                    raw = LunaCodexClassifier._read_final_message(
                        output_path, completed.stdout
                    )
                    result = _planning_from_text(raw, planner=self.name)
                except (RuntimeError, PlannerOutputError) as exc:
                    last_error = (
                        exc
                        if isinstance(exc, PlannerOutputError)
                        else PlannerOutputError(str(exc))
                    )
                    if attempt < total_attempts:
                        continue
                    self._last_status = ProviderStatus.DEGRADED
                    self._set_diagnostics(started, attempt, usage, ProviderStatus.DEGRADED)
                    raise last_error

                self._last_status = ProviderStatus.ONLINE
                self._set_diagnostics(started, attempt, usage, ProviderStatus.ONLINE)
                return result
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._last_status = ProviderStatus.OFFLINE
                self._set_diagnostics(started, attempt, None, ProviderStatus.OFFLINE)
                raise PlannerUnavailableError(f"Luna planner request failed: {exc}") from exc
            finally:
                output_path.unlink(missing_ok=True)
        raise last_error or PlannerOutputError("Luna returned no planning result")

    def _build_command(
        self,
        prefix: Sequence[str],
        workspace: Path,
        schema: Path,
        output_path: Path,
    ) -> list[str]:
        return [
            *prefix,
            "--ask-for-approval",
            "never",
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

    def _set_diagnostics(
        self,
        started: float,
        attempts: int,
        usage: tuple[int | None, int | None, int | None] | None,
        status: ProviderStatus,
    ) -> None:
        input_tokens, cached_input_tokens, output_tokens = usage or (None, None, None)
        self.last_diagnostics = PlanningDiagnostics(
            source="codex_cli",
            model_id=self.model_id,
            effort=ReasoningEffort.LOW,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            attempts=attempts,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            provider=self.name,
            status=status,
        )
