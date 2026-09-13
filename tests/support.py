from __future__ import annotations

import sys
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def ensure_fixture_repository() -> None:
    """Create the tiny Git fixture when a clone omits its local metadata."""
    fixture = ROOT / "benchmarks" / "fixtures" / "phase4_repo"
    if not fixture.is_dir() or (fixture / ".git").exists():
        return
    subprocess.run(["git", "init", "--quiet"], cwd=fixture, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=fixture, check=True)
    subprocess.run(["git", "config", "user.name", "Router Tests"], cwd=fixture, check=True)
    subprocess.run(["git", "add", "-A"], cwd=fixture, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=fixture, check=True)


ensure_fixture_repository()

from adaptive_codex_router.config import AppConfig, TelemetryConfig


def test_config(telemetry_path: Path) -> AppConfig:
    config = AppConfig.load(ROOT / "config.yaml")
    return replace(
        config,
        classifier=replace(config.classifier, mode="mock"),
        planning=replace(config.planning, default_provider="none"),
        executor=replace(config.executor, mode="mock"),
        telemetry=TelemetryConfig(path=telemetry_path, log_prompts=False),
    )


def runtime_path() -> Path:
    return ROOT / "tests" / "fixtures" / f"history-{uuid4().hex}.jsonl"
