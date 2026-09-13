"""Optional official SWE-bench harness boundary for Phase 5 real pilots."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from ..router.schemas import ExecutionResult, ValidationResult, ValidationSpec
from .runner import BenchmarkTask


class SWEbenchInfrastructureError(ValueError):
    """Abort the benchmark instead of escalating models for a grader outage."""


BASELINE_MARKER_PATCH = """diff --git a/.adaptive-codex-router-baseline b/.adaptive-codex-router-baseline
new file mode 100644
index 0000000..98c040b
--- /dev/null
+++ b/.adaptive-codex-router-baseline
@@ -0,0 +1 @@
+baseline validation marker
"""


def _instance_digest(instance: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        instance, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SWEbenchValidationAsset:
    task_id: str
    dataset: str
    revision: str
    row_index: int
    asset_sha256: str
    instance: dict[str, Any]

    @property
    def image(self) -> str:
        return str(self.instance["image"])


def load_swebench_assets(path: str | Path) -> dict[str, SWEbenchValidationAsset]:
    asset_path = Path(path).resolve()
    assets: dict[str, SWEbenchValidationAsset] = {}
    for line_number, line in enumerate(
        asset_path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            instance = value["instance"]
            task_id = str(value["id"])
            digest = str(value["asset_sha256"])
            if not isinstance(instance, dict):
                raise ValueError("instance must be an object")
            if instance.get("instance_id") != task_id:
                raise ValueError("asset id does not match instance_id")
            if _instance_digest(instance) != digest:
                raise ValueError("asset SHA-256 does not match its instance")
            if task_id in assets:
                raise ValueError(f"duplicate asset id: {task_id}")
            assets[task_id] = SWEbenchValidationAsset(
                task_id=task_id,
                dataset=str(value["dataset"]),
                revision=str(value["revision"]),
                row_index=int(value["row_index"]),
                asset_sha256=digest,
                instance=dict(instance),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid SWE-bench validation asset line {line_number}: {exc}"
            ) from exc
    if not assets:
        raise ValueError(f"SWE-bench validation asset file is empty: {asset_path}")
    return assets


def validate_task_assets(
    tasks: Sequence[BenchmarkTask],
    assets: Mapping[str, SWEbenchValidationAsset],
) -> None:
    for task in tasks:
        asset = assets.get(task.task_id)
        if asset is None:
            raise ValueError(f"missing sealed validation asset for {task.task_id}")
        expected = task.provenance.get("validation_asset_sha256")
        if expected != asset.asset_sha256:
            raise ValueError(f"validation asset hash mismatch for {task.task_id}")
        if task.provenance.get("validation_backend") != "swebench_container":
            raise ValueError(f"task is not marked for SWE-bench validation: {task.task_id}")
        if task.provenance.get("dataset") != asset.dataset:
            raise ValueError(f"validation dataset mismatch for {task.task_id}")
        if task.provenance.get("revision") != asset.revision:
            raise ValueError(f"validation revision mismatch for {task.task_id}")
        if task.provenance.get("row_index") != asset.row_index:
            raise ValueError(f"validation row index mismatch for {task.task_id}")
        if task.provenance.get("container_image") != asset.image:
            raise ValueError(f"container image mismatch for {task.task_id}")
        if task.base_ref != asset.instance.get("base_commit"):
            raise ValueError(f"base commit mismatch for {task.task_id}")
        if task.provenance.get("source_repo") != asset.instance.get("repo"):
            raise ValueError(f"source repository mismatch for {task.task_id}")
        asset_prompt = asset.instance.get("problem_statement")
        if not isinstance(asset_prompt, str) or task.prompt.strip() != asset_prompt.strip():
            raise ValueError(f"problem statement mismatch for {task.task_id}")


class SWEbenchDockerWorkspace:
    """Extract `/testbed` from the reviewed instance image for Codex execution."""

    def __init__(
        self,
        root: str | Path,
        assets: Mapping[str, SWEbenchValidationAsset],
        *,
        docker_command: str = "docker",
        git_command: str = "git",
        allow_image_pull: bool = False,
        keep: bool = False,
        run_command: Any = subprocess.run,
    ) -> None:
        self.root = Path(root).resolve()
        self.assets = assets
        self.docker_command = docker_command
        self.git_command = git_command
        self.allow_image_pull = allow_image_pull
        self.keep = keep
        self.run_command = run_command

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self.run_command(
                list(args),
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"command timed out: {args[0]}") from exc
        except OSError as exc:
            raise ValueError(f"command could not start: {args[0]}: {exc}") from exc

    @staticmethod
    def _failure(completed: subprocess.CompletedProcess[str]) -> str:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return " ".join(detail.split())[-1000:]

    def prepare(
        self,
        tasks: Sequence[BenchmarkTask],
        *,
        swebench_python: str,
    ) -> None:
        engine = self._run(
            [self.docker_command, "version", "--format", "{{.Server.Version}}"],
            timeout=30,
        )
        if engine.returncode != 0 or not engine.stdout.strip():
            raise ValueError(
                "Docker Linux engine is unavailable"
                + (f": {self._failure(engine)}" if self._failure(engine) else "")
            )
        harness = self._run(
            [swebench_python, "-c", "import swebench; print(swebench.__version__)"],
            timeout=30,
        )
        if harness.returncode != 0:
            raise ValueError(
                "official SWE-bench Python package is unavailable"
                + (f": {self._failure(harness)}" if self._failure(harness) else "")
            )

        images = sorted({self.assets[task.task_id].image for task in tasks})
        missing: list[str] = []
        for image in images:
            inspected = self._run(
                [self.docker_command, "image", "inspect", image], timeout=30
            )
            if inspected.returncode != 0:
                missing.append(image)
        if missing and not self.allow_image_pull:
            raise ValueError(
                f"{len(missing)} SWE-bench image(s) are missing; "
                "pass --allow-image-pull to authorize large downloads"
            )
        for image in missing:
            pulled = self._run([self.docker_command, "pull", image], timeout=None)
            if pulled.returncode != 0:
                raise ValueError(
                    f"failed to pull SWE-bench image {image}: {self._failure(pulled)}"
                )

    def resolve_commit(self, task: BenchmarkTask) -> str:
        return task.base_ref

    @contextmanager
    def materialize(self, task: BenchmarkTask, strategy: str) -> Iterator[Path]:
        asset = self.assets[task.task_id]
        self.root.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in task.task_id
        )[:60]
        target = (self.root / f"{safe_id}-{strategy}-{uuid4().hex[:8]}").resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("generated SWE-bench workspace escaped its configured root")
        container = f"acr-copy-{uuid4().hex[:20]}"
        created = False
        try:
            target.mkdir(parents=True)
            result = self._run(
                [self.docker_command, "create", "--name", container, asset.image],
                timeout=60,
            )
            if result.returncode != 0:
                raise ValueError(
                    f"could not create SWE-bench container: {self._failure(result)}"
                )
            created = True
            copied = self._run(
                [self.docker_command, "cp", f"{container}:/testbed/.", str(target)],
                timeout=300,
            )
            if copied.returncode != 0:
                raise ValueError(
                    f"could not extract /testbed: {self._failure(copied)}"
                )
            inside = self._run(
                [self.git_command, "-C", str(target), "rev-parse", "--is-inside-work-tree"],
                timeout=30,
            )
            ancestor = self._run(
                [
                    self.git_command,
                    "-C",
                    str(target),
                    "merge-base",
                    "--is-ancestor",
                    task.base_ref,
                    "HEAD",
                ],
                timeout=30,
            )
            if inside.returncode != 0 or inside.stdout.strip() != "true":
                raise ValueError("extracted /testbed is not a Git working tree")
            if ancestor.returncode != 0:
                raise ValueError(
                    f"task base commit is not an ancestor of image HEAD: {task.task_id}"
                )
            yield target
        finally:
            if created:
                try:
                    self._run([self.docker_command, "rm", "-f", container], timeout=60)
                except ValueError:
                    pass
            if target.exists() and not self.keep:
                if not target.is_relative_to(self.root):
                    raise ValueError("refusing to remove workspace outside configured root")
                try:
                    shutil.rmtree(target)
                except OSError as exc:
                    # Windows antivirus/overlay locks can briefly hold files in
                    # `.git/objects`. Do not discard an otherwise valid benchmark
                    # result because best-effort cleanup could not finish.
                    print(
                        f"Warning: retained SWE-bench workspace after cleanup failure: {target} ({exc})"
                    )


class SWEbenchHarnessValidator:
    """Grade a workspace patch with the official per-repository log parsers."""

    def __init__(
        self,
        task: BenchmarkTask,
        asset: SWEbenchValidationAsset,
        *,
        evaluation_root: str | Path,
        swebench_python: str,
        git_command: str = "git",
        run_command: Any = subprocess.run,
    ) -> None:
        self.task = task
        self.asset = asset
        self.evaluation_root = Path(evaluation_root).resolve()
        self.swebench_python = swebench_python
        self.git_command = git_command
        self.run_command = run_command

    def _git(self, args: Sequence[str], workspace: Path) -> subprocess.CompletedProcess[str]:
        try:
            return self.run_command(
                [self.git_command, "-C", str(workspace), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Git timed out while preparing the SWE-bench patch") from exc
        except OSError as exc:
            raise ValueError(f"Git could not start while preparing the patch: {exc}") from exc

    def _workspace_patch(self, workspace: Path) -> str:
        staged = self._git(["add", "-A"], workspace)
        if staged.returncode != 0:
            raise ValueError("could not stage workspace changes for SWE-bench grading")
        # Codex may commit its changes. Compare against the pinned task base,
        # rather than HEAD, so both committed and working-tree changes are sent
        # to the official harness.
        diff = self._git(["diff", "--binary", self.task.base_ref], workspace)
        if diff.returncode != 0:
            raise ValueError("could not capture workspace patch for SWE-bench grading")
        if not diff.stdout.strip():
            raise ValueError("workspace produced an empty patch")
        return diff.stdout

    @staticmethod
    def _resolved_from_reports(
        run_directory: Path, task_id: str, *, require_valid_baseline: bool = False,
    ) -> bool | None:
        for report_path in run_directory.rglob("report.json"):
            try:
                value = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            task_report = value.get(task_id) if isinstance(value, dict) else None
            if isinstance(task_report, dict) and isinstance(task_report.get("resolved"), bool):
                if task_report.get("infra_failure"):
                    raise SWEbenchInfrastructureError(
                        f"official SWE-bench report flags infrastructure failure: {report_path}"
                    )
                if require_valid_baseline:
                    tests = task_report.get("tests_status") or {}
                    f2p = tests.get("FAIL_TO_PASS") or {}
                    if (
                        task_report.get("patch_successfully_applied") is not True
                        or not f2p.get("failure")
                    ):
                        raise SWEbenchInfrastructureError(
                            f"baseline requires executed failing target tests: {report_path}"
                        )
                return task_report["resolved"]
        return None

    def evaluate_patch(
        self,
        patch: str,
        *,
        timeout_seconds: float,
        label: str,
    ) -> tuple[bool, int, int]:
        run_id = f"acr-{label}-{uuid4().hex[:12]}"
        run_directory = (self.evaluation_root / run_id).resolve()
        if not run_directory.is_relative_to(self.evaluation_root):
            raise ValueError("generated SWE-bench evaluation directory escaped its root")
        run_directory.mkdir(parents=True, exist_ok=False)
        dataset_path = run_directory / "instance.json"
        predictions_path = run_directory / "prediction.jsonl"
        dataset_path.write_text(
            json.dumps([self.asset.instance], ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        predictions_path.write_text(
            json.dumps(
                {
                    "instance_id": self.task.task_id,
                    "model_name_or_path": "adaptive-codex-router",
                    "model_patch": patch,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        command = [
            self.swebench_python,
            "-X",
            "utf8",
            "-m",
            "adaptive_codex_router.benchmark.swebench_entry",
            "--dataset_name",
            str(dataset_path),
            "--split",
            "test",
            "--predictions_path",
            str(predictions_path),
            "--max_workers",
            "1",
            "--run_id",
            run_id,
            "--instance_ids",
            self.task.task_id,
            "--timeout",
            str(max(1, int(timeout_seconds))),
        ]
        started = perf_counter()
        try:
            completed = self.run_command(
                command,
                cwd=str(run_directory),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds + 120,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SWEbenchInfrastructureError(
                f"official SWE-bench harness timed out after {timeout_seconds + 120:g}s"
            ) from exc
        except OSError as exc:
            raise SWEbenchInfrastructureError(f"official SWE-bench harness could not start: {exc}") from exc
        duration_ms = max(0, int((perf_counter() - started) * 1000))
        resolved = self._resolved_from_reports(
            run_directory, self.task.task_id, require_valid_baseline=label == "baseline",
        )
        if resolved is None:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise SWEbenchInfrastructureError(
                "official SWE-bench harness produced no task report"
                + (f": {' '.join(detail.split())[-1000:]}" if detail else "")
            )
        return resolved, completed.returncode, duration_ms

    def validate(
        self,
        execution: ExecutionResult,
        spec: ValidationSpec | None = None,
        working_directory: str | Path | None = None,
    ) -> ValidationResult:
        spec = spec or ValidationSpec()
        failures: list[str] = []
        if not execution.success:
            failures.append("executor reported failure")
        if execution.exit_code != 0:
            failures.append(f"non-zero exit code: {execution.exit_code}")
        if spec.required_output and spec.required_output not in execution.output:
            failures.append("required output is missing")
        if spec.require_changed_files and not execution.changed_files:
            failures.append("required files were unchanged")
        if failures:
            return ValidationResult(success=False, failures=tuple(failures))
        if working_directory is None:
            return ValidationResult(
                success=False,
                failures=("SWE-bench validation requires a working directory",),
            )
        try:
            patch = self._workspace_patch(Path(working_directory).resolve())
            resolved, exit_code, duration_ms = self.evaluate_patch(
                patch,
                timeout_seconds=spec.timeout_seconds,
                label="attempt",
            )
        except SWEbenchInfrastructureError:
            raise
        except ValueError as exc:
            return ValidationResult(success=False, failures=(str(exc),))
        return ValidationResult(
            success=resolved,
            failures=() if resolved else ("official SWE-bench report: unresolved",),
            command_exit_code=exit_code,
            command_duration_ms=duration_ms,
        )


def validate_swebench_baseline(
    task: BenchmarkTask,
    validator: SWEbenchHarnessValidator,
    *,
    timeout_seconds: float,
) -> None:
    resolved, _, _ = validator.evaluate_patch(
        BASELINE_MARKER_PATCH,
        timeout_seconds=timeout_seconds,
        label="baseline",
    )
    if resolved:
        raise ValueError(
            f"SWE-bench baseline already resolves {task.task_id}; task cannot measure improvement"
        )
