<div align="center">

<img src="docs/media/logo.svg" alt="Adaptive Codex Router logo" width="130">

# Adaptive Codex Router

**Plan locally. Route smartly. Pay only for the reasoning you need.**

A usage-aware wrapper for the Codex CLI. It plans each coding task first, on a
local Qwen model by default, then sends it to the cheapest Codex model and
reasoning effort that is likely to succeed.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Runtime dependencies: 0](https://img.shields.io/badge/runtime%20deps-0-22c55e)](pyproject.toml)
[![Version 0.5.3](https://img.shields.io/badge/version-0.5.3-818cf8)](pyproject.toml)
[![Default planner: local Qwen3.8-27B](https://img.shields.io/badge/planner-local%20Qwen3.8--27B-0d9488)](ARCHITECTURE.md#qwen-local-boundary)
[![Savings claims: not yet](https://img.shields.io/badge/savings%20claims-not%20yet-f59e0b)](#-project-status)

[Intro video](#-watch-the-intro) ·
[Quick start](#-quick-start) ·
[How it works](#-how-it-works) ·
[Evidence](#-benchmarks-and-evidence) ·
[Architecture](ARCHITECTURE.md)

</div>

## 🎬 Watch the intro

https://github.com/user-attachments/assets/a71b32ff-165e-4f11-8215-4b00d405eeba

<sub>2:14 · English voice-over · burned-in English subtitles ·
subtitle files: [SRT](docs/media/adaptive-codex-router-intro.en.srt) /
[VTT](docs/media/adaptive-codex-router-intro.en.vtt) ·
player not loading? [download the MP4](docs/media/adaptive-codex-router-intro.mp4) ·
[how the video is made](docs/video/README.md)</sub>

<details>
<summary><b>Read the transcript</b></summary>

> Not every coding task needs the most powerful model. A typo fix and a
> cross-module race condition are very different jobs, yet most workflows send
> both to the same expensive tier.
>
> Meet Adaptive Codex Router: a local, usage-aware wrapper for the Codex CLI. It
> plans every task first, then routes it to the cheapest model and reasoning
> effort that is likely to succeed.
>
> **Step one: plan.** A local Qwen3.8-27B model analyzes your repository, so
> planning spends none of your Codex allowance. It returns a structured plan:
> task type, relevant files, implementation steps, risks, and verification. If
> the local model is offline, auto mode falls back to Luna, then to a
> deterministic classifier. A planner failure never blocks your coding task.
>
> **Step two: route.** A deterministic policy picks the model and reasoning
> effort across four tiers: Luna, Terra, Sol, and Astra. A typo goes to Luna on
> low. A new feature gets Terra on medium. A tricky race condition goes to Sol on
> high. Planners can only suggest a tier. The policy decides, and Astra's most
> expensive settings stay behind explicit guardrails.
>
> **Step three: execute and verify.** The chosen model edits your Git working
> tree in a sandbox, and objective checks decide whether it really succeeded. If
> it fails, the router looks at why and escalates to a stronger route, with up
> to three attempts by default.
>
> Every run is logged as privacy-conscious telemetry, and prompts stay out of
> the logs unless you opt in. A local dashboard shows tokens, latency, models,
> and attempts as they happen.
>
> And the project stays honest about evidence. On forty calibration tasks,
> routing was 95% exact, with zero under-routes. A SWE-bench Verified harness is
> ready, but no savings are claimed until at least one hundred real tasks are
> measured.
>
> Adaptive Codex Router. Plan locally, route smartly, and pay only for the
> reasoning you need.

</details>

## 💡 Why

A one-line typo fix and a cross-module race condition need very different
amounts of model power. Sending both to the strongest tier burns allowance on
work a cheaper model would finish. The router picks a route per task instead.
These are real `--explain` results from the deterministic planner:

| Task | Route chosen | Why |
|---|---|---|
| `Fix a typo in README.md` | **Luna** · low | bounded low-complexity edit |
| `Implement pagination for the user list` | **Terra** · medium | normal coding task, balanced route |
| `Debug a complex race condition across multiple modules` | **Sol** · high | high reasoning complexity or high-risk task type |

If a route fails, the router escalates (for example `luna/low -> terra/medium`)
instead of starting at the most expensive model.

## 🧭 How it works

![Adaptive Codex Router system flow](docs/adaptive-codex-router-flow.svg)

1. **Preflight.** Check the target Git working tree and Codex CLI before any
   inference is spent.
2. **Plan.** A planner (local Qwen by default) turns the prompt into a
   provider-neutral `PlanningResult`: classification, relevant files, steps,
   verification, risks, and an advisory tier.
3. **Route.** The deterministic `RoutingPolicy` picks the model and reasoning
   effort. A planner's suggestion never bypasses the policy or the Astra
   guardrails.
4. **Execute and validate.** The selected model edits the working tree in a
   workspace-write sandbox; objective checks decide success.
5. **Escalate.** Failures are classified and retried on a stronger route, up to
   three attempts by default.
6. **Record.** Planning and execution telemetry is written as JSONL.

### The model ladder

| Tier | Model | Class | Reasoning efforts |
|---|---|---|---|
| 🔵 **Luna** | `gpt-5.6-luna` | cheap | low · medium · high |
| 🟣 **Terra** | `gpt-5.6-terra` | balanced | low · medium · high |
| 🟡 **Sol** | `gpt-5.6-sol` | strong | medium · high · xhigh |
| 🔴 **Astra** | `gpt-6-astra` | frontier | low · medium · high · xhigh 🔒 · max 🔒 |

🔒 Astra XHigh is escalation-only and needs a high-value task. Astra Max is never
chosen automatically as a first route and needs `--allow-max` plus
`--high-value`. Model availability and the Astra-to-Sol fallback are
configurable in [`config.yaml`](config.yaml).

## ✨ What works now

| Area | Highlights |
|---|---|
| 🧠 **Planning** | Local Qwen3.8-27B via llama-server (thinking on, high reasoning) or GPT-5.6 Luna/Low via `codex exec`; `qwen`, `luna`, `auto`, and `none` modes with automatic fallback |
| 🧭 **Routing** | Deterministic model + effort selection across four tiers, availability fallback, failure-aware escalation, manual overrides, explain mode |
| 🛡️ **Safety** | Git preflight, workspace-write sandbox, ChatGPT login only, Astra XHigh/Max guardrails, terminal handling of infrastructure failures |
| ✅ **Validation** | Objective result checks decide success, not the model's own report |
| 📈 **Observability** | Privacy-conscious JSONL telemetry, token/latency capture, aggregate metrics, a local live dashboard |
| 🧪 **Evaluation** | 40-case calibration set, five-strategy coding benchmark, and a SWE-bench Verified harness with sealed grading data |

<details>
<summary><b>Full feature list</b></summary>

- A provider-neutral `PlanningResult` with classification, relevant files,
  implementation steps, verification, risks, and an advisory execution tier.
- Local Qwen3.8-27B planning through llama-server with thinking enabled and high
  reasoning, plus GPT-5.6 Luna/Low planning through `codex exec`.
- `qwen`, `luna`, `auto`, and `none` modes. `auto` falls back Qwen -> Luna ->
  deterministic routing, and planner failure never aborts the coding task.
- Real routed coding execution with the selected model and reasoning effort.
- ChatGPT authentication only; API-key variables are removed from Codex calls.
- Strict JSON Schema output, timeout handling, and one malformed-output retry.
- A bounded repository snapshot for Qwen and read-only repository access for Luna.
- Git-working-tree preflight before planning, avoiding inference when the
  execution target is invalid.
- A workspace-write executor with ephemeral state and isolated user config.
- Exit status, final message, changed files, latency, cached input, output, and
  reasoning-token capture when the CLI reports them.
- Cancellation, timeout, launch-failure, and write-denial handling. Executor
  infrastructure failures are terminal and do not trigger a model escalation.
- Deterministic routing across Luna, Terra, Sol, and Astra.
- Model plus reasoning-effort selection.
- Configurable model availability and Astra-to-Sol fallback.
- Failure-aware escalation with a configurable three-attempt default.
- Astra XHigh/Max guardrails.
- Objective result validation.
- Privacy-conscious JSONL telemetry and aggregate metrics.
- Manual model/effort overrides and explain mode.
- A 40-case classifier/routing calibration dataset and evaluator.
- A resumable five-strategy coding benchmark with detached Git worktrees,
  pre-model baseline checks, external validation commands, and real/mock usage
  separation.

</details>

## 🚀 Quick start

Python 3.11 or newer is required, and the runtime uses only the standard
library. On this Windows workspace, Python is managed by `uv`, so the
no-install command is:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$env:PYTHONPATH = "$PWD\src"
uv run --no-project --python 3.12 python -m adaptive_codex_router --explain "Fix a typo in README.md"
```

If `smart-codex` has been installed from this project, the equivalent command is:

```powershell
smart-codex --explain "Fix a typo in README.md"
```

> [!IMPORTANT]
> The default run makes a local Qwen high-reasoning planning call and then lets
> the selected coding model modify the target Git working tree. Always point
> `--working-directory` at the intended repository. Use `--dry-run` to keep real
> planning and routing but prevent file changes, or combine
> `--planner none --dry-run` for a completely offline deterministic run.

### Exercise the flows

```powershell
python -m adaptive_codex_router --working-directory C:\path\to\repo --require-changed-files "Fix the typo in README.md"
python -m adaptive_codex_router --dry-run --explain "Implement pagination for the user list"
python -m adaptive_codex_router --planner auto --dry-run --explain "Debug a complex race condition across multiple modules"
python -m adaptive_codex_router --planner none --dry-run --mock-fail luna --explain "Fix a typo in README.md"
python -m adaptive_codex_router --planner none --dry-run --model astra --effort max "Architecture for a critical system"
```

The fourth command makes only Luna fail and shows the explicit Terra escalation.
The fifth command is expected to exit with code 2 because Astra Max was not
authorized. A deliberate manual Max run requires both flags:

```powershell
python -m adaptive_codex_router --planner none --dry-run --model astra --effort max --high-value --allow-max "Architecture for a critical system"
```

To simulate missing Astra availability:

```powershell
python -m adaptive_codex_router --planner none --dry-run --astra-unavailable --explain "Migrate the entire repository architecture; this is a very difficult multi-system task"
```

## 🧠 Planning input

All providers receive the prompt, target workspace, and small metadata. Qwen is
sent a bounded text snapshot of the repository; Luna receives read-only Codex
access to the target. `none` reads no repository content.

![Planner selection and fallback](docs/planner-fallback-flow.svg)

```powershell
python -m adaptive_codex_router --metadata-json '{"files_explicitly_mentioned":3,"tests_requested":true,"cross_module_dependency":true}' "Implement the requested feature"
```

## ⚙️ Configuration

`config.yaml` contains the default planner, Qwen llama-server URL/model/context
and timeout settings, Luna fallback settings, executor sandbox/approval policy,
model IDs, supported efforts,
availability, guardrails, maximum attempts, reliability target, and telemetry
settings. Its contents use JSON syntax, which is valid YAML 1.2; this keeps the
runtime dependency-free with Python's standard library.

Prompts are not logged unless `telemetry.log_prompts` is explicitly enabled.
Runtime telemetry is written to `data/routing_history.jsonl` and ignored by Git.
Real executor events record the token fields exposed by Codex JSONL. The
`estimated_usage` field is used only by the mock and is not real Codex allowance.

## 📈 Local dashboard

The dependency-free dashboard reads Phase 5 JSONL artifacts from `data/` and
refreshes every five seconds. It shows task success, planner/model distribution,
latency, Codex tokens, local Qwen tokens, attempts, and stop reasons:

```powershell
Set-Location 'C:\Users\ivank\Desktop\Adaptive-Codex-Router'
.\.venv\Scripts\python.exe -m adaptive_codex_router.dashboard
```

Open [http://127.0.0.1:8766](http://127.0.0.1:8766) (or use `--port 8765` when
available). Use `--data-dir <path>` to observe another results directory.
The dashboard also has a task form: choose a planner, enter a Git repository
path, or click `Browse…` to use the native Windows folder picker, and submit a
prompt. It launches the existing CLI in a background job; the job status and
output appear below the metrics. The browser cannot expose absolute paths by
itself, so the picker is provided by the local dashboard process.

## 🧪 Tests

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$env:PYTHONPATH = "$PWD\src"
uv run --no-project --python 3.12 python -m unittest discover -s tests -v
```

The suite covers Qwen's HTTP boundary, Luna's Codex subprocess boundary,
provider schema equivalence and fallback, authentication isolation, strict
output parsing, file detection, cancellation, timeouts, terminal
infrastructure failures, all four initial routes, availability fallback,
escalation, guardrails, validation, telemetry, and calibration metrics.

## 📊 Benchmarks and evidence

| Stage | Status | Details |
|---|---|---|
| Classifier calibration | ✅ 95% exact-route accuracy on 40 tasks, zero under-routes | [PHASE2_RESULTS.md](PHASE2_RESULTS.md) |
| Real executor smoke test | ✅ One Luna/Low attempt succeeded | [PHASE3_RESULTS.md](PHASE3_RESULTS.md) |
| Five-strategy coding benchmark | 🛠️ Harness ready, no real matrix run yet | [PHASE4_RESULTS.md](PHASE4_RESULTS.md) |
| Planner and Astra efficiency | 🛠️ 100 SWE-bench Verified tasks reviewed; real pilot pending | [PHASE5_RESULTS.md](PHASE5_RESULTS.md) |

### Classifier calibration

![Classifier calibration modes](docs/classifier-calibration.svg)

The checked-in dataset contains 40 synthetic tasks. A mock run is free and useful
for verifying the harness:

```powershell
python -m adaptive_codex_router.benchmark.evaluator --classifier mock
```

A real sequential run makes one Luna/Low Codex call per case, writes no prompt
into its result file, stops on the first classifier error, and never invokes a
coding executor. Start with a small sample:

```powershell
python -m adaptive_codex_router.benchmark.evaluator --classifier codex --limit 3
```

For full calibration, batch all 40 tasks into one Luna call so the fixed CLI
context is paid once:

```powershell
python -m adaptive_codex_router.benchmark.evaluator --classifier codex --batch
```

The completed reference run achieved 95% task-type accuracy and 95% exact-route
accuracy, with zero under-routes and two conservative over-routes. It used 16,931
input and 3,275 output tokens for the whole batch.

The real sequential evaluator refuses an unbounded run. Use `--full` only when
you intentionally authorize 40 separate calls. Current measurements show
about 14.3k uncached input tokens per classifier call even with the tiny task
payload, because `codex exec` supplies its own fixed agent context. A full run
would therefore consume roughly 573k input tokens before any coding execution.
That overhead is a Phase 2 go/no-go metric, not something to hide.

### Phase 4 coding benchmark

The five strategies are Always Luna High, Always Terra High, Always Sol High,
Always Astra Low, and Adaptive Router. Every real run receives a detached Git
worktree at the same resolved commit. A task's external validation command must
fail at that base commit before any model runs and pass after a valid solution.

![Phase 4 coding strategy comparison](docs/phase4-strategy-matrix.svg)

<details>
<summary><b>Phase 4 commands</b></summary>

Inspect the planned call volume without executing models:

```powershell
python -m adaptive_codex_router.benchmark.runner --mode real --limit 1 --strategies sol adaptive --plan
```

Exercise the full matrix with deterministic mocks:

```powershell
python -m adaptive_codex_router.benchmark.runner --mode mock --output data/phase4_results_mock.jsonl
```

A limited real run requires explicit volume authorization:

```powershell
python -m adaptive_codex_router.benchmark.runner --mode real --limit 1 --strategies sol adaptive --allow-real-execution --output data/phase4_results_sample.jsonl
```

</details>

Adding the Astra baseline also requires `--allow-astra-baseline`. A `--full` real
run is rejected until the dataset contains at least 100 tasks. Results append as
JSONL after each completed strategy and can be continued with `--resume`; a JSON
summary reports success, first-attempt success, escalation, attempts, latency,
model/effort/category distributions, routing quality, cached/uncached token use,
usage per success, efficiency, and Adaptive-vs-Sol/Astra savings.

See [benchmarks/README.md](benchmarks/README.md) and
[benchmarks/phase4_tasks.example.jsonl](benchmarks/phase4_tasks.example.jsonl)
for the corpus contract. The two checked-in fixture tasks are only for harness
verification and are not evidence of real model performance.

### Phase 5 planner and Astra efficiency

Phase 5 adds a scenario matrix over the Phase 4 task/worktree safeguards. The
default scenarios are Qwen/Luna/None + Adaptive, plus No Planner + Sol High and
No Planner + Astra Low. This separates planner effects from routing and retains
the original Astra efficiency comparison.

![Phase 5 planner and routing matrix](docs/phase5-benchmark-matrix.svg)

![Validation and evidence gate](docs/validation-evidence-gate.svg)

Add Qwen/Luna + Always Sol controls with `--include-planned-sol-controls`.
Real runs require `--allow-real-execution`, a bounded `--limit` or explicit
`--full`, and `--allow-astra-baseline`. Full runs require at least 100 tasks and
all eight planned categories. The summary reports success, first-attempt
success, escalation, planner failure/fallback, planning latency, local planning
tokens, Codex usage, usage per successful task, and efficiency overall and by
category. `claims_ready` remains false until the real evidence requirements are
met.

<details>
<summary><b>Phase 5 commands: plan, mock, and corpus import</b></summary>

Inspect the real call volume without running a model:

```powershell
python -m adaptive_codex_router.benchmark.phase5 --dataset data/swebench_verified_reviewed.jsonl --workspace-backend swebench_container --validation-assets data/swebench_verified_candidates.validation.jsonl --mode real --limit 1 --plan
```

Run the free mock matrix:

```powershell
python -m adaptive_codex_router.benchmark.phase5 --mode mock --output data/phase5_results_mock.jsonl
```

Start real-corpus preparation with the pinned SWE-bench Verified importer. It
creates a source-valid candidate manifest without copying gold patches or
pretending the container evaluation script is a local Windows test command:

```powershell
python -m adaptive_codex_router.benchmark.corpus import-swebench --limit 100
python -m adaptive_codex_router.benchmark.corpus audit data/swebench_verified_candidates.jsonl
```

See [benchmarks/README.md](benchmarks/README.md) for the promotion blockers and
the stronger Git/claims audit.

</details>

<details>
<summary><b>Phase 5 commands: SWE-bench harness, pilot, and category review</b></summary>

The importer also writes a sealed `.validation.jsonl` sidecar for the official
SWE-bench harness. It includes grading-only test data that is never copied into
the model workspace, and each manifest row pins the matching asset hash. Install
the optional pinned harness and run the zero-model environment doctor:

```powershell
uv sync --extra phase5-swebench
.\.venv\Scripts\python.exe -m adaptive_codex_router.benchmark.phase5 --dataset data/swebench_verified_reviewed.jsonl --workspace-backend swebench_container --validation-assets data/swebench_verified_candidates.validation.jsonl --mode real --limit 1 --check-environment
```

The doctor checks the Docker Linux engine, official harness, and required
images. Missing images are reported but never pulled unless
`--allow-image-pull` is supplied explicitly.

Once Qwen and the environment are ready, a bounded pilot can run only Qwen
planning plus adaptive execution (at most three executor attempts):

```powershell
.\.venv\Scripts\python.exe -u -m adaptive_codex_router.benchmark.phase5 --dataset data/swebench_verified_reviewed.jsonl --workspace-backend swebench_container --validation-assets data/swebench_verified_candidates.validation.jsonl --mode real --limit 1 --scenarios qwen_adaptive --allow-real-execution --output data/phase5_qwen_pilot.jsonl
```

`--scenarios` filters the enabled matrix; its default remains all scenarios.
Selecting `none_astra` still requires `--allow-astra-baseline`. Adaptive routing
and its escalation policy are unchanged. A pilot is not evidence of savings.
On Windows, the adapter preserves UTF-8/LF for Linux grading artifacts. Baseline
acceptance requires executed failing target tests, not just `resolved=false`.
SWE-bench execution uses the global `--ask-for-approval never` option with
workspace-write isolation; it must not be silently changed to automatic approval.

Generate a resumable Qwen High category proposal without exposing sealed
grading data:

```powershell
python -m adaptive_codex_router.benchmark.category_review --batch-size 25
```

This writes JSONL proposals, a distribution summary, and a Markdown confirmation
checklist. Qwen labels are advisory and never clear `human_review_required`.

Apply a hash-pinned, user-delegated review decision without overwriting the Qwen
proposal artifact:

```powershell
python -m adaptive_codex_router.benchmark.category_finalize
python -m adaptive_codex_router.benchmark.corpus audit data/swebench_verified_reviewed.jsonl
```

The checked-in decision record confirms 95 proposals and modifies 5 from
`normal_implementation` to `debugging`. The resulting reviewed manifest clears
the review gate while retaining the suggested category, final category,
reviewer, authority, timestamp, and decision hash in provenance.

</details>

## 📚 Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Planning providers, routing, execution boundaries, and telemetry |
| [PHASE2_RESULTS.md](PHASE2_RESULTS.md) | Classifier calibration |
| [PHASE3_RESULTS.md](PHASE3_RESULTS.md) | Real-executor verification |
| [PHASE4_RESULTS.md](PHASE4_RESULTS.md) | Benchmark-framework status |
| [PLANNING_PROVIDER_RESULTS.md](PLANNING_PROVIDER_RESULTS.md) | Provider refactor and real local-Qwen smoke test |
| [PHASE5_RESULTS.md](PHASE5_RESULTS.md) | Planner/Astra efficiency framework and its mock verification |
| [CORPUS_RESULTS.md](CORPUS_RESULTS.md) | SWE-bench Verified corpus staging and integrity audit |
| [benchmarks/README.md](benchmarks/README.md) | Corpus contract, promotion blockers, and claims audit |

## 🧾 Project status

> [!NOTE]
> Phase 3's controlled real-executor smoke test succeeded in one Luna/Low
> attempt, but consumed 59,770 input tokens (51,200 cached) for a one-line edit.
> Phase 4's harness is now ready, but no real comparative matrix has been run.
> Do not claim usage savings until at least 100 objectively validated real
> tasks are collected and executed across the required baselines.
