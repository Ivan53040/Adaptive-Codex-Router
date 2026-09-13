# Phase 4 — Four-model benchmark status

Date: 2026-09-08

## Status

The benchmark framework is implemented and verified. Phase 4 data collection is
not complete: the implementation plan requires at least 100 real coding tasks,
while the repository currently contains only two deliberately tiny fixture tasks
for free harness testing. No comparative real-model run was started in this
phase, so there is still no evidence that Adaptive Router saves Codex usage.

## Implemented

- Five strategies: Always Luna High, Always Terra High, Always Sol High, Always
  Astra Low, and Adaptive Router.
- A strict JSONL corpus loader with task ID, prompt, local repository, base ref,
  category, lightweight classifier metadata, optional minimum-model label, and
  objective validation contract.
- Base refs resolved once per process and recorded as commit SHAs.
- A fresh detached Git worktree for every task/strategy pair, followed by guarded
  cleanup unless `--keep-workspaces` is requested.
- Pre-model validation that rejects a task when its objective check already
  passes on the base commit.
- External validation after each attempt using argument arrays and `shell=False`,
  with exit status, duration, and timeout recorded but command output omitted.
- Append-after-each-run JSONL, dataset fingerprints, and `--resume` support.
- Aggregate success, first-attempt success, escalation, attempt, latency,
  distribution, route-quality, token, usage-per-success, and efficiency metrics.
- Direct Adaptive-vs-Sol and Adaptive-vs-Astra comparison fields.
- Separate `mock_estimate` and `codex_jsonl` usage sources. Mock token values do
  not enter reported-token savings.

## Usage safeguards

Real mode requires `--allow-real-execution` and either `--limit N` or `--full`.
The Astra baseline additionally requires `--allow-astra-baseline`. A full run is
blocked until the selected corpus contains at least 100 tasks. `--plan` reports
the minimum and maximum executor calls without authorizing execution.

For a 100-task, five-strategy matrix, the minimum is 500 executor calls plus 100
Adaptive classifier calls. With the current three-attempt limit, the maximum is
700 executor calls. These limits are why the implementation did not silently
start the real benchmark.

## Verification

The two fixture tasks were run across all five strategies in mock mode:

```text
tasks:                  2
strategies:             5
mock executor runs:    10
adaptive classifier:    2 mock calls
successful runs:       10 / 10
real model calls:       0
```

The mock summary correctly leaves real reported-token savings as `null` and
reports only relative estimated-usage comparisons. The complete automated suite
passes 57 tests, including corpus parsing, permission gates, detached-worktree
isolation and cleanup, baseline validation, fixed/adaptive execution, metric
comparison, external command validation, and every earlier Phase 1–3 test.

## Remaining Phase 4 work

1. Collect at least 100 genuine coding tasks with pinned commits and validation
   commands that fail before and pass after a correct implementation.
2. Review category balance and repository licensing/confidentiality.
3. Run a small real pilot with `--limit` and Sol/Adaptive only.
4. Review token and validation integrity before adding Astra or running all five
   strategies.
5. Complete the 100-task matrix and only then evaluate a usage-saving claim.

The corpus format and collection rules are documented in
`benchmarks/README.md`; `benchmarks/phase4_tasks.example.jsonl` is an executable
format example, not benchmark evidence.
