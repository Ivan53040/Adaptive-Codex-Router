# Adaptive Codex Router

## 1. Project Goal

Build a local wrapper around Codex that uses GPT-5.6 Luna as a lightweight semantic classifier to analyse each coding task, then automatically choose the most usage-efficient GPT model and reasoning effort.

Supported models:

```text
GPT-5.6 Luna
GPT-5.6 Terra
GPT-5.6 Sol
GPT-6 Astra
```

The main objective is:

> Minimise Codex usage on a ChatGPT Plus subscription while maintaining a high task success rate.

The project must work without an OpenAI API key.

Authentication should use the existing Codex CLI login through the user's ChatGPT Plus account.

---

# 2. Core Research Question

The project should answer:

> Can semantic task routing automatically select the optimal model–reasoning pair across Luna, Terra, Sol and Astra to reduce Codex usage while preserving task success?

The objective is NOT:

```text
Choose the strongest model.
```

It is:

```text
Choose the cheapest model + reasoning effort
that is sufficiently likely to complete the task correctly.
```

Conceptually:

\[
(m,e)^* =
\arg\min_{m,e}
E[Usage(m,e,task)]
\]

subject to:

\[
P(success \mid task,m,e) \geq T
\]

where:

```text
m = Luna / Terra / Sol / Astra
e = reasoning effort
T = reliability threshold
```

Initial reliability target:

```text
T ≈ 0.90–0.95
```

Make this threshold configurable.

---

# 3. Core Architecture

Do NOT make MCP the core routing mechanism.

The router must run before the main Codex coding task starts.

Target architecture:

```text
User Prompt
    ↓
Smart Codex Wrapper
    ↓
GPT-5.6 Luna
Low-effort classification
    ↓
Semantic Task Features
    ↓
Deterministic / Adaptive Routing Policy
    ↓
Select:
Model
+
Reasoning Effort
    ↓
Codex executes original task
    ↓
Validation
    ↓
Success → Done

Failure
    ↓
Escalation Policy
    ↓
Stronger / more suitable route
```

The wrapper should invoke Codex CLI rather than directly calling the OpenAI API.

Conceptually:

```bash
codex exec -m <model> ...
```

Authentication:

```text
ChatGPT Plus
    ↓
Codex authentication
    ↓
Smart Codex Wrapper
```

No `OPENAI_API_KEY` should be required.

---

# 4. Why Not MCP First?

MCP runs inside an already active Codex agent session.

For example:

```text
User
 ↓
Sol already running
 ↓
Sol calls Router MCP
 ↓
Router says Luna was sufficient
```

This does not solve the primary optimisation problem because expensive model usage has already started.

Therefore:

```text
Core routing
= external Codex wrapper

MCP
= optional interface later
```

MCP may eventually provide:

- routing statistics
- manual route inspection
- configuration
- usage reports
- benchmark information
- explanation of previous routing decisions

But it should not be responsible for the initial model selection.

---

# 5. Luna's Role

GPT-5.6 Luna acts as the semantic classifier.

Luna must NOT:

- solve the coding task
- inspect the entire repository
- perform code changes
- produce long explanations
- directly invoke the selected model

Luna receives only:

```text
user prompt
+
small lightweight metadata
```

Example metadata:

```json
{
  "files_explicitly_mentioned": 3,
  "tests_requested": true,
  "repository_wide": false,
  "estimated_repo_size": "medium"
}
```

Avoid sending repository contents to Luna.

Otherwise the system may waste usage by having Luna read a large repository and then having the executor read it again.

The classification call should remain extremely small.

---

# 6. Luna Classification Schema

Do NOT primarily ask Luna:

```text
Which model should I use?
```

Instead ask Luna to extract task characteristics.

Example:

```json
{
  "task_type": "debugging",
  "scope": "multi_file",
  "reasoning_complexity": "high",
  "agentic_complexity": "medium",
  "ambiguity": "medium",
  "risk": "medium",
  "verification_difficulty": "high",
  "context_requirement": "medium",
  "expected_task_length": "medium",
  "confidence": 0.91
}
```

Possible `task_type` values:

```text
simple_edit
documentation
test_generation
implementation
refactor
debugging
architecture
repository_analysis
migration
performance
security
unknown
```

