from __future__ import annotations

import unittest

from tests.support import SRC  # noqa: F401

from adaptive_codex_router.router.classifier import MockLunaClassifier
from adaptive_codex_router.router.schemas import (
    Complexity,
    ContextRequirement,
    Scope,
    TaskMetadata,
    TaskType,
)


class MockLunaClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = MockLunaClassifier()

    def test_simple_edit_stays_small(self) -> None:
        result = self.classifier.classify("Fix a typo in README.md")
        self.assertEqual(result.task_type, TaskType.DOCUMENTATION)
        self.assertEqual(result.scope, Scope.SINGLE_FILE)
        self.assertEqual(result.reasoning_complexity, Complexity.LOW)
        self.assertEqual(result.context_requirement, ContextRequirement.SMALL)

    def test_short_concurrency_prompt_is_not_underestimated(self) -> None:
        result = self.classifier.classify(
            "Fix race condition when websocket connections close during concurrent database writes"
        )
        self.assertEqual(result.task_type, TaskType.DEBUGGING)
        self.assertEqual(result.reasoning_complexity, Complexity.HIGH)
        self.assertEqual(result.verification_difficulty, Complexity.HIGH)

    def test_lightweight_metadata_affects_scope_without_repository_content(self) -> None:
        metadata = TaskMetadata(
            files_explicitly_mentioned=4,
            tests_requested=True,
            cross_module_dependency=True,
            number_of_expected_steps=5,
        )
        result = self.classifier.classify("Implement the requested feature", metadata)
        self.assertEqual(result.scope, Scope.MULTI_FILE)
        self.assertEqual(result.agentic_complexity, Complexity.HIGH)
        self.assertTrue(result.cross_module_dependency)

    def test_repository_migration_is_very_large(self) -> None:
        result = self.classifier.classify(
            "Migrate the entire repository; this is a very difficult multi-system task"
        )
        self.assertEqual(result.task_type, TaskType.MIGRATION)
        self.assertEqual(result.reasoning_complexity, Complexity.VERY_HIGH)
        self.assertEqual(result.context_requirement, ContextRequirement.VERY_LARGE)

    def test_large_context_agentic_metadata_is_preserved(self) -> None:
        result = self.classifier.classify(
            "Analyse the whole repository",
            TaskMetadata(repository_wide=True, number_of_expected_steps=6),
        )
        self.assertEqual(result.context_requirement, ContextRequirement.LARGE)
        self.assertEqual(result.agentic_complexity, Complexity.HIGH)
        self.assertEqual(result.number_of_expected_steps, 6)


if __name__ == "__main__":
    unittest.main()
