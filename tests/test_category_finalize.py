from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import SRC  # noqa: F401

from adaptive_codex_router.benchmark.category_finalize import finalize_categories


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class CategoryFinalizeTests(unittest.TestCase):
    def test_finalize_preserves_proposal_and_applies_audited_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jsonl"
            proposals = root / "proposals.jsonl"
            decisions = root / "decisions.json"
            write_jsonl(
                source,
                [
                    {"id": "one", "category": "uncategorized", "provenance": {"human_review_required": True}},
                    {"id": "two", "category": "uncategorized", "provenance": {"human_review_required": True}},
                ],
            )
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            write_jsonl(
                proposals,
                [
                    {"task_id": "one", "suggested_category": "normal_implementation", "source_manifest_sha256": source_hash},
                    {"task_id": "two", "suggested_category": "debugging", "source_manifest_sha256": source_hash},
                ],
            )
            proposal_hash = hashlib.sha256(proposals.read_bytes()).hexdigest()
            decisions.write_text(
                json.dumps(
                    {
                        "source_manifest_sha256": source_hash,
                        "proposal_sha256": proposal_hash,
                        "reviewed_by": "reviewer",
                        "review_authority": "user_delegated",
                        "reviewed_at": "2026-09-10T00:00:00Z",
                        "overrides": [
                            {"task_id": "one", "from": "normal_implementation", "to": "debugging", "reason": "Existing behavior is broken."}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rows, summary = finalize_categories(source, proposals, decisions)

            self.assertEqual([row["category"] for row in rows], ["debugging", "debugging"])
            self.assertTrue(rows[0]["provenance"]["category_review"]["status"] == "modified")
            self.assertFalse(rows[1]["provenance"]["human_review_required"])
            self.assertEqual(summary["confirmed"], 1)
            self.assertEqual(summary["modified"], 1)

    def test_finalize_rejects_changed_proposal_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jsonl"
            proposals = root / "proposals.jsonl"
            decisions = root / "decisions.json"
            write_jsonl(source, [{"id": "one", "provenance": {}}])
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            write_jsonl(proposals, [{"task_id": "one", "suggested_category": "debugging", "source_manifest_sha256": source_hash}])
            decisions.write_text(
                json.dumps({"source_manifest_sha256": source_hash, "proposal_sha256": "0" * 64, "overrides": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "proposal SHA-256 mismatch"):
                finalize_categories(source, proposals, decisions)


if __name__ == "__main__":
    unittest.main()