Possible `scope`:

```text
single_line
single_file
multi_file
repository
multi_repository
unknown
```

Possible complexity values:

```text
low
medium
high
very_high
```

Possible `context_requirement`:

```text
small
medium
large
very_large
```

The output must be structured JSON only.

No chain-of-thought or long natural-language explanation should be requested.

---

# 7. Separate Classification From Routing

Luna should classify the task.

A separate policy layer should choose the model.

Architecture:

```text
Prompt
 ↓
Luna classifier
 ↓
Semantic task features
 ↓
Routing policy
 ↓
Model + effort
```

Example:

```python
classification = classifier.classify(
    prompt,
    metadata
)

route = policy.select(classification)

executor.run(
    model=route.model,
    effort=route.effort,
    prompt=prompt
)
```

This separation is critical.

Future models should be replaceable without redesigning the Luna classifier.

---

# 8. Model Configuration

Keep model identities in configuration.

Example:

```yaml
models:

  luna:
    model: gpt-5.6-luna
    class: cheap

  terra:
    model: gpt-5.6-terra
    class: balanced

  sol:
    model: gpt-5.6-sol
    class: strong

  astra:
    model: gpt-6-astra
    class: frontier
```

The application should check which models are currently available in Codex.

Do not assume Astra is always available.

If Astra is unavailable:

```text
Astra route
 ↓
fallback
 ↓
Sol
```

Model availability should be detected or configurable.

---

# 9. Model + Reasoning Pair

Routing should select:

```text
model
+
reasoning effort
```

rather than only a model.

Initial candidate set:

```text
Luna Low
Luna Medium
Luna High

Terra Low
Terra Medium
Terra High

Sol Medium
Sol High
Sol XHigh

Astra Low
Astra Medium
Astra High
Astra XHigh
Astra Max
```

However, Astra XHigh and Max are special escalation states.

They must NOT be treated as ordinary initial routes.

Recommended policy:

```text
Normal automatic initial routes:
Luna Low/Medium/High
Terra Low/Medium/High
Sol Medium/High
Astra Low/Medium

Escalation-only:
Sol XHigh
Astra High
Astra XHigh

Exceptional / explicit:
Astra Max
```

The goal is usage efficiency, not maximum capability.

---

# 10. Initial Routing Policy

Start conservatively.

Example initial policy:

| Task | Initial Route |
|---|---|
| Typo / rename / formatting | Luna Low |
| Documentation | Luna Low |
| Simple test generation | Luna Low / Medium |
| Small bounded implementation | Luna High |
| Normal coding task | Terra Medium |
| Multi-file implementation | Terra High |
| Moderate debugging | Terra High |
| Complex debugging | Sol Medium / High |
| Large refactor | Sol High |
| Architecture reasoning | Sol High |
| Large-context agentic task | Astra Low |
| Very difficult repository task | Astra Low / Medium |
| Sol failed on capability grounds | Astra Low |
| Extremely difficult task | Astra Medium initially |

Important:

```text
Astra ≠ automatically highest tier
```

Astra should be selected only when its expected capability-per-usage is better for that task.

Astra High/XHigh/Max should normally be reached through escalation rather than initial classification.

---

# 11. Astra Routing Signals

Astra may be useful when tasks have:

- very large context requirements
- long-running agentic workflows
- many dependent steps
- complex repository exploration
- difficult architecture reasoning
- repeated failure using Sol
- tasks where stronger reasoning may reduce the number of attempts
- tasks where a more capable model may use substantially fewer tokens overall

Add routing signals such as:

```text
context_requirement
expected_task_length
agentic_complexity
number_of_expected_steps
cross_module_dependency
```

The router should learn over time whether Astra actually saves usage for these classes of tasks.

---

# 12. Important Astra Principle

Do NOT assume:

```text
Astra uses fewer tokens
→ therefore Astra is cheaper.
```

Astra may consume Plus allowance faster per unit of computation.

Therefore compare:

```text
Total task usage
```

rather than only:

```text
Output token count
```

Astra may be more usage-efficient when it reduces retries, exploration, or unnecessary intermediate work.

This must be empirically measured.

