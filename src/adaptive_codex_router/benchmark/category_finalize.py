"""Finalize user-delegated category review without overwriting Qwen proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase5 import PHASE5_CATEGORIES


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on {path} line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path} line {line_number} must be an object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{path} is empty")
    return rows


def _unique_by(rows: Sequence[Mapping[str, Any]], key: str, label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} row has no {key}")
        if value in result:
            raise ValueError(f"duplicate {label} {key}: {value}")
        result[value] = row
    return result


def finalize_categories(
    source_path: str | Path,
    proposal_path: str | Path,
    decision_path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = Path(source_path).resolve()
    proposals_file = Path(proposal_path).resolve()
    decisions_file = Path(decision_path).resolve()
    source_digest = _sha256(source)
    proposal_digest = _sha256(proposals_file)
    decisions = json.loads(decisions_file.read_text(encoding="utf-8-sig"))
    if not isinstance(decisions, dict):
        raise ValueError("category decision must be an object")
    if decisions.get("source_manifest_sha256") != source_digest:
        raise ValueError("category decision source manifest SHA-256 mismatch")
    if decisions.get("proposal_sha256") != proposal_digest:
        raise ValueError("category decision proposal SHA-256 mismatch")

    source_rows = _read_jsonl(source)
    proposal_rows = _read_jsonl(proposals_file)
    source_by_id = _unique_by(source_rows, "id", "source")
    proposals_by_id = _unique_by(proposal_rows, "task_id", "proposal")
    if set(source_by_id) != set(proposals_by_id):
        raise ValueError("source and proposal task ID sets differ")
    for proposal in proposal_rows:
        if proposal.get("source_manifest_sha256") != source_digest:
            raise ValueError("proposal source manifest SHA-256 mismatch")

    overrides: dict[str, Mapping[str, Any]] = {}
    for override in decisions.get("overrides", []):
        if not isinstance(override, dict):
            raise ValueError("each category override must be an object")
        task_id = override.get("task_id")
        if task_id not in source_by_id:
            raise ValueError(f"category override has unknown task: {task_id}")
        if task_id in overrides:
            raise ValueError(f"duplicate category override: {task_id}")
        proposal = proposals_by_id[str(task_id)]
        if override.get("from") != proposal.get("suggested_category"):
            raise ValueError(f"category override source mismatch for {task_id}")
        if override.get("to") not in PHASE5_CATEGORIES:
            raise ValueError(f"invalid reviewed category for {task_id}")
        if not str(override.get("reason", "")).strip():
            raise ValueError(f"category override needs a reason for {task_id}")
        overrides[str(task_id)] = override

    decision_digest = _sha256(decisions_file)
    reviewed_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        task_id = str(source_row["id"])
        proposal = proposals_by_id[task_id]
        suggested = str(proposal["suggested_category"])
        if suggested not in PHASE5_CATEGORIES:
            raise ValueError(f"invalid proposed category for {task_id}")
        override = overrides.get(task_id)
        final = str(override["to"]) if override else suggested
        row = dict(source_row)
        provenance = dict(row.get("provenance", {}))
        provenance["human_review_required"] = False
        provenance["category_review"] = {
            "status": "modified" if override else "confirmed",
            "suggested_category": suggested,
            "reviewed_category": final,
            "reviewed_by": decisions.get("reviewed_by"),
            "review_authority": decisions.get("review_authority"),
            "reviewed_at": decisions.get("reviewed_at"),
            "decision_sha256": decision_digest,
        }
        row["category"] = final
        row["provenance"] = provenance
        reviewed_rows.append(row)
        review_rows.append(
            {
                "task_id": task_id,
                "suggested_category": suggested,
                "reviewed_category": final,
                "status": "modified" if override else "confirmed",
                "reason": str(override["reason"]) if override else "Qwen proposal confirmed after independent public-prompt review.",
            }
        )

    distribution = Counter(row["category"] for row in reviewed_rows)
    summary = {
        "source_manifest_sha256": source_digest,
        "proposal_sha256": proposal_digest,
        "decision_sha256": decision_digest,
        "reviewed_at": decisions.get("reviewed_at"),
        "reviewed_by": decisions.get("reviewed_by"),
        "review_authority": decisions.get("review_authority"),
        "reviewed_tasks": len(reviewed_rows),
        "confirmed": len(reviewed_rows) - len(overrides),
        "modified": len(overrides),
        "human_review_required": False,
        "category_distribution": {
            category: distribution.get(category, 0) for category in PHASE5_CATEGORIES
        },
        "missing_categories": [
            category for category in PHASE5_CATEGORIES if not distribution.get(category)
        ],
        "changes": [dict(value) for value in overrides.values()],
        "reviews": review_rows,
    }
    return reviewed_rows, summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 5 confirmed category review",
        "",
        f"Reviewer: `{summary['reviewed_by']}` (`{summary['review_authority']}`)",
        "",
        f"Reviewed: {summary['reviewed_tasks']}; confirmed: {summary['confirmed']}; modified: {summary['modified']}.",
        "",
        "## Distribution",
        "",
        "| Category | Tasks |",
        "|---|---:|",
    ]
    for category in PHASE5_CATEGORIES:
        lines.append(f"| `{category}` | {summary['category_distribution'][category]} |")
    lines.extend(["", "## Decisions", "", "| Status | Task | Qwen | Final | Reason |", "|---|---|---|---|---|"])
    for row in summary["reviews"]:
        lines.append(
            "| {status} | {task} | `{suggested}` | `{final}` | {reason} |".format(
                status="Modified" if row["status"] == "modified" else "Confirmed",
                task=row["task_id"],
                suggested=row["suggested_category"],
                final=row["reviewed_category"],
                reason=str(row["reason"]).replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smart-codex-category-finalize")
    parser.add_argument("--dataset", default="data/swebench_verified_candidates.jsonl")
    parser.add_argument("--proposals", default="data/swebench_verified_category_review.jsonl")
    parser.add_argument("--decisions", default="data/swebench_verified_category_decision.json")
    parser.add_argument("--output", default="data/swebench_verified_reviewed.jsonl")
    args = parser.parse_args(argv)
    reviewed, summary = finalize_categories(args.dataset, args.proposals, args.decisions)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in reviewed),
        encoding="utf-8",
    )
    summary_path = output.with_suffix(".summary.json")
    markdown_path = output.with_suffix(".md")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    print(f"Finalized {summary['reviewed_tasks']} tasks: {summary['confirmed']} confirmed, {summary['modified']} modified")
    if summary["missing_categories"]:
        print("Missing categories: " + ", ".join(summary["missing_categories"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
