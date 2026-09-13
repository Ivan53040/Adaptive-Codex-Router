from __future__ import annotations

import unittest
from pathlib import Path

from tests.support import SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.app import AdaptiveCodexRouter
from adaptive_codex_router.executor.codex import ExecutorPreflightError, MockCodexExecutor
from adaptive_codex_router.router.classifier import MockLunaClassifier
from adaptive_codex_router.router.policy import GuardrailError, RoutingPolicy
from adaptive_codex_router.router.schemas import (
    FailureType,
    ExecutionResult,
    ModelName,
    ModelRoute,
    ReasoningEffort,
)


class RejectingExecutor:
    def preflight(self, working_directory):
        raise ExecutorPreflightError("unsafe target")

    def execute(self, prompt, route, working_directory):
        raise AssertionError("execute must not be called")

    def cancel(self):
        return False


class InfrastructureFailureExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def preflight(self, working_directory):
        return Path(working_directory).resolve()

    def execute(self, prompt, route, working_directory):
        self.calls += 1
        return ExecutionResult(
            success=False,
            output="CLI unavailable",
            exit_code=7,
            failure_type=FailureType.EXECUTOR,
        )

    def cancel(self):
        return False


class EscalationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = runtime_path()
        self.config = test_config(self.path)
        self.policy = RoutingPolicy(self.config)
        self.classifier = MockLunaClassifier()

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_failed_luna_task_escalates_to_terra(self) -> None:
        router = AdaptiveCodexRouter(
            self.config,
            executor=MockCodexExecutor(fail_models={ModelName.LUNA}),
        )
        result = router.run("Fix a typo in README.md")
        self.assertTrue(result.success)
        self.assertEqual(
            [attempt.route.model for attempt in result.attempts],
            [ModelName.LUNA, ModelName.TERRA],
        )
        self.assertIsNotNone(result.attempts[0].escalation_reason)

    def test_preflight_happens_before_classifier_call(self) -> None:
        class CountingClassifier(MockLunaClassifier):
            called = False

            def classify(self, prompt, metadata=None):
                self.called = True
                return super().classify(prompt, metadata)

        classifier = CountingClassifier()
        router = AdaptiveCodexRouter(
            self.config,
            classifier=classifier,
            executor=RejectingExecutor(),
        )
        with self.assertRaisesRegex(ExecutorPreflightError, "unsafe target"):
            router.run("Fix a typo")
        self.assertFalse(classifier.called)

    def test_executor_infrastructure_failure_does_not_waste_an_escalation(self) -> None:
        executor = InfrastructureFailureExecutor()
        router = AdaptiveCodexRouter(self.config, executor=executor)
        result = router.run("Fix a typo in README.md")

        self.assertFalse(result.success)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.stop_reason, "executor infrastructure failure")

    def test_reasoning_failure_can_skip_terra(self) -> None:
        task = self.classifier.classify("Fix a typo in README.md")
        current = self.policy.select_initial(task)
        route = self.policy.escalate(
            current,
            task,
            FailureType.REASONING,
            previous_failures=1,
            allow_max=False,
            high_task_value=False,
        )
        self.assertEqual(route.model, ModelName.SOL)

    def test_sol_failure_escalates_to_astra_low(self) -> None:
        task = self.classifier.classify("Debug a complex race condition")
        current = self.policy.select_initial(task)
        route = self.policy.escalate(
            current,
            task,
            FailureType.CAPABILITY,
            previous_failures=1,
            allow_max=False,
            high_task_value=False,
        )
        self.assertEqual(route.key, (ModelName.ASTRA, ReasoningEffort.LOW))

    def test_astra_xhigh_requires_high_value_and_prior_escalation(self) -> None:
        task = self.classifier.classify("Architecture for a difficult repository")
        current = ModelRoute(
            model=ModelName.ASTRA,
            model_id=self.config.model(ModelName.ASTRA).model_id,
            effort=ReasoningEffort.HIGH,
            is_escalation=True,
        )
        with self.assertRaisesRegex(GuardrailError, "high-value"):
            self.policy.escalate(
                current,
                task,
                FailureType.REASONING,
                previous_failures=2,
                allow_max=False,
                high_task_value=False,
            )

    def test_astra_max_requires_explicit_permission(self) -> None:
        task = self.classifier.classify("Architecture for a very difficult high-value system")
        current = ModelRoute(
            model=ModelName.ASTRA,
            model_id=self.config.model(ModelName.ASTRA).model_id,
            effort=ReasoningEffort.XHIGH,
            is_escalation=True,
        )
        with self.assertRaisesRegex(GuardrailError, "allow-max"):
            self.policy.escalate(
                current,
                task,
                FailureType.REASONING,
                previous_failures=3,
                allow_max=False,
                high_task_value=True,
            )


if __name__ == "__main__":
    unittest.main()
