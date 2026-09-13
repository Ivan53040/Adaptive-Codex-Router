from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.support import ROOT, SRC, test_config  # noqa: F401

from adaptive_codex_router.benchmark.category_review import (
    QwenCategoryReviewer,
    render_review_markdown,
    summarize_reviews,
)
from adaptive_codex_router.benchmark.runner import BenchmarkTask
from adaptive_codex_router.router.schemas import TaskMetadata, ValidationSpec


def task(task_id: str) -> BenchmarkTask:
    return BenchmarkTask(
        task_id=task_id,
        prompt="Fix a regression in parsing.",
        repository=Path("missing"),
        base_ref="1" * 40,
        category="uncategorized",
        metadata=TaskMetadata(tests_requested=True),
        validation=ValidationSpec(),
        provenance={"source_repo": "owner/repo", "difficulty": "15 min - 1 hour"},
    )


class CategoryReviewTests(unittest.TestCase):
    def test_qwen_request_uses_high_reasoning_and_validates_all_ids(self) -> None:
        tasks = [task("one"), task("two")]
        tasks[0].provenance["test_patch"] = "SEALED_VALIDATION_SECRET"
        requests = []

        def requester(request, timeout):
            requests.append((request, timeout))
            reviews = [
                {
                    "task_id": item.task_id,
                    "suggested_category": "debugging",
                    "secondary_category": None,
                    "confidence": 0.9,
                    "rationale": "Existing behavior is incorrect.",
                    "review_flags": [],
                }
                for item in tasks
            ]
            return json.dumps(
                {
                    "choices": [{"message": {"content": json.dumps({"reviews": reviews})}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                }
            ).encode()

        reviewer = QwenCategoryReviewer(
            test_config(ROOT / "tests" / "fixtures" / "category-telemetry.jsonl"),
            requester=requester,
        )
        reviews, diagnostics = reviewer.review_batch(tasks)
        payload = json.loads(requests[0][0].data)
        self.assertEqual(payload["chat_template_kwargs"]["reasoning_effort"], "high")
        self.assertTrue(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(payload["thinking_budget_tokens"], 8192)
        self.assertGreaterEqual(payload["max_tokens"], 16384)
        self.assertNotIn("SEALED_VALIDATION_SECRET", payload["messages"][0]["content"])
        self.assertEqual({row["task_id"] for row in reviews}, {"one", "two"})
        self.assertEqual(diagnostics["input_tokens"], 12)

    def test_qwen_response_must_cover_every_task(self) -> None:
        tasks = [task("one"), task("two")]
        value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "reviews": [
                                    {
                                        "task_id": "one",
                                        "suggested_category": "debugging",
                                        "secondary_category": None,
                                        "confidence": 0.8,
                                        "rationale": "Regression.",
                                        "review_flags": [],
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "omitted task IDs"):
            QwenCategoryReviewer._parse_reviews(value, [item.task_id for item in tasks])

    def test_summary_and_markdown_remain_human_review_only(self) -> None:
        tasks = [task("one")]
        record = {
            "task_id": "one",
            "suggested_category": "debugging",
            "secondary_category": None,
            "confidence": 0.7,
            "rationale": "Regression.",
            "review_flags": ["requires_repository_inspection"],
            "batch_id": "batch",
            "batch_diagnostics": {
                "duration_ms": 10,
                "input_tokens": 12,
                "output_tokens": 8,
            },
        }
        summary = summarize_reviews(
            [record],
            manifest_sha256="a" * 64,
            expected_tasks=1,
            low_confidence_threshold=0.75,
        )
        markdown = render_review_markdown([record], tasks, summary)
        self.assertTrue(summary["human_review_required"])
        self.assertEqual(summary["low_confidence_tasks"], ["one"])
        self.assertIn("[ ]", markdown)
        self.assertIn("Qwen High proposal only", markdown)


if __name__ == "__main__":
    unittest.main()
