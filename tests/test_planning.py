from __future__ import annotations

import json
import subprocess
import sys
import unittest
import urllib.request
from dataclasses import replace
from pathlib import Path

from tests.support import ROOT, SRC, runtime_path, test_config  # noqa: F401

from adaptive_codex_router.planning import (
    MockLunaPlanner,
    MockQwenPlanner,
    NoPlanningProvider,
    PlanningCore,
    QwenLocalPlanner,
    LunaCodexPlanner,
)
from adaptive_codex_router.cli import build_parser
from adaptive_codex_router.config import AppConfig
from adaptive_codex_router.router.policy import RoutingPolicy
from adaptive_codex_router.router.schemas import ModelName, ProviderStatus


def valid_planning_payload() -> dict[str, object]:
    return {
        "task_type": "debugging",
        "scope": "multi_file",
        "reasoning_complexity": "high",
        "agentic_complexity": "medium",
        "ambiguity": "medium",
        "risk": "high",
        "verification_difficulty": "high",
        "context_requirement": "medium",
        "expected_task_length": "medium",
        "confidence": 0.94,
        "number_of_expected_steps": 4,
        "cross_module_dependency": True,
        "relevant_files": ["src/router.py", "tests/test_router.py"],
        "implementation_plan": ["Inspect the failure", "Apply the fix"],
        "verification_steps": ["Run router tests"],
        "risks": ["Regression in fallback behavior"],
        "suggested_execution_tier": "sol",
    }