---

# 13. Escalation

Routing mistakes must be recoverable.

Do NOT simply use:

```text
Luna → Terra → Sol → Astra
```

for every failure.

Escalation should consider the failure type.

Example:

```text
Luna
 ↓
capability failure
 ↓
Terra
```

```text
Terra
 ↓
architecture / reasoning failure
 ↓
Sol
```

```text
Sol
 ↓
large-context / difficult agentic failure
 ↓
Astra
```

Initial simple escalation can be:

```text
Luna
 ↓
Terra
 ↓
Sol High
 ↓
Astra Low / Medium
```

Higher Astra efforts require stronger evidence of genuine difficulty.

Recommended escalation hierarchy:

```text
Luna
 ↓
Terra
 ↓
Sol High
 ↓
Astra Low
 ↓
Astra Medium
 ↓
Astra High
 ↓
Astra XHigh
 ↓
Astra Max
```

However, this should NOT mean every failed task walks through every level.

The router should skip inappropriate steps based on failure type and task characteristics.

---

# 14. Astra XHigh / Max Guardrails

Astra XHigh and Astra Max should be protected because the project's purpose is usage optimisation.

## Astra XHigh

Use only when:

- the task is genuinely high-value or difficult
- lower Astra efforts or Sol have failed
- additional reasoning is likely to materially improve the result

Astra XHigh should be:

```text
escalation only
```

not an ordinary initial route.

## Astra Max

Astra Max should be treated as an exceptional state.

Recommended rules:

```text
automatic_initial_selection: false
require_previous_failure: true
require_high_task_value: true
```

Ideally require explicit user permission:

```bash
smart-codex --allow-max "..."
```

or a config option:

```yaml
astra:
  max:
    automatic: false
    require_previous_failure: true
    require_explicit_permission: true
```

Good Astra Max cases include:

- extremely difficult repository-wide architectural migrations
- persistent distributed/concurrency bugs
- large multi-system tasks with many interacting constraints
- high-value tasks where Sol/Astra lower efforts failed
- complex benchmark or telemetry analysis where multiple hypotheses must be reconciled

Do NOT use Astra Max for ordinary coding simply because the classifier labels a task `very_high`.

---

# 15. Validation Signals

Prefer objective signals:

- tests failed
- build failed
- lint failed
- type checking failed
- requested output missing
- required files unchanged
- explicit executor failure
- acceptance criteria failed
- benchmark/regression failure

Do not automatically escalate only because the model says:

```text
"I am uncertain."
```

Maximum attempts:

```text
max_attempts = 3
```

Make this configurable.

Every escalation must be logged.

---

# 16. Proposed Project Structure

Use Python for the MVP.

```text
adaptive-codex-router/
│
├── src/
│   ├── router/
│   │   ├── classifier.py
│   │   ├── policy.py
│   │   ├── schemas.py
│   │   ├── prompts.py
│   │   └── availability.py
│   │
│   ├── executor/
│   │   ├── codex.py
│   │   └── validator.py
│   │
│   ├── telemetry/
│   │   ├── logger.py
│   │   ├── metrics.py
│   │   └── usage.py
│   │
│   ├── benchmark/
│   │   ├── runner.py
│   │   └── evaluator.py
│   │
│   ├── cli.py
│   └── config.py
│
├── tests/
│   ├── test_classifier.py
│   ├── test_policy.py
│   ├── test_escalation.py
│   ├── test_availability.py
│   └── fixtures/
│
├── benchmarks/
│   └── tasks.jsonl
│
├── data/
│   └── routing_history.jsonl
│
├── config.yaml
├── ARCHITECTURE.md
├── README.md
└── pyproject.toml
```

---

# 17. CLI Experience

Target:

```bash
smart-codex "Fix the authentication bug"
```

Internally:

```text
smart-codex
 ↓
Luna classification
 ↓
routing policy
 ↓
choose model + effort
 ↓
codex exec
 ↓
validation
```

Optional explain mode:

```bash
smart-codex --explain "Fix the authentication bug"
```

Example:

```text
Task:
  debugging

Scope:
  multi-file

Complexity:
  high

Selected route:
  GPT-5.6 Terra
  High reasoning

Astra:
  not justified for expected task scope
```

