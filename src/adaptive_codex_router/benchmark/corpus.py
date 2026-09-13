"""Import and audit real Phase 5 benchmark corpus candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .phase5 import PHASE5_CATEGORIES


SWEBENCH_DATASET = "SWE-bench/SWE-bench_Verified"
SWEBENCH_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
SWEBENCH_CONFIG = "default"
SWEBENCH_SPLIT = "test"
HF_API_ROOT = "https://huggingface.co/api/datasets"
HF_ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SOURCE_FIELDS = {"patch", "test_patch", "hints_text", "eval_script"}
SEALED_VALIDATION_FIELDS = (
    "base_commit",
    "created_at",
    "difficulty",
    "environment_setup_commit",
    "eval_type",
    "image",
    "instance_id",
    "log_parser",
    "repo",
    "version",
    "test_patch",
    "eval_script",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
)

JsonFetcher = Callable[[str, float], dict[str, Any]]


def _fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "adaptive-codex-router/0.5.3"})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object from {url}")
    return payload


def _dataset_info_url(dataset: str) -> str:
    owner, name = dataset.split("/", 1)
    return f"{HF_API_ROOT}/{owner}/{name}"


def fetch_swebench_rows(
    *,
    limit: int,
    offset: int = 0,
    dataset: str = SWEBENCH_DATASET,
    revision: str = SWEBENCH_REVISION,
    timeout_seconds: float = 60,
    fetch_json: JsonFetcher = _fetch_json,
) -> list[tuple[int, dict[str, Any]]]:
    """Fetch a bounded slice while detecting a moving Hub revision."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must not be negative")
    if not FULL_SHA.fullmatch(revision):
        raise ValueError("source revision must be a full 40-character commit SHA")

    before = fetch_json(_dataset_info_url(dataset), timeout_seconds).get("sha")
    if before != revision:
        raise ValueError(
            f"Hub revision changed for {dataset}: expected {revision}, found {before}; "
            "review the new dataset before updating --source-revision"
        )

    selected: list[tuple[int, dict[str, Any]]] = []
    cursor = offset
    while len(selected) < limit:
        page_length = min(100, limit - len(selected))
        query = urlencode(
            {
                "dataset": dataset,
                "config": SWEBENCH_CONFIG,
                "split": SWEBENCH_SPLIT,
                "offset": cursor,
                "length": page_length,
            }
        )
        payload = fetch_json(f"{HF_ROWS_ENDPOINT}?{query}", timeout_seconds)
        if payload.get("partial"):
            raise ValueError("Hugging Face returned a partial dataset slice")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Hugging Face rows response is missing rows")
        if not rows:
            break
        for wrapper in rows:
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("row"), dict):
                raise ValueError("Hugging Face returned a malformed row")
            if wrapper.get("truncated_cells"):
                raise ValueError(
                    f"source row {wrapper.get('row_idx', cursor)} contains truncated cells"
                )
            row_index = wrapper.get("row_idx")
            if not isinstance(row_index, int):
                raise ValueError("Hugging Face row is missing an integer row_idx")
            selected.append((row_index, wrapper["row"]))
        cursor += len(rows)
        total = payload.get("num_rows_total")
        if isinstance(total, int) and cursor >= total:
            break

    after = fetch_json(_dataset_info_url(dataset), timeout_seconds).get("sha")
    if after != before:
        raise ValueError(
            f"Hub revision changed during import for {dataset}: {before} -> {after}"
        )
    if len(selected) != limit:
        raise ValueError(f"requested {limit} rows from offset {offset}, received {len(selected)}")
    return selected


def select_balanced_swebench_rows(
    rows: Sequence[tuple[int, dict[str, Any]]],
    *,
    limit: int,
) -> list[tuple[int, dict[str, Any]]]:
    """Select deterministically across repository and source difficulty buckets."""
    if limit < 1:
        raise ValueError("selection limit must be at least 1")
    if limit > len(rows):
        raise ValueError(f"cannot select {limit} tasks from {len(rows)} source rows")

    buckets: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    for row_index, row in rows:
        repo = _required_string(row, "repo")
        difficulty = str(row.get("difficulty") or "unknown")
        buckets.setdefault((repo, difficulty), []).append((row_index, row))
    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: hashlib.sha256(
                _required_string(item[1], "instance_id").encode("utf-8")
            ).hexdigest()
        )

    selected: list[tuple[int, dict[str, Any]]] = []
    bucket_keys = sorted(buckets)
    cursor = 0
    while len(selected) < limit:
        progress = False
        for key in bucket_keys:
            bucket = buckets[key]
            if cursor < len(bucket):
                selected.append(bucket[cursor])
                progress = True
                if len(selected) == limit:
                    break
        if not progress:
            raise ValueError("balanced selection exhausted before reaching requested limit")
        cursor += 1
    return selected