class FakeHttpRequester:
    def __init__(self) -> None:
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append((request, timeout))
        if request.full_url.endswith("/health"):
            return b'{"status":"ok"}'
        if request.full_url.endswith("/v1/models"):
            return b'{"data":[{"id":"qwen3.8-27b"}]}'
        response = {
            "choices": [{"message": {"content": json.dumps(valid_planning_payload())}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        }
        return json.dumps(response).encode()


class ReasoningFallbackRequester(FakeHttpRequester):
    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append((request, timeout))
        if request.full_url.endswith("/health"):
            return b'{"status":"ok"}'
        if request.full_url.endswith("/v1/models"):
            return b'{"data":[{"id":"qwen3.8-27b"}]}'
        response = {
            "choices": [{
                "message": {
                    "content": "{malformed final content",
                    "reasoning_content": json.dumps(valid_planning_payload()),
                }
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }
        return json.dumps(response).encode()


class MalformedThenValidRequester(FakeHttpRequester):
    def __init__(self) -> None:
        super().__init__()
        self.chat_calls = 0

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append((request, timeout))
        if request.full_url.endswith("/health"):
            return b'{"status":"ok"}'
        if request.full_url.endswith("/v1/models"):
            return b'{"data":[{"id":"qwen3.8-27b"}]}'
        self.chat_calls += 1
        content = "{ malformed" if self.chat_calls == 1 else json.dumps(valid_planning_payload())
        return json.dumps({
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }).encode()


class FakeLunaRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs):
        self.calls.append((command, kwargs))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(valid_planning_payload()), encoding="utf-8")
        stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "cached_input_tokens": 90,
                    "output_tokens": 35,
                },
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


class PlanningProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = runtime_path()
        self.config = test_config(self.path)

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_mock_qwen_and_luna_share_the_common_schema(self) -> None:
        qwen = MockQwenPlanner().plan("Implement a router", ROOT)
        luna = MockLunaPlanner().plan("Implement a router", ROOT)
        self.assertEqual(set(qwen.to_dict()), set(luna.to_dict()))
        self.assertEqual(qwen.classification, luna.classification)
        self.assertEqual(qwen.planner, "qwen")
        self.assertEqual(luna.planner, "luna")

    def test_auto_prefers_qwen(self) -> None:
        core = PlanningCore(
            "auto", qwen=MockQwenPlanner(), luna=MockLunaPlanner()
        )
        result = core.plan("Fix a typo", ROOT)
        self.assertEqual(result.planner, "qwen")
        self.assertEqual(core.last_diagnostics.fallback_reasons, ())

    def test_auto_falls_back_from_qwen_to_luna(self) -> None:
        core = PlanningCore(
            "auto",
            qwen=MockQwenPlanner(status=ProviderStatus.OFFLINE),
            luna=MockLunaPlanner(),
        )
        result = core.plan("Fix a typo", ROOT)
        self.assertEqual(result.planner, "luna")
        self.assertEqual(core.last_diagnostics.provider, "luna")
        self.assertIn("qwen: provider offline", core.last_diagnostics.fallback_reasons)

    def test_auto_uses_none_when_both_external_providers_fail(self) -> None:
        core = PlanningCore(
            "auto",
            qwen=MockQwenPlanner(fail=True),
            luna=MockLunaPlanner(status=ProviderStatus.OFFLINE),
        )
        result = core.plan("Fix a typo", ROOT)
        self.assertEqual(result.planner, "none")
        self.assertEqual(result.implementation_plan, ())
        self.assertEqual(len(core.last_diagnostics.fallback_reasons), 2)

    def test_none_mode_never_calls_external_planners(self) -> None:
        core = PlanningCore(
            "none",
            qwen=MockQwenPlanner(fail=True),
            luna=MockLunaPlanner(fail=True),
            none=NoPlanningProvider(),
        )
        result = core.plan("Implement pagination", ROOT)
        self.assertEqual(result.planner, "none")
        self.assertEqual(core.last_diagnostics.source, "deterministic")

    def test_routing_policy_consumes_planning_result(self) -> None:
        result = MockQwenPlanner().plan("Architecture for a secure migration", ROOT)
        route = RoutingPolicy(self.config).select_initial(result)
        self.assertEqual(route.model, ModelName.SOL)

    def test_qwen_uses_high_reasoning_and_openai_compatible_endpoint(self) -> None:
        requester = FakeHttpRequester()
        planner = QwenLocalPlanner(self.config, requester=requester)
        self.assertEqual(planner.status(), ProviderStatus.ONLINE)
        result = planner.plan("Debug the router", ROOT)

        self.assertEqual(result.planner, "qwen")
        self.assertEqual(result.suggested_execution_tier, ModelName.SOL)
        chat_request, timeout = requester.requests[-1]
        self.assertTrue(chat_request.full_url.endswith("/v1/chat/completions"))
        body = json.loads(chat_request.data)
        self.assertEqual(
            body["chat_template_kwargs"],
            {"enable_thinking": True, "reasoning_effort": "high"},
        )
        self.assertEqual(body["model"], "qwen3.8-27b")
        self.assertIn("exactly these keys", body["messages"][0]["content"])
        self.assertEqual(timeout, self.config.planning.qwen_timeout_seconds)
        self.assertTrue(planner.last_diagnostics.local_inference)
        self.assertEqual(planner.last_diagnostics.input_tokens, 100)

    def test_qwen_retries_reasoning_content_when_final_content_is_malformed(self) -> None:
        planner = QwenLocalPlanner(
            self.config,
            requester=ReasoningFallbackRequester(),
        )
        result = planner.plan("Debug the router", ROOT)
        self.assertEqual(result.planner, "qwen")
        self.assertEqual(result.task_type, "debugging")

    def test_qwen_retry_drops_unreliable_server_schema_mode(self) -> None:
        requester = MalformedThenValidRequester()
        planner = QwenLocalPlanner(self.config, requester=requester)
        planner.plan("Debug the router", ROOT)
        chat_requests = [request for request, _ in requester.requests if request.full_url.endswith("/v1/chat/completions")]
        self.assertEqual(len(chat_requests), 2)
        self.assertIn("response_format", json.loads(chat_requests[0].data))
        self.assertNotIn("response_format", json.loads(chat_requests[1].data))

    def test_config_and_cli_expose_planner_selection(self) -> None:
        config = AppConfig.load(ROOT / "config.yaml")
        self.assertEqual(config.planning.default_provider, "qwen")
        self.assertEqual(config.planning.qwen_reasoning_effort, "high")
        args = build_parser().parse_args(["--planner", "auto", "Fix the task"])
        self.assertEqual(args.planner, "auto")

    def test_luna_uses_same_schema_in_read_only_codex_call(self) -> None:
        runner = FakeLunaRunner()
        config = replace(
            self.config,
            planning=replace(
                self.config.planning,
                luna_codex_command=sys.executable,
            ),
        )
        planner = LunaCodexPlanner(config, runner=runner)
        result = planner.plan("Debug the router", ROOT)

        self.assertEqual(result.planner, "luna")
        command, kwargs = runner.calls[0]
        self.assertIn("read-only", command)
        self.assertIn("never", command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn("planning.schema.json", " ".join(command))
        self.assertEqual(kwargs["cwd"], str(ROOT.resolve()))
        self.assertEqual(planner.last_diagnostics.status, ProviderStatus.ONLINE)


if __name__ == "__main__":
    unittest.main()