Do not expose hidden model reasoning.

Only expose classification and routing decisions.

---

# 18. Manual Override

Allow users to bypass routing when desired.

Examples:

```bash
smart-codex --model luna "..."
smart-codex --model terra "..."
smart-codex --model sol "..."
smart-codex --model astra "..."
```

Also:

```bash
smart-codex --effort high "..."
```

For Astra Max:

```bash
smart-codex --model astra --effort max --allow-max "..."
```

This is useful for:

- debugging router behaviour
- benchmarking
- user preference
- comparing models
- exceptional high-value tasks

---

# 19. Telemetry

Record every routing decision.

Example:

```json
{
  "task_id": "abc123",
  "timestamp": "...",

  "task_type": "debugging",
  "scope": "multi_file",

  "classifier_model": "gpt-5.6-luna",

  "selected_model": "gpt-5.6-terra",
  "selected_effort": "high",

  "classifier_confidence": 0.91,

  "success": true,
  "first_attempt_success": true,

  "escalated": false,
  "attempts": 1,

  "input_tokens": null,
  "output_tokens": null,
  "estimated_usage": null,

  "duration_ms": 0
}
```

For Astra also record:

```text
Astra availability
Astra reasoning effort
Astra task duration
whether XHigh/Max was used
why escalation occurred
```

Never log:

- passwords
- API keys
- secrets
- repository contents by default

Prompt logging should be optional.

---

# 20. Benchmark Strategies

Compare at least:

## Baseline A

```text
Always Luna
```

## Baseline B

```text
Always Terra
```

## Baseline C

```text
Always Sol High
```

## Baseline D

```text
Always Astra Low
```

## Experimental

```text
Adaptive Router
```

Optional additional benchmarks:

```text
Always Astra Medium
Always Sol XHigh
```

Astra Max should generally NOT be used as a normal baseline because it is an exceptional route.

Measure:

- overall success rate
- first-attempt success rate
- escalation rate
- under-routing rate
- over-routing rate
- task latency
- total attempts
- model distribution
- reasoning-effort distribution
- token usage where available
- Plus/Codex usage where observable
- estimated usage saving

---

# 21. Important Benchmark Comparison

Astra should specifically be compared against Sol.

Do not assume the answer before benchmarking.

Measure whether Astra can reduce:

- retries
- exploration
- total elapsed work
- usage per successful task

rather than focusing only on raw output tokens.

---

# 22. Luna Router vs Heuristic Router

Also compare:

```text
Heuristic Router
```

against:

```text
Luna Semantic Router
```

Example tricky prompt:

```text
Fix race condition when websocket connections close
during concurrent database writes.
```

A simple heuristic may see:

```text
short prompt
few words
```

and underestimate difficulty.

Luna should ideally identify:

```text
concurrency
race condition
cross-component debugging
high verification difficulty
```

Measure:

```text
routing accuracy
under-routing
over-routing
```

---

# 23. Under-Routing Metric

Under-routing is more dangerous:

```text
Hard task → Luna
```

than over-routing:

```text
Easy task → Terra
```

Create a weighted routing error metric.

Example:

```text
Over-route by 1 tier:
penalty = 1

Under-route by 1 tier:
penalty = 2

Under-route by 2 tiers:
penalty = 5
```

Tune later based on real data.

---

# 24. Phase 1 — Mock MVP

Build only:

- Python CLI
- routing schemas
- deterministic policy
- mocked Luna classifier
- mocked Codex executor
- four-model configuration
- Astra availability flag
- escalation
- telemetry
- unit tests

Do NOT connect real Codex yet.

First prove:

```text
Prompt
 ↓
classification
 ↓
route
 ↓
model + effort
 ↓
execution
 ↓
validation
 ↓
escalation
```

works using mocks.

---

# 25. Phase 2 — Luna Integration

Replace mocked classifier with:

```text
Codex CLI
+
GPT-5.6 Luna
+
Low reasoning
```

Requirements:

- ChatGPT Plus authentication
- no OpenAI API key
- JSON-only output
- tiny context
- error handling
- timeout handling
- malformed JSON recovery

Test approximately:

```text
30–50 synthetic coding tasks
```

---

# 26. Phase 3 — Real Codex Executor

Implement:

```python
class CodexExecutor:
    def execute(
        self,
        prompt,
        model,
        effort,
        working_directory
    ):
        ...
```

Responsibilities:

- invoke Codex CLI
- choose model
- choose effort
- set working directory
- capture result
- capture exit status
- capture available usage metadata
- support cancellation/errors
- support Astra availability

Keep all Codex-specific behaviour isolated here.

---

# 27. Phase 4 — Four-Model Benchmark

Collect at least:

```text
100 real coding tasks
```

Run representative subsets across:

```text
Luna
Terra
Sol
Astra
Adaptive Router
```

Record:

```text
task
classification
selected model
reasoning effort
success
usage
latency
attempts
escalations
validation
```

Main comparison:

```text
Always Sol
vs
Always Astra Low
vs
Adaptive Router
```

---

# 28. Phase 5 — Astra Efficiency Analysis

Analyse whether Astra's token efficiency translates into actual Codex usage efficiency.

Group tasks by:

```text
simple coding
normal implementation
debugging
large refactor
architecture
repository analysis
long agentic task
large-context task
```

For each category compute:

\[
Efficiency =
\frac{SuccessRate}{AverageUsage}
\]

Also compute:

\[
UsagePerSuccessfulTask =
\frac{TotalUsage}{SuccessfulTasks}
\]

This metric is especially useful because a cheap model that repeatedly fails may ultimately cost more than Astra.

---

# 29. Phase 6 — Adaptive Routing

Only implement after enough real data exists.

Use:

```text
Luna semantic features
+
historical outcomes
```

to estimate:

\[
P(success \mid task,m,e)
\]

and:

\[
E(Usage \mid task,m,e)
\]

Then select:

\[
(m,e)^*
=
\arg\min E(Usage)
\]

subject to:

\[
P(success)\geq T
\]

---

# 30. Phase 7 — Optional Learned Router

Only after hundreds of tasks exist.

Possible approaches:

- logistic regression
- gradient boosting
- lightweight classifier
- contextual bandit
- Bayesian optimisation
- learned cost-quality predictor

Inputs:

```text
Luna semantic features
task metadata
historical routing data
```

Outputs:

```text
success probability per route
expected usage per route
```

Do not implement this prematurely.

---

# 31. Phase 8 — Optional MCP Interface

Once the routing engine is stable, expose:

```text
route_task
get_routing_stats
explain_last_route
get_usage_report
get_model_performance
set_policy
```

Architecture:

```text
              ┌─ CLI
              │
Router Core ──┼─ MCP
              │
              └─ Benchmark Runner
```

MCP remains an interface.

It is not the core routing engine.

---

# 32. Recommended Development Workflow & Model Escalation

Use the following sequence when building the project itself.

```text
① GPT-5.6 Sol High
   ↓
Architecture + Mock MVP

② GPT-5.6 Terra High
   ↓
Ordinary implementation

③ GPT-5.6 Sol High
   ↓
Real Codex CLI integration

④ GPT-5.6 Luna / Terra
   ↓
Tests + benchmark framework

⑤ GPT-5.6 Sol High
   ↓
Integration review

⑥ GPT-6 Astra Low
   ↓
Independent architecture review

⑦ GPT-6 Astra High
   ↓
Use only for genuinely unresolved hard problems

⑧ GPT-6 Astra XHigh
   ↓
Use only if Astra High still fails or remains inconclusive

⑨ GPT-6 Astra Max
   ↓
Use only for extremely difficult, high-value tasks
after lower-effort models have already failed
```

### Development principle

Do not start the project with Astra.

Start with:

```text
Sol High
```

because the initial architecture and Mock MVP are difficult enough to benefit from strong reasoning but do not justify Astra-level usage.

Use Terra for the majority of ordinary implementation work.

Use Luna for bounded, repetitive, easily verifiable tasks.

Use Astra primarily as a reviewer or escalation path.

### Astra escalation rules

```text
Astra Low
→ independent review / difficult end-to-end task

Astra High
→ unresolved difficult problem

Astra XHigh
→ escalation only

Astra Max
→ exceptional / explicit only
```