def _required_string(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source field {field} must be a non-empty string")
    return value.strip()


def _string_array(row: dict[str, Any], field: str) -> list[str]:
    value = row.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"source field {field} must be an array of strings")
    return value


def build_swebench_validation_asset(
    row_index: int,
    row: dict[str, Any],
    *,
    dataset: str = SWEBENCH_DATASET,
    revision: str = SWEBENCH_REVISION,
) -> dict[str, Any]:
    """Build a sealed official-harness input that is never placed in a task workspace."""
    instance = {field: row.get(field) for field in SEALED_VALIDATION_FIELDS}
    instance["patch"] = ""
    canonical = json.dumps(
        instance, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "id": _required_string(row, "instance_id"),
        "dataset": dataset,
        "revision": revision,
        "row_index": row_index,
        "asset_sha256": hashlib.sha256(canonical).hexdigest(),
        "instance": instance,
    }


def normalize_swebench_row(
    row_index: int,
    row: dict[str, Any],
    *,
    output_path: Path,
    repository_root: Path,
    dataset: str = SWEBENCH_DATASET,
    revision: str = SWEBENCH_REVISION,
    validation_asset_sha256: str | None = None,
) -> dict[str, Any]:
    """Convert a source row without exposing its gold solution to the router."""
    task_id = _required_string(row, "instance_id")
    source_repo = _required_string(row, "repo")
    base_commit = _required_string(row, "base_commit").lower()
    if not FULL_SHA.fullmatch(base_commit):
        raise ValueError(f"{task_id}: base_commit is not a full Git SHA")
    prompt = _required_string(row, "problem_statement")
    image = _required_string(row, "image")
    eval_script = _required_string(row, "eval_script")
    fail_to_pass = _string_array(row, "FAIL_TO_PASS")
    pass_to_pass = _string_array(row, "PASS_TO_PASS")

    repo_slug = source_repo.replace("/", "__")
    local_repo = (repository_root.resolve() / repo_slug).resolve()
    relative_repo = os.path.relpath(local_repo, output_path.parent.resolve())

    return {
        "id": task_id,
        "prompt": prompt,
        "repository": Path(relative_repo).as_posix(),
        "base_ref": base_commit,
        "category": "uncategorized",
        "metadata": {
            "files_explicitly_mentioned": 0,
            "tests_requested": True,
            "repository_wide": False,
            "estimated_repo_size": "unknown",
            "number_of_expected_steps": 1,
            "cross_module_dependency": False,
        },
        "validation": {
            "require_changed_files": True,
            "command": [],
            "timeout_seconds": 120,
        },
        "provenance": {
            "dataset": dataset,
            "revision": revision,
            "config": SWEBENCH_CONFIG,
            "split": SWEBENCH_SPLIT,
            "row_index": row_index,
            "source_repo": source_repo,
            "created_at": row.get("created_at"),
            "difficulty": row.get("difficulty") or "unknown",
            "version": row.get("version"),
            "environment_setup_commit": row.get("environment_setup_commit"),
            "eval_type": row.get("eval_type"),
            "container_image": image,
            "validation_backend": "swebench_container",
            "selection_policy": "balanced_repository_difficulty_v1",
            "eval_script_sha256": hashlib.sha256(eval_script.encode("utf-8")).hexdigest(),
            "validation_asset_sha256": validation_asset_sha256,
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
            "gold_fields_excluded": sorted(FORBIDDEN_SOURCE_FIELDS),
            "human_review_required": True,
        },
    }


def _load_manifest(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"manifest line {line_number} is not a JSON object")
        rows.append(value)
    if not rows:
        raise ValueError(f"corpus manifest is empty: {path}")
    return rows, hashlib.sha256(raw).hexdigest()


