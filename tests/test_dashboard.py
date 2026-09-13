from __future__ import annotations

import json
import unittest
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from tests.support import ROOT
from adaptive_codex_router.dashboard import discover_runs, load_run


class DashboardTests(unittest.TestCase):
    def test_load_run_summarizes_jsonl_and_rejects_unknown_selection(self) -> None:
        data = ROOT / "tests" / "fixtures" / f"dashboard-{uuid4().hex}"
        data.mkdir(parents=True)
        try:
            (data / "phase5_demo.jsonl").write_text(
                json.dumps({
                    "task_id": "demo", "success": True, "planner_used": "qwen",
                    "final_model": "terra", "latency_ms": 1000,
                    "usage": {"reported_tokens": 12, "local_planning_input_tokens": 3,
                               "local_planning_output_tokens": 4},
                }) + "\n", encoding="utf-8"
            )
            (data / "phase5_demo.telemetry.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertEqual(discover_runs(data), ["phase5_demo.jsonl"])
            result = load_run(data, "missing.jsonl")
            self.assertEqual(result["selected"], "phase5_demo.jsonl")
            self.assertEqual(result["metrics"]["success_rate"], 1)
            self.assertEqual(result["metrics"]["reported_tokens_total"], 12)
        finally:
            rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