Astra Max should never be selected merely because:

```text
task_complexity = very_high
```

It should normally require:

```text
high task value
+
previous attempts failed
+
strong reason to believe additional reasoning will help
```

The guiding development rule is:

> Use the lowest-cost model and reasoning effort that is likely to complete the current development step successfully.

---

# 33. Future Dashboard

Optional later feature:

```text
Adaptive Codex Router

Tasks today: 47

Luna
██████████████████ 51%

Terra
██████████ 27%

Sol
█████ 14%

Astra
███ 8%

First-attempt success:
95.2%

Escalation rate:
6.4%

Estimated usage reduction vs Always Sol:
43%

Astra tasks:
4
```

This should only be built after telemetry is reliable.

---

# 34. Important Constraints

1. ChatGPT Plus only.
2. No OpenAI API key.
3. Use Codex CLI authentication.
4. Support Luna, Terra, Sol and Astra.
5. Astra availability must be checked.
6. Keep Luna classification calls tiny.
7. Luna must not read the entire repository.
8. Separate semantic classification from routing policy.
9. Route model + reasoning effort together.
10. Keep Codex integration isolated.
11. Never silently escalate to an expensive model.
12. Log every routing and escalation decision.
13. Do not assume Astra is cheaper.
14. Measure usage per successful task.
15. Do not over-engineer the MVP.
16. Do not build MCP first.
17. Do not build machine learning before collecting real data.
18. Astra XHigh is escalation-only.
19. Astra Max is exceptional and preferably requires explicit permission.

---

# 35. Main Success Metrics

The three most important metrics are:

## Task Success Rate

\[
SuccessRate =
\frac{SuccessfulTasks}{TotalTasks}
\]

## Usage Per Successful Task

\[
UsagePerSuccess =
\frac{TotalUsage}{SuccessfulTasks}
\]

## Under-Routing Rate

\[
UnderRoutingRate =
\frac{TasksInitiallySentToInsufficientModel}{TotalTasks}
\]

Secondary metrics:

- first-attempt success rate
- escalation rate
- latency
- average attempts
- Astra selection rate
- model distribution
- effort distribution
- over-routing rate

---

# 36. Desired Final Result

An ideal result may look like:

```text
100 coding tasks

Always Sol High
Success:              96%
Usage:               100%

Always Astra Low
Success:              98%
Usage:               118%

Adaptive Router
Success:              96%
Usage:                55%

Routing:

Luna                  46%
Terra                 29%
Sol                   17%
Astra                  8%

First-attempt success: 93%
Escalation rate:        7%

Usage reduction
vs Always Sol:         45%
```

A strong project conclusion would be:

> Semantic model-and-reasoning routing preserved approximately Sol-level task success while substantially reducing Codex usage by assigning Luna, Terra, Sol and Astra only where each model delivered the best capability-per-usage.

---

# 37. First Codex Task

Start by inspecting the current repository.

If empty:

1. Initialise a Python project.
2. Create the proposed directory structure.
3. Write `ARCHITECTURE.md`.
4. Define semantic classifier schemas.
5. Define `ModelRoute` containing model + reasoning effort.
6. Add Luna, Terra, Sol and Astra model configuration.
7. Add an Astra availability abstraction.
8. Implement the deterministic routing policy.
9. Implement a mocked Luna classifier.
10. Implement a mocked Codex executor.
11. Implement validation.
12. Implement basic escalation across the four models.
13. Add Astra XHigh / Max guardrails.
14. Add telemetry.
15. Write unit tests.
16. Demonstrate complete mocked routing flows for:
   - simple task → Luna
   - normal task → Terra
   - difficult task → Sol
   - large/very difficult task → Astra
   - failed Luna task → escalation
   - Astra Max being blocked without explicit permission
17. Run all tests.

Do NOT integrate the real Codex CLI yet.

Do NOT implement MCP yet.

Do NOT implement adaptive machine learning yet.

At the end, report:

- architecture decisions
- files created
- test results
- model-routing rules
- Astra-specific design decisions
- Astra Max guardrail behaviour
- unresolved questions
- risks
- recommended next step

Stop after the mocked MVP works successfully.