def _git_commit(repository: Path, base_ref: str, git_command: str) -> str | None:
    completed = subprocess.run(
        [git_command, "-C", str(repository), "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def audit_manifest(
    path: str | Path,
    *,
    check_git: bool = False,
    git_command: str = "git",
    minimum_tasks: int = 100,
) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    rows, digest = _load_manifest(manifest_path)
    errors: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []
    ids: list[str] = []
    prompts: list[str] = []
    categories: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    static_runnable = True
    category_review_ready = True
    validation_backend_ready = True
    git_verified = check_git

    for line_number, row in enumerate(rows, 1):
        prefix = f"line {line_number}"
        task_id = row.get("id")
        prompt = row.get("prompt")
        base_ref = row.get("base_ref")
        category = row.get("category")
        repository_value = row.get("repository")
        provenance = row.get("provenance")
        validation = row.get("validation")

        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"{prefix}: missing non-empty id")
        else:
            ids.append(task_id)
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{prefix}: missing non-empty prompt")
        else:
            prompts.append(prompt.strip())
        if not isinstance(base_ref, str) or not FULL_SHA.fullmatch(base_ref):
            errors.append(f"{prefix}: base_ref must be a full lowercase commit SHA")
        if not isinstance(category, str):
            errors.append(f"{prefix}: category must be a string")
            static_runnable = False
            category_review_ready = False
        else:
            categories[category] += 1
            if category not in PHASE5_CATEGORIES:
                static_runnable = False
                category_review_ready = False
        if not isinstance(repository_value, str) or not repository_value.strip():
            errors.append(f"{prefix}: repository must be a non-empty path")
            static_runnable = False
        leaked = sorted(FORBIDDEN_SOURCE_FIELDS & set(row))
        if isinstance(provenance, dict):
            leaked.extend(sorted(FORBIDDEN_SOURCE_FIELDS & set(provenance)))
            source = provenance.get("dataset")
            if isinstance(source, str):
                sources[source] += 1
            else:
                errors.append(f"{prefix}: provenance.dataset is missing")
            if not FULL_SHA.fullmatch(str(provenance.get("revision", ""))):
                errors.append(f"{prefix}: provenance.revision is not a full SHA")
            if provenance.get("human_review_required"):
                static_runnable = False
                category_review_ready = False
        else:
            warnings.append(f"{prefix}: source provenance is missing")

        validation_command = validation.get("command") if isinstance(validation, dict) else None
        sealed_container_validation = (
            isinstance(provenance, dict)
            and provenance.get("validation_backend") == "swebench_container"
            and SHA256_HEX.fullmatch(
                str(provenance.get("validation_asset_sha256", ""))
            )
        )
        if validation_command:
            if not isinstance(validation_command, list) or not all(
                isinstance(item, str) and item for item in validation_command
            ):
                errors.append(f"{prefix}: validation.command must be an argument array")
                static_runnable = False
                validation_backend_ready = False
        elif not sealed_container_validation:
            static_runnable = False
            validation_backend_ready = False
        if leaked:
            errors.append(f"{prefix}: forbidden gold/source fields leaked: {', '.join(leaked)}")

        if check_git and isinstance(repository_value, str) and isinstance(base_ref, str):
            repository = Path(repository_value)
            if not repository.is_absolute():
                repository = (manifest_path.parent / repository).resolve()
            if not repository.is_dir():
                errors.append(f"{prefix}: repository does not exist: {repository}")
                git_verified = False
            elif _git_commit(repository, base_ref, git_command) != base_ref:
                errors.append(f"{prefix}: base_ref does not resolve exactly in {repository}")
                git_verified = False

    duplicate_ids = sorted(key for key, count in Counter(ids).items() if count > 1)
    duplicate_prompts = sum(count - 1 for count in Counter(prompts).values() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate task ids: {', '.join(duplicate_ids[:10])}")
    if duplicate_prompts:
        errors.append(f"duplicate prompts: {duplicate_prompts}")

    source_valid = not errors
    if len(rows) < minimum_tasks:
        blockers.append(f"only {len(rows)} tasks; at least {minimum_tasks} required")
    missing_categories = sorted(set(PHASE5_CATEGORIES) - set(categories))
    if missing_categories:
        blockers.append("missing Phase 5 categories: " + ", ".join(missing_categories))
    invalid_categories = sorted(set(categories) - set(PHASE5_CATEGORIES))
    if invalid_categories:
        blockers.append("unreviewed/invalid categories: " + ", ".join(invalid_categories))
    if not category_review_ready:
        blockers.append("one or more tasks require category/human review")
    if not validation_backend_ready:
        blockers.append("one or more tasks lack a declared validation backend")
    if not check_git:
        blockers.append("Git repositories and base commits were not checked")
    elif not git_verified:
        blockers.append("one or more repositories/base commits failed verification")
    if errors:
        blockers.append("manifest integrity errors must be fixed")

    manifest_runnable = source_valid and static_runnable
    claims_corpus_ready = (
        manifest_runnable
        and git_verified
        and len(rows) >= minimum_tasks
        and not missing_categories
    )
    return {
        "manifest": str(manifest_path),
        "manifest_sha256": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": len(rows),
        "unique_task_ids": len(set(ids)),
        "sources": dict(sorted(sources.items())),
        "categories": dict(sorted(categories.items())),
        "missing_categories": missing_categories,
        "source_valid": source_valid,
        "manifest_runnable": manifest_runnable,
        "git_checked": check_git,
        "git_verified": git_verified,
        "claims_corpus_ready": claims_corpus_ready,
        "errors": errors,
        "warnings": warnings,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ValueError(f"output already exists; pass --overwrite to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def _write_audit(path: Path, report: dict[str, Any]) -> Path:
    audit_path = path.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return audit_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-codex-corpus",
        description="Import and audit real Phase 5 corpus candidates.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser(
        "import-swebench", help="Import a leak-safe SWE-bench Verified candidate slice"
    )
    import_parser.add_argument("--output", default="data/swebench_verified_candidates.jsonl")
    import_parser.add_argument("--repository-root", default="data/phase5_repositories")
    import_parser.add_argument("--limit", type=int, default=100)
    import_parser.add_argument("--offset", type=int, default=0)
    import_parser.add_argument(
        "--source-limit",
        type=int,
        default=500,
        help="Source rows to scan before balanced repository/difficulty selection",
    )
    import_parser.add_argument("--source-revision", default=SWEBENCH_REVISION)
    import_parser.add_argument("--timeout-seconds", type=float, default=60)
    import_parser.add_argument(
        "--validation-assets",
        help="Sealed official-harness JSONL; defaults beside --output",
    )
    import_parser.add_argument("--overwrite", action="store_true")

    audit_parser = commands.add_parser("audit", help="Audit a Phase 5 corpus manifest")
    audit_parser.add_argument("manifest")
    audit_parser.add_argument("--check-git", action="store_true")
    audit_parser.add_argument("--git-command", default="git")
    audit_parser.add_argument("--minimum-tasks", type=int, default=100)
    audit_parser.add_argument(
        "--require",
        choices=("source", "runnable", "claims"),
        default="source",
        help="Readiness level required for a zero exit code",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import-swebench":
            output = Path(args.output).resolve()
            repository_root = Path(args.repository_root).resolve()
            source_rows = fetch_swebench_rows(
                limit=args.source_limit,
                offset=args.offset,
                revision=args.source_revision,
                timeout_seconds=args.timeout_seconds,
            )
            selected_rows = select_balanced_swebench_rows(
                source_rows,
                limit=args.limit,
            )
            assets = [
                build_swebench_validation_asset(
                    row_index,
                    row,
                    revision=args.source_revision,
                )
                for row_index, row in selected_rows
            ]
            asset_hashes = {asset["id"]: asset["asset_sha256"] for asset in assets}
            rows = [
                normalize_swebench_row(
                    row_index,
                    row,
                    output_path=output,
                    repository_root=repository_root,
                    revision=args.source_revision,
                    validation_asset_sha256=asset_hashes[row["instance_id"]],
                )
                for row_index, row in selected_rows
            ]
            _write_jsonl(output, rows, overwrite=args.overwrite)
            assets_path = (
                Path(args.validation_assets).resolve()
                if args.validation_assets
                else output.with_name(f"{output.stem}.validation.jsonl")
            )
            _write_jsonl(assets_path, assets, overwrite=args.overwrite)
            report = audit_manifest(output)
            audit_path = _write_audit(output, report)
            print(f"Imported candidate tasks: {len(rows)}")
            print(f"Manifest: {output}")
            print(f"Audit: {audit_path}")
            print(f"Sealed validation assets: {assets_path}")
            print(f"Claims corpus ready: {report['claims_corpus_ready']}")
            for blocker in report["blockers"]:
                print(f"Blocker: {blocker}")
            return 0 if report["source_valid"] else 2

        report = audit_manifest(
            args.manifest,
            check_git=args.check_git,
            git_command=args.git_command,
            minimum_tasks=args.minimum_tasks,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        ready = {
            "source": report["source_valid"],
            "runnable": report["manifest_runnable"],
            "claims": report["claims_corpus_ready"],
        }[args.require]
        return 0 if ready else 2
    except (OSError, ValueError) as exc:
        print(f"Corpus operation blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
