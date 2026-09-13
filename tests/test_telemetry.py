from __future__ import annotations

import unittest

from tests.support import SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.app import AdaptiveCodexRouter
from adaptive_codex_router.router.schemas import ModelName
from adaptive_codex_router.telemetry.metrics import summarize


class TelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = runtime_path()
        self.config = test_config(self.path)

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_logs_routes_but_not_prompt_by_default(self) -> None:
        router = AdaptiveCodexRouter(self.config)
        result = router.run("Fix a typo containing secret-shaped but harmless text")
        events = router.telemetry.read_events()
        self.assertEqual(len(events), 1)
        self.assertNotIn("prompt", events[0])
        self.assertEqual(events[0]["task_id"], result.task_id)
        self.assertEqual(len(events[0]["route_history"]), 1)
        self.assertEqual(events[0]["planner"], "none")
        self.assertEqual(events[0]["planning"]["source"], "deterministic")
        self.assertIn("planning_fallback_reasons", events[0])

    def test_metrics_summarize_success_and_distribution(self) -> None:
        router = AdaptiveCodexRouter(self.config)
        router.run("Fix a typo in README.md")
        router.run("Implement pagination for the user list")
        metrics = summarize(router.telemetry.read_events())
        self.assertEqual(metrics["tasks"], 2)
        self.assertEqual(metrics["success_rate"], 1.0)
        self.assertEqual(
            set(metrics["model_distribution"]),
            {
                self.config.model(ModelName.LUNA).model_id,
                self.config.model(ModelName.TERRA).model_id,
            },
        )


if __name__ == "__main__":
    unittest.main()
