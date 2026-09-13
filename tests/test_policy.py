from __future__ import annotations

import unittest
from dataclasses import replace

from tests.support import SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.router.classifier import MockLunaClassifier
from adaptive_codex_router.router.policy import GuardrailError, RoutingPolicy
from adaptive_codex_router.router.schemas import (
    Complexity,
    ContextRequirement,
    ModelName,
    ReasoningEffort,
    Scope,
    TaskMetadata,
)


class RoutingPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = runtime_path()
        self.config = test_config(self.path)
        self.policy = RoutingPolicy(self.config)
        self.classifier = MockLunaClassifier()

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def route(self, prompt: str):
        return self.policy.select_initial(self.classifier.classify(prompt))

    def test_simple_task_routes_to_luna_low(self) -> None:
        route = self.route("Fix a typo in README.md")
        self.assertEqual(route.key, (ModelName.LUNA, ReasoningEffort.LOW))

    def test_normal_task_routes_to_terra_medium(self) -> None:
        route = self.route("Implement pagination for the user list")
        self.assertEqual(route.key, (ModelName.TERRA, ReasoningEffort.MEDIUM))

    def test_small_bounded_implementation_routes_to_luna_high(self) -> None:
        route = self.route("Implement a small bounded helper in helpers.py")
        self.assertEqual(route.key, (ModelName.LUNA, ReasoningEffort.HIGH))

    def test_difficult_task_routes_to_sol_high(self) -> None:
        route = self.route("Debug a complex race condition across multiple modules")
        self.assertEqual(route.key, (ModelName.SOL, ReasoningEffort.HIGH))

    def test_large_multifile_debug_does_not_jump_to_astra(self) -> None:
        task = replace(
            self.classifier.classify("Debug a complex race condition across multiple modules"),
            scope=Scope.MULTI_FILE,
            reasoning_complexity=Complexity.VERY_HIGH,
            agentic_complexity=Complexity.HIGH,
            context_requirement=ContextRequirement.LARGE,
            number_of_expected_steps=12,
        )
        route = self.policy.select_initial(task)
        self.assertEqual(route.key, (ModelName.SOL, ReasoningEffort.HIGH))

    def test_large_very_difficult_task_routes_to_astra_medium(self) -> None:
        route = self.route(
            "Migrate the entire repository architecture; this is a very difficult multi-system task"
        )
        self.assertEqual(route.key, (ModelName.ASTRA, ReasoningEffort.MEDIUM))

    def test_large_context_long_agentic_task_routes_to_astra_low(self) -> None:
        task = self.classifier.classify(
            "Analyse the whole repository",
            TaskMetadata(repository_wide=True, number_of_expected_steps=6),
        )
        route = self.policy.select_initial(task)
        self.assertEqual(route.key, (ModelName.ASTRA, ReasoningEffort.LOW))

    def test_astra_max_is_blocked_without_permission(self) -> None:
        task = self.classifier.classify("Architecture for a high-value system")
        with self.assertRaisesRegex(GuardrailError, "allow-max"):
            self.policy.manual_route(
                task,
                ModelName.ASTRA,
                ReasoningEffort.MAX,
                allow_max=False,
                high_task_value=True,
            )

    def test_manual_astra_max_requires_high_value_too(self) -> None:
        task = self.classifier.classify("Architecture for a system")
        with self.assertRaisesRegex(GuardrailError, "high-value"):
            self.policy.manual_route(
                task,
                ModelName.ASTRA,
                ReasoningEffort.MAX,
                allow_max=True,
                high_task_value=False,
            )

    def test_manual_astra_max_can_be_explicitly_authorized(self) -> None:
        task = self.classifier.classify("Architecture for a high-value system")
        route = self.policy.manual_route(
            task,
            ModelName.ASTRA,
            ReasoningEffort.MAX,
            allow_max=True,
            high_task_value=True,
        )
        self.assertEqual(route.key, (ModelName.ASTRA, ReasoningEffort.MAX))


if __name__ == "__main__":
    unittest.main()
