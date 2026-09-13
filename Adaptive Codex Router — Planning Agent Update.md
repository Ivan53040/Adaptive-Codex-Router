# Adaptive Codex Router — Planning Agent Architecture Update

Update the existing project plan with the following architectural change.

The router must NOT hard-code GPT-5.6 Luna or Qwen3.8-27B as the only planning agent.

Instead, introduce a **Planning Agent Provider layer**.

---

# 1. New Planning Architecture

Target architecture:

```text
User Task
   ↓
Smart Codex Router
   ↓
Planning Agent Selector
   ↓
┌────────────────────────────────┐
│ Available Planning Agents      │
│                                │
│ Local Qwen3.8-27B              │
│ GPT-5.6 Luna                   │
│ Future planning providers      │
└───────────────┬────────────────┘
                ↓
          Planning Result
                ↓
       Semantic Task Features
       Relevant Files
       Implementation Plan
       Verification Plan
                ↓
          Routing Policy
                ↓
┌────────┬────────┬───────┬────────┐
│ Local  │ Luna   │ Terra │ Sol    │ Astra
└────────┴────────┴───────┴────────┘
                ↓
            Executor
                ↓
            Validate
                ↓
      Success / Escalation
```

Planning and execution must remain separate concepts.

A planner may recommend an execution route, but the deterministic/adaptive routing policy makes the final model decision.

---

# 2. Planning Provider Interface

Create a common abstraction such as:

```python
class PlanningProvider:
    def plan(
        self,
        prompt,
        workspace,
        metadata
    ) -> PlanningResult:
        ...
```

Initial implementations:

```python
class QwenLocalPlanner(PlanningProvider):
    ...
```

```python
class CodexLunaPlanner(PlanningProvider):
    ...
```

Future providers should be easy to add without changing the routing engine.

Possible future examples:

```text
ChatGPTSolPlanner
OtherLocalModelPlanner
RemotePlanner
HeuristicPlanner
```

Do NOT implement unsupported providers yet.

---

# 3. Qwen Local Planner

Qwen3.8-27B should be the preferred local planning option.

It may use:

```text
LM Studio
→ localhost OpenAI-compatible endpoint
```

The local planner may inspect more repository context than Luna because it does not consume Codex allowance.

Responsibilities may include:

```text
Task understanding
Repository exploration
Relevant-file discovery
Dependency analysis
Implementation planning
Risk analysis
Verification planning
Complexity classification
```

Example output:

```json
{
  "task_type": "debugging",
  "scope": "multi_file",
  "complexity": "high",

  "relevant_files": [
    "src/auth/service.py",
    "src/ws/session.py",
    "src/db/transaction.py"
  ],

  "implementation_plan": [
    "Inspect transaction lifetime",
    "Remove blocking await from locked region",
    "Add concurrency regression test"
  ],

  "verification": [
    "pytest tests/ws/test_concurrency.py"
  ],

  "suggested_execution_tier": "terra",
  "confidence": 0.89
}
```

Do not pass unnecessary raw repository contents to the final Codex executor.

Prefer a compact handoff.

---

# 4. Luna Planner

Keep GPT-5.6 Luna as a supported planning agent.

Luna should normally use smaller context than Qwen.

Use it for:

- comparing local vs cloud planning quality
- fallback when the local model is unavailable
- situations where Luna performs better on a specific task type
- benchmarking
- manual user preference

Example:

```text
Planner:
GPT-5.6 Luna

Reasoning:
Low / Medium
```

Luna planning consumes Codex allowance, so it should not automatically replace the local planner unless policy or user preference requires it.

---

# 5. Planner Modes

Support at least:

```text
qwen
luna
auto
none
```

Meaning:

### `qwen`

Always use local Qwen3.8-27B for planning.

### `luna`

Use GPT-5.6 Luna through Codex for planning.

### `auto`

The router decides which planner to use.

Initial `auto` policy:

```text
If local Qwen is healthy:
→ Qwen

If local Qwen unavailable:
→ Luna

If task is explicitly being benchmarked:
→ selected benchmark planner
```

Do NOT create a complex learned planner-selection policy in the MVP.

### `none`

Skip external planning and send the original task directly to the execution router.

This is important for benchmarks.

---

# 6. CLI Selection

Support:

```bash
smart-codex --planner qwen "..."
```

```bash
smart-codex --planner luna "..."
```

```bash
smart-codex --planner auto "..."
```

```bash
smart-codex --planner none "..."
```

Allow configuration of the default:

```yaml
planning:
  default_provider: qwen
```

---

# 7. Dashboard

Add a future dashboard / control panel.

The dashboard should allow the user to select the default planning agent.

Example:

```text
Adaptive Codex Router

Planning Agent
┌─────────────────────────────┐
│ ● Auto                      │
│ ○ Local Qwen3.8-27B         │
│ ○ GPT-5.6 Luna              │
│ ○ No external planning      │
└─────────────────────────────┘

Local Planner
Qwen3.8-27B
Status: ● Online
Endpoint: LM Studio

Execution Routing
Automatic

Astra Max
Disabled
```

Changing the planner in the dashboard should update configuration used by the CLI/router.

Do NOT duplicate planner-selection logic inside the dashboard.

The dashboard is only a UI over the core configuration and routing engine.

---

# 8. Dashboard Metrics

Eventually show:

```text
Planner Usage

Qwen Local       64%
Luna             21%
No Planner       15%
```

And planner-specific metrics:

```text
Qwen Planner
Planning success:       92%
Execution success:      95%
Avg Codex usage:        0.61x

Luna Planner
Planning success:       95%
Execution success:      96%
Avg Codex usage:        0.74x
```

Important metrics:

