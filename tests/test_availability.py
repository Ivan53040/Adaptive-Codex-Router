from __future__ import annotations

import unittest

from tests.support import SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.router.availability import (
    ConfiguredAvailability,
    ModelUnavailableError,
)
from adaptive_codex_router.router.classifier import MockLunaClassifier
from adaptive_codex_router.router.policy import RoutingPolicy
from adaptive_codex_router.router.schemas import ModelName


class AvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = runtime_path()
        self.config = test_config(self.path)

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_unavailable_astra_falls_back_to_sol_high(self) -> None:
        unavailable = self.config.with_model_availability(ModelName.ASTRA, False)
        policy = RoutingPolicy(unavailable)
        task = MockLunaClassifier().classify(
            "Migrate the entire repository; this is a very difficult multi-system task"
        )
        resolved = ConfiguredAvailability(unavailable).resolve(policy.select_initial(task))
        self.assertEqual(resolved.model, ModelName.SOL)
        self.assertEqual(resolved.fallback_from, ModelName.ASTRA)

    def test_other_unavailable_model_has_no_silent_fallback(self) -> None:
        unavailable = self.config.with_model_availability(ModelName.TERRA, False)
        policy = RoutingPolicy(unavailable)
        task = MockLunaClassifier().classify("Implement pagination for the user list")
        with self.assertRaises(ModelUnavailableError):
            ConfiguredAvailability(unavailable).resolve(policy.select_initial(task))


if __name__ == "__main__":
    unittest.main()
