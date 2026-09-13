# Adaptive Codex Router — Planning Provider Architecture

## Scope

The runtime separates planning from execution-model selection. A planning
provider analyzes the task and repository into one provider-neutral
`PlanningResult`; deterministic `RoutingPolicy` remains the authority that picks
Luna, Terra, Sol, or Astra and its reasoning effort. A planner's suggested tier
is advisory and cannot bypass routing or Astra guardrails.

The default provider is local Qwen3.8-27B served by llama.cpp at
`http://127.0.0.1:8080`. It runs with thinking enabled and high reasoning. Luna
remains available through the logged-in Codex CLI, and `none` preserves an
external-call-free deterministic path.

## Runtime flow

```text
prompt + metadata + target Git working tree
        |
        v
CodexExecutor.preflight       validate target/CLI/Git before planning
        |
        v
PlanningCore                  qwen | luna | auto | none
        |
        +-- auto: Qwen unavailable -> Luna unavailable -> none
        |
        v
PlanningResult                classification + files + plan + checks + risks
        |
        v
RoutingPolicy                 final deterministic model/effort selection
        |
        v
ConfiguredAvailability        explicit Astra -> Sol availability fallback
        |
        v
CodexExecutor                 original task + compact planning handoff
        |
        v
ObjectiveValidator            external success criteria
        |
        +-- success
        |
        v
RoutingPolicy.escalate        guarded, failure-aware retry
        |
        v
TelemetryLogger               planning + execution diagnostics and history
```

## Planning contract

`PlanningProvider.plan(prompt, workspace, metadata)` returns the same
`PlanningResult` regardless of provider. The result contains the existing rich
routing features plus relevant files, ordered implementation and verification
steps, risks, confidence, planner identity, and an optional suggested execution
tier. `RoutingPolicy` consumes this common result directly.

`PlanningCore` owns selection and fallback. It also exposes `public_config()` and
provider statuses (`ONLINE`, `OFFLINE`, `DEGRADED`, `UNKNOWN`) as a stable API for
future CLI, dashboard, and MCP adapters. Selection logic must not be duplicated
in those interfaces.

| Mode | Selection order |
|---|---|
| `qwen` | Qwen, then deterministic `none` if unavailable |
| `luna` | Luna, then deterministic `none` if unavailable |
| `auto` | Qwen, Luna, deterministic `none` |
| `none` | Deterministic classification only |

Planner failure never aborts an otherwise executable coding task. Every skipped
or failed provider is recorded as a fallback reason.

## Qwen local boundary

`QwenLocalPlanner` uses only Python's standard library and llama-server's
OpenAI-compatible API:

- `GET /health` verifies server health.
- `GET /v1/models` verifies that `qwen3.8-27b` is loaded.
- `POST /v1/chat/completions` requests the strict planning JSON schema.
- `chat_template_kwargs.enable_thinking` is `true` and
  `reasoning_effort` is `high`.

The local provider builds a bounded repository snapshot. It excludes VCS data,
dependency trees, caches, build outputs, symlinks, large files, and likely binary
files. File paths plus prioritized text files are included up to the configured
character budget. Local prompt, cached, and completion tokens and latency are
recorded for performance analysis, but they do not consume Codex allowance.

## Luna boundary

`LunaCodexPlanner` uses GPT-5.6 Luna/Low through `codex exec`, ChatGPT login only,
read-only sandboxing, ephemeral state, ignored user configuration/rules, strict
JSON Schema, timeout handling, and one malformed-output retry. API-key variables
are removed. Luna can inspect the selected repository read-only, while its final
message is written to a temporary location outside the repository.

The old `LunaCodexClassifier` remains available only for Phase 2 classifier
calibration. `ClassifierPlanningAdapter` keeps older benchmark injection points
working without making the legacy classifier the production architecture.

## Execution and guardrails

The executor receives the original task plus a compact, explicitly advisory
planning handoff. It remains the only component allowed to modify the target.
Objective validation and the existing escalation ladder are unchanged. Astra
XHigh and Max protections, explicit availability fallback, cancellation,
timeouts, write-denial handling, and terminal infrastructure failures continue
to apply after the planning refactor.

## Phase 5 SWE-bench boundary

Candidate prompts and grading secrets are split. The public manifest contains
the issue and an SHA-256 pointer; a sealed sidecar contains the official test
patch and evaluation fields and is never materialized into `/testbed`. Codex is
rooted at that extracted task directory, and SWE-bench real mode forces approval
policy `never` so an attempted read beyond the workspace cannot be approved.
`SWEbenchDockerWorkspace` extracts an isolated workspace from the reviewed
container image and verifies base-commit ancestry. After execution,
`SWEbenchHarnessValidator` captures a binary Git patch and sends it with the
sealed instance to the official harness. Success is read from its per-task
`report.json`, preserving repository-specific FAIL_TO_PASS/PASS_TO_PASS parsing.

Baseline grading uses a valid no-op marker patch before any model call. Docker,
the official Python package, and images have a separate zero-model doctor; large
image pulls require explicit authorization.

## Telemetry

Each event records planner identity, provider/model/status, fallback reasons,
planning latency and token counts, the common planning result, execution-only
usage, combined usage, route history, validation, and Astra fields. Qwen is
marked `local_inference: true`, allowing later reports to separate local compute
from Codex allowance. Prompt logging remains disabled by default.

## Deferred work

- Supplement the reviewed 100-task SWE-bench slice with genuine large-refactor,
  repository-analysis, and large-context tasks.
- Compare first-attempt success, total Codex allowance, local planning latency,
  fallback rate, and end-to-end success before claiming savings.
- Add thin MCP and dashboard adapters only after CLI selection is stable; both
  must reuse `PlanningCore`.