- planning latency
- relevant-file precision
- execution success after plan
- first-attempt success
- Codex usage after planning
- planner fallback rate
- planner failure rate

The main comparison should be:

```text
Qwen planning
vs
Luna planning
vs
No external planning
```

---

# 9. Planning Result Schema

Create a common schema independent of planner identity.

For example:

```python
class PlanningResult:
    task_type: str
    scope: str
    complexity: str
    relevant_files: list[str]
    implementation_plan: list[str]
    verification_steps: list[str]
    risks: list[str]
    suggested_execution_tier: str | None
    confidence: float
    planner: str
```

Routing policy must consume `PlanningResult`.

It must not contain Qwen-specific or Luna-specific logic unless absolutely necessary.

---

# 10. Planner Health Checks

Implement provider availability.

Example:

```text
Qwen:
LM Studio reachable?
Model loaded?
Health request successful?

Luna:
Codex authenticated?
Model available?
```

Provider status:

```text
ONLINE
OFFLINE
DEGRADED
UNKNOWN
```

If:

```text
planner = auto
```

and Qwen is offline:

```text
Qwen
 ↓ unavailable
Luna
```

If Luna is also unavailable:

```text
Skip planning
↓
Use deterministic routing
```

Do not fail the entire coding task solely because a planner is unavailable.

---

# 11. MCP Integration

Keep MCP support.

MCP should expose planning functionality in addition to the normal CLI.

Potential tools:

```text
plan_task
list_planners
get_planner_status
set_default_planner
compare_planners
get_planner_metrics
```

Example:

```json
{
  "planner": "qwen",
  "task": "Fix the websocket race condition"
}
```

The MCP layer must call the same `PlanningProvider` interfaces used by the CLI.

Do NOT create separate MCP-only planner implementations.

Architecture:

```text
                   ┌── CLI
                   │
Planning Core ─────┼── MCP
                   │
                   └── Dashboard
```

All three interfaces must reuse the same core routing/planning code.

---

# 12. Important Architectural Principle

Do NOT design:

```text
MCP
→ Qwen
```

as the only path.

Instead:

```text
             ┌─ Qwen
Planner Core ─┼─ Luna
             └─ Future providers

      ↑
 ┌────┼─────┐
CLI  MCP  Dashboard
```

MCP is an interface.

Qwen and Luna are providers.

This keeps the architecture modular.

---

# 13. Updated Optimisation Strategy

The project now optimises two different things:

## Planning cost

Prefer:

```text
Local Qwen
```

when its planning quality is sufficient.

Its Codex allowance cost is effectively:

```text
0
```

for the local planning inference.

## Execution cost

Choose:

```text
Local
Luna
Terra
Sol
Astra
```

based on expected task success and usage.

Overall objective:

\[
\min
(
PlanningUsage +
ExecutionUsage +
RetryUsage
)
\]

subject to:

\[
P(success) \ge T
\]

For local planning:

\[
PlanningUsage_{Codex}(Qwen)=0
\]

but still record:

```text
latency
local inference time
local GPU usage
```

for honest comparison.

---

# 14. Updated Benchmark

Compare:

```text
Qwen Planner + Adaptive Router
```

against:

```text
Luna Planner + Adaptive Router
```

against:

```text
No Planner + Adaptive Router
```

Optional:

```text
Qwen Planner + Always Sol
Luna Planner + Always Sol
No Planner + Always Sol
```

This allows the project to determine whether savings come from:

```text
better planning
model routing
or both
```

---

# 15. Recommended MVP Order

Do NOT build the dashboard first.

Updated implementation order:

```text
① Sol High
   ↓
PlanningProvider architecture
+ Mock MVP

② Terra High
   ↓
QwenLocalPlanner
+ LM Studio integration

③ Sol High
   ↓
CodexLunaPlanner
+ real Codex integration

④ Luna / Terra
   ↓
Planner tests
+ benchmark framework

⑤ Sol High
   ↓
Integration review

⑥ Astra Low
   ↓
Independent architecture review

⑦ Terra
   ↓
Simple dashboard

⑧ Astra High
   ↓
Only unresolved hard problems

⑨ Astra XHigh
   ↓
Escalation only

⑩ Astra Max
   ↓
Exceptional / explicit only
```

---

# 16. Dashboard MVP

Only after CLI planning selection is stable.

Initial dashboard should be deliberately small.

Required controls:

```text
Planning Agent:
[ Auto ▼ ]

Available:
- Auto
- Local Qwen3.8-27B
- GPT-5.6 Luna
- None

Local Qwen status:
Online / Offline

Execution routing:
Automatic

Allow Astra Max:
Off
```

Required metrics:

```text
Tasks today
Planner distribution
Execution model distribution
First-attempt success
Escalation rate
Estimated Codex usage
```

Do not build advanced charts yet.

---

# 17. Updated First Development Task

Modify the existing Mock MVP architecture.

Add:

1. `PlanningProvider` abstraction.
2. `PlanningResult` common schema.
3. `MockQwenPlanner`.
4. `MockLunaPlanner`.
5. planner modes:
   - qwen
   - luna
   - auto
   - none
6. provider availability / health abstraction.
7. automatic fallback from Qwen to Luna.
8. configuration for default planner.
9. CLI `--planner` option.
10. telemetry identifying which planner was used.
11. tests verifying that Qwen and Luna produce equivalent common schemas.
12. tests for planner fallback.
13. tests for `none` mode.
14. keep MCP integration modular but do not implement the full MCP server yet.
15. define dashboard-facing configuration interfaces, but do not build the dashboard yet.

After completing this update, report:

- changed architecture
- new files/classes
- planner-selection behaviour
- fallback behaviour
- unit-test results
- effects on the previous routing design
- recommended next step

Do not implement the dashboard until planner selection works correctly through the CLI.