from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.support import ROOT, SRC, runtime_path  # noqa: F401

from adaptive_codex_router.benchmark.corpus import (
    SWEBENCH_REVISION,
    audit_manifest,
    fetch_swebench_rows,
    normalize_swebench_row,
    select_balanced_swebench_rows,
)


def source_row(index: int = 0) -> dict:
    return {
        "instance_id": f"owner__repo-{index}",
        "repo": "owner/repo",
        "base_commit": f"{index + 1:040x}",
        "problem_statement": f"Fix real issue {index}",
        "image": f"swebench/example:{index}",
        "eval_script": "#!/bin/bash\npytest -q\n",
        "FAIL_TO_PASS": ["tests/test_issue.py::test_regression"],
        "PASS_TO_PASS": ["tests/test_issue.py::test_existing"],
        "patch": "gold solution must not leak",
        "test_patch": "gold tests must not leak",
        "hints_text": "maintainer hint must not leak",
        "created_at": "2025-01-01T00:00:00Z",
        "difficulty": "15 min - 1 hour",
        "version": "1.0",
        "environment_setup_commit": f"{index + 2:040x}",
        "eval_type": "pass_and_fail",
    }


class CorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self.paths:
            path.unlink(missing_ok=True)

    def test_normalization_excludes_gold_content_and_marks_candidate(self) -> None:
        output = runtime_path()
        normalized = normalize_swebench_row(
            7,
            source_row(7),
            output_path=output,
            repository_root=ROOT / "data" / "phase5_repositories",
        )
        serialized = json.dumps(normalized)
        self.assertNotIn("gold solution", serialized)
        self.assertNotIn("gold tests", serialized)
        self.assertNotIn("maintainer hint", serialized)
        self.assertNotIn("eval_script", normalized["provenance"])
        self.assertEqual(normalized["category"], "uncategorized")
        self.assertEqual(normalized["validation"]["command"], [])
        self.assertEqual(
            normalized["provenance"]["validation_backend"], "swebench_container"
        )
        self.assertEqual(normalized["provenance"]["revision"], SWEBENCH_REVISION)

    def test_fetch_checks_revision_and_paginates_at_100(self) -> None:
        calls: list[str] = []

        def fake_fetch(url: str, timeout: float) -> dict:
            calls.append(url)
            if "/api/datasets/" in url:
                return {"sha": SWEBENCH_REVISION}
            query_offset = 0 if "offset=0" in url else 100
            length = 100 if query_offset == 0 else 1
            return {
                "partial": False,
                "rows": [
                    {
                        "row_idx": query_offset + index,
                        "row": source_row(query_offset + index),
                        "truncated_cells": [],
                    }
                    for index in range(length)
                ],
                "num_rows_total": 500,
            }

        rows = fetch_swebench_rows(limit=101, fetch_json=fake_fetch)
        self.assertEqual(len(rows), 101)
        self.assertEqual(sum("/rows?" in call for call in calls), 2)

    def test_fetch_refuses_unreviewed_dataset_revision(self) -> None:
        def fake_fetch(url: str, timeout: float) -> dict:
            return {"sha": "f" * 40}

        with self.assertRaisesRegex(ValueError, "Hub revision changed"):
            fetch_swebench_rows(limit=1, fetch_json=fake_fetch)

    def test_balanced_selection_is_deterministic_across_buckets(self) -> None:
        rows = []
        for index in range(20):
            row = source_row(index)
            row["repo"] = f"owner/repo-{index % 4}"
            row["difficulty"] = "short" if index % 2 else "long"
            rows.append((index, row))
        first = select_balanced_swebench_rows(rows, limit=8)
        second = select_balanced_swebench_rows(list(reversed(rows)), limit=8)
        self.assertEqual(
            [row["instance_id"] for _, row in first],
            [row["instance_id"] for _, row in second],
        )
        self.assertEqual(len({row["repo"] for _, row in first}), 4)

    def test_candidate_audit_is_source_valid_but_not_runnable(self) -> None:
        path = runtime_path()
        self.paths.append(path)
        rows = [
            normalize_swebench_row(
                index,
                source_row(index),
                output_path=path,
                repository_root=ROOT / "data" / "phase5_repositories",
                validation_asset_sha256="a" * 64,
            )
            for index in range(100)
        ]
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        report = audit_manifest(path)
        self.assertTrue(report["source_valid"])
        self.assertFalse(report["manifest_runnable"])
        self.assertFalse(report["claims_corpus_ready"])
        self.assertIn("uncategorized", report["categories"])
        self.assertFalse(
            any("declared validation backend" in item for item in report["blockers"])
        )
        self.assertTrue(any("unreviewed/invalid categories" in item for item in report["blockers"]))
        self.assertTrue(any("Git repositories" in item for item in report["blockers"]))

    def test_audit_detects_gold_field_leakage(self) -> None:
        path = runtime_path()
        self.paths.append(path)
        row = normalize_swebench_row(
            0,
            source_row(),
            output_path=path,
            repository_root=ROOT / "data" / "phase5_repositories",
        )
        row["patch"] = "leaked"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        report = audit_manifest(path, minimum_tasks=1)
        self.assertFalse(report["source_valid"])
        self.assertTrue(any("forbidden" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
