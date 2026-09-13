"""Configuration loader for the dependency-free router."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .router.schemas import ModelName, ReasoningEffort


@dataclass(frozen=True)
class ModelConfig:
    name: ModelName
    model_id: str
    model_class: str
    efforts: frozenset[ReasoningEffort]
    available: bool = True


@dataclass(frozen=True)
class AstraGuardrails:
    xhigh_escalation_only: bool = True
    max_automatic: bool = False
    max_require_previous_failure: bool = True
    max_require_high_task_value: bool = True
    max_require_explicit_permission: bool = True


@dataclass(frozen=True)
class TelemetryConfig:
    path: Path
    log_prompts: bool = False


@dataclass(frozen=True)
class ClassifierConfig:
    mode: str = "codex"
    codex_command: str = "codex"
    timeout_seconds: float = 45.0
    batch_timeout_seconds: float = 120.0
    max_malformed_retries: int = 1
    working_directory: Path = Path("data/classifier_workspace")


@dataclass(frozen=True)
class PlanningConfig:
    default_provider: str = "qwen"
    qwen_base_url: str = "http://127.0.0.1:8080"
    qwen_model: str = "qwen3.8-27b"
    qwen_timeout_seconds: float = 300.0
    qwen_max_tokens: int = 8192
    qwen_max_context_chars: int = 240_000
    qwen_reasoning_effort: str = "high"
    luna_codex_command: str = "codex"
    luna_timeout_seconds: float = 120.0
    max_malformed_retries: int = 1
    working_directory: Path = Path("data/planner_workspace")


@dataclass(frozen=True)
class ExecutorConfig:
    mode: str = "codex"
    codex_command: str = "codex"
    timeout_seconds: float = 900.0
    cancel_grace_seconds: float = 3.0
    sandbox: str = "workspace-write"
    approval_policy: str = "auto-review"
    require_git_repository: bool = True
    output_directory: Path = Path("data/executor_workspace")


@dataclass(frozen=True)
class AppConfig:
    reliability_threshold: float
    max_attempts: int
    classifier: ClassifierConfig
    planning: PlanningConfig
    executor: ExecutorConfig
    models: dict[ModelName, ModelConfig]
    astra: AstraGuardrails
    telemetry: TelemetryConfig

    def model(self, name: ModelName) -> ModelConfig:
        try:
            return self.models[name]
        except KeyError as exc:
            raise ValueError(f"missing model configuration: {name.value}") from exc

    def with_model_availability(self, name: ModelName, available: bool) -> "AppConfig":
        models = dict(self.models)
        models[name] = replace(self.model(name), available=available)
        return replace(self, models=models)

    def with_classifier_mode(self, mode: str) -> "AppConfig":
        return replace(self, classifier=replace(self.classifier, mode=mode))

    def with_planner_mode(self, mode: str) -> "AppConfig":
        return replace(self, planning=replace(self.planning, default_provider=mode))

    def with_executor_mode(self, mode: str) -> "AppConfig":
        return replace(self, executor=replace(self.executor, mode=mode))

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        config_path = Path(path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        models: dict[ModelName, ModelConfig] = {}
        for key, value in raw["models"].items():
            name = ModelName(key)
            models[name] = ModelConfig(
                name=name,
                model_id=value["model"],
                model_class=value["class"],
                efforts=frozenset(ReasoningEffort(item) for item in value["efforts"]),
                available=bool(value.get("available", True)),
            )

        astra = raw.get("astra", {})
        classifier = raw.get("classifier", {})
        planning = raw.get("planning", {})
        qwen_planning = planning.get("qwen", {})
        luna_planning = planning.get("luna", {})
        executor = raw.get("executor", {})
        telemetry = raw.get("telemetry", {})
        telemetry_path = Path(telemetry.get("path", "data/routing_history.jsonl"))
        if not telemetry_path.is_absolute():
            telemetry_path = config_path.resolve().parent / telemetry_path
        classifier_working_directory = Path(
            classifier.get("working_directory", "data/classifier_workspace")
        )
        if not classifier_working_directory.is_absolute():
            classifier_working_directory = (
                config_path.resolve().parent / classifier_working_directory
            )
        planning_working_directory = Path(
            planning.get("working_directory", "data/planner_workspace")
        )
        if not planning_working_directory.is_absolute():
            planning_working_directory = (
                config_path.resolve().parent / planning_working_directory
            )
        executor_output_directory = Path(
            executor.get("output_directory", "data/executor_workspace")
        )
        if not executor_output_directory.is_absolute():
            executor_output_directory = config_path.resolve().parent / executor_output_directory

        config = cls(
            reliability_threshold=float(raw.get("reliability_threshold", 0.92)),
            max_attempts=int(raw.get("max_attempts", 3)),
            classifier=ClassifierConfig(
                mode=str(classifier.get("mode", "codex")),
                codex_command=str(classifier.get("codex_command", "codex")),
                timeout_seconds=float(classifier.get("timeout_seconds", 45)),
                batch_timeout_seconds=float(
                    classifier.get("batch_timeout_seconds", 120)
                ),
                max_malformed_retries=int(classifier.get("max_malformed_retries", 1)),
                working_directory=classifier_working_directory,
            ),
            planning=PlanningConfig(
                default_provider=str(planning.get("default_provider", "qwen")),
                qwen_base_url=str(
                    qwen_planning.get("base_url", "http://127.0.0.1:8080")
                ),
                qwen_model=str(qwen_planning.get("model", "qwen3.8-27b")),
                qwen_timeout_seconds=float(qwen_planning.get("timeout_seconds", 300)),
                qwen_max_tokens=int(qwen_planning.get("max_tokens", 8192)),
                qwen_max_context_chars=int(
                    qwen_planning.get("max_context_chars", 240_000)
                ),
                qwen_reasoning_effort=str(
                    qwen_planning.get("reasoning_effort", "high")
                ),
                luna_codex_command=str(
                    luna_planning.get(
                        "codex_command", classifier.get("codex_command", "codex")
                    )
                ),
                luna_timeout_seconds=float(
                    luna_planning.get("timeout_seconds", 120)
                ),
                max_malformed_retries=int(
                    planning.get(
                        "max_malformed_retries",
                        classifier.get("max_malformed_retries", 1),
                    )
                ),
                working_directory=planning_working_directory,
            ),
            executor=ExecutorConfig(
                mode=str(executor.get("mode", "codex")),
                codex_command=str(executor.get("codex_command", "codex")),
                timeout_seconds=float(executor.get("timeout_seconds", 900)),
                cancel_grace_seconds=float(executor.get("cancel_grace_seconds", 3)),
                sandbox=str(executor.get("sandbox", "workspace-write")),
                approval_policy=str(executor.get("approval_policy", "auto-review")),
                require_git_repository=bool(
                    executor.get("require_git_repository", True)
                ),
                output_directory=executor_output_directory,
            ),
            models=models,
            astra=AstraGuardrails(**astra),
            telemetry=TelemetryConfig(
                path=telemetry_path,
                log_prompts=bool(telemetry.get("log_prompts", False)),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 0 < self.reliability_threshold <= 1:
            raise ValueError("reliability_threshold must be between 0 and 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.classifier.mode not in {"codex", "mock"}:
            raise ValueError("classifier.mode must be 'codex' or 'mock'")
        if self.classifier.timeout_seconds <= 0:
            raise ValueError("classifier.timeout_seconds must be positive")
        if self.classifier.batch_timeout_seconds <= 0:
            raise ValueError("classifier.batch_timeout_seconds must be positive")
        if self.classifier.max_malformed_retries < 0:
            raise ValueError("classifier.max_malformed_retries cannot be negative")
        if self.planning.default_provider not in {"qwen", "luna", "auto", "none"}:
            raise ValueError("planning.default_provider must be qwen, luna, auto, or none")
        if not self.planning.qwen_base_url.startswith(("http://", "https://")):
            raise ValueError("planning.qwen.base_url must be an HTTP(S) URL")
        if not self.planning.qwen_model:
            raise ValueError("planning.qwen.model cannot be empty")
        if self.planning.qwen_timeout_seconds <= 0:
            raise ValueError("planning.qwen.timeout_seconds must be positive")
        if self.planning.qwen_max_tokens < 1:
            raise ValueError("planning.qwen.max_tokens must be positive")
        if self.planning.qwen_max_context_chars < 0:
            raise ValueError("planning.qwen.max_context_chars cannot be negative")
        if self.planning.qwen_reasoning_effort != "high":
            raise ValueError("planning.qwen.reasoning_effort must be 'high'")
        if self.planning.luna_timeout_seconds <= 0:
            raise ValueError("planning.luna.timeout_seconds must be positive")
        if self.planning.max_malformed_retries < 0:
            raise ValueError("planning.max_malformed_retries cannot be negative")
        if self.executor.mode not in {"codex", "mock"}:
            raise ValueError("executor.mode must be 'codex' or 'mock'")
        if self.executor.timeout_seconds <= 0:
            raise ValueError("executor.timeout_seconds must be positive")
        if self.executor.cancel_grace_seconds < 0:
            raise ValueError("executor.cancel_grace_seconds cannot be negative")
        if self.executor.sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("executor.sandbox must be 'read-only' or 'workspace-write'")
        if self.executor.approval_policy not in {
            "auto-review",
            "never",
            "on-request",
        }:
            raise ValueError(
                "executor.approval_policy must be 'auto-review', 'never', or 'on-request'"
            )
        missing = set(ModelName) - set(self.models)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"missing model configuration: {names}")
