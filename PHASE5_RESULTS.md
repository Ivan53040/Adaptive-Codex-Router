# Phase 5 — Planner and Astra Efficiency Status

Date: 2026-09-11

## Status

The Phase 5 benchmark, real-corpus importer, sealed grading assets, Docker
workspace boundary, and official SWE-bench harness adapter are implemented.
Real data collection is not complete: 100 genuine candidates are staged,
Qwen High has proposed categories for all of them, and a user-delegated Sol High
review has confirmed the manifest. The one-task Docker/harness baseline and
workspace extraction now work. Qwen was unreachable at the final check, so the
real executor pilot and category supplementation remain incomplete. No
token-saving or model-efficiency conclusion is claimed.

## Implemented scenarios

- Qwen Planner + Adaptive Router
- Luna Planner + Adaptive Router
- No Planner + Adaptive Router
- No Planner + Always Sol High
- No Planner + Always Astra Low
- Optional Qwen/Luna Planner + Always Sol controls

Each local task receives an isolated worktree; each SWE-bench task receives an
isolated `/testbed` extracted from its pinned image. The Phase 4 pre-model
failing-baseline check, objective validation,
append-only JSONL, resume behavior, execution permissions, and Astra permission
gate remain active.

## Metrics

Phase 5 reports overall and per-category:

- success and first-attempt success rate
- escalation and average attempts
- planner fallback and planner failure rate
- provider status and planner-used distribution
- end-to-end and planning latency
- Codex reported tokens
- local Qwen planning tokens, separately
- average usage and usage per successful task
- efficiency: success rate divided by average usage
- planner comparisons and Astra-vs-Sol comparisons

The eight categories are simple coding, normal implementation, debugging, large
refactor, architecture, repository analysis, long agentic work, and large
context. `claims_ready` becomes true only for real results with at least 100
unique tasks, all categories, and at least 100 rows for every required scenario.

## Mock verification

The two fixtures completed the five default scenarios:

```text
tasks:                  2
scenarios:              5
mock scenario runs:    10
successful runs:       10 / 10
real model calls:       0
claims_ready:           false
```

The mock summary intentionally uses weighted mock estimates, not real Codex
tokens. Its apparent relative savings are harness signals only and are not
evidence about Qwen, Luna, Sol, or Astra.

Artifacts:

- `data/phase5_results_mock.jsonl`
- `data/phase5_results_mock.summary.json`
- `data/phase5_results_mock.telemetry.jsonl`

## Safeguarded real execution

A one-task planning-only check reports five initial executor runs, eleven maximum
executor attempts, one Qwen planning call, and one Luna planning call. It starts
no model.

Real execution requires `--allow-real-execution` plus `--limit N` or `--full`.
Because the default matrix contains Astra, it also requires
`--allow-astra-baseline`. A bounded pilot can select `--scenarios qwen_adaptive`
to run only that scenario (one initial executor call, at most three attempts).
This does not disable adaptive route escalation or the Astra-baseline guard.
A full run is blocked until the corpus reaches 100
tasks and covers all eight categories.

For SWE-bench, a planning-only load successfully verifies the candidate-to-
sealed-asset hashes without starting a model. `--check-environment` then checks
Docker, the pinned official harness, and required images. Image downloads need
the separate `--allow-image-pull` authorization. On 2026-09-11 the one-task doctor
completed and the astropy-14369 image was downloaded. The optional SWE-bench
5.0.2 dependencies are installed in `.venv`; the harness interpreter defaults
to the running Python executable, avoiding a different Windows PATH interpreter.

Hidden grading fields remain outside the extracted Codex workspace. SWE-bench
planning remains read-only. Executor runs use `auto-review` with the extracted
`/testbed` as the only workspace-write boundary; hidden grading assets are never
copied into the model workspace.

## End-to-end pilot result (2026-09-13)

The latest bounded pilot completed its model and grading steps:

- Qwen High succeeded in one attempt (`qwen3.8-27b`, 31,506 input tokens,
  12,040 output tokens, 296.530 seconds) and classified the task as debugging.
- Adaptive routing selected Terra High. Terra completed in 774.463 seconds and
  produced changes in the CDS parser, parser table, and two test files.
- Official SWE-bench grading ran for 44.341 seconds but remained unresolved:
  all three FAIL_TO_PASS tests still failed. The candidate patch therefore did
  not solve the task. This report was produced before the committed patch was
  included in patch capture.
- The router escalated to Sol High. That attempt was blocked by the Codex usage
  limit and produced no usable patch. Total recorded Codex usage was 4,395,344
  tokens, mostly cached input across the two attempts.
- A Windows cleanup lock then prevented automatic removal of the extracted
  workspace; cleanup is now best-effort and preserves the result instead of
  aborting summary generation.

The result and summary are in `data/phase5_qwen_pilot_20260913_final.jsonl` and
`data/phase5_qwen_pilot_20260913_final.summary.json`. This is valid evidence
that Qwen planning and Terra execution can run end-to-end, but the recorded
benchmark row is invalid for task quality because its committed patch was not
graded.

## Committed patch verification (2026-09-13)

Terra's commit `f80d42d30` was extracted directly and graded against the pinned
task base. The official SWE-bench harness returned `resolved=true`, exit code 0,
in 49.446 seconds. The patch changes the CDS grammar to make chained division
left-associative, regenerates `cds_parsetab.py`, and adds parser/ASCII reader
regressions. This confirms the model's patch was correct; the earlier unresolved
row was a harness patch-capture bug, not a Terra solution failure.

The validator now captures `git diff --binary <task.base_ref>` after staging,
which includes both ordinary working-tree changes and commits created by the
executor. A cleanup lock remains best-effort and cannot invalidate a completed
grading result.

## Category review

Four resumable Qwen High batches classified all 100 public task statements in
858.791 seconds. The run used 82,412 local input tokens and 40,876 local
completion tokens; none consume Codex allowance. Integrity checks found 100
unique proposals matching the source IDs and no sealed grading fields.

The proposed distribution is 60 debugging, 20 normal implementation, 18 simple
coding, 1 architecture, and 1 long-agentic task. Large refactor, repository
analysis, and large context have zero primary proposals. Eleven tasks are below
0.75 confidence and 45 request repository inspection. This is evidence that the
SWE-bench slice must be supplemented, not artificially rebalanced.

The user-delegated review confirmed 95 proposals and changed 5 bounded
behavior fixes from normal implementation to debugging. The final distribution
is 65 debugging, 15 normal implementation, 18 simple coding, 1 architecture,
and 1 long-agentic task. The reviewed manifest is source/proposal/decision hash
pinned, clears `human_review_required`, and passes corpus integrity audit with no
errors. The three absent categories remain honest blockers.

Artifacts:

- `data/swebench_verified_category_review.jsonl`
- `data/swebench_verified_category_review.summary.json`
- `data/swebench_verified_category_review.md`
- `data/swebench_verified_category_decision.json`
- `data/swebench_verified_reviewed.jsonl`
- `data/swebench_verified_reviewed.summary.json`
- `data/swebench_verified_reviewed.md`

## Real baseline verification (2026-09-11)

The initial run `acr-baseline-b9182a489e8f` was INVALID: Windows newline
translation wrote CRLF into the Linux eval script. The harness returned
`resolved=false` even though tests never ran. It must not count as a baseline.

The compatibility entry point now writes only the harness's `eval.sh` and
`patch.diff` as UTF-8/LF inside the subprocess, without modifying the installed
SWE-bench package or its grading rules. Reports must show applied/parseable
tests and failing FAIL_TO_PASS targets for baseline acceptance. Explicit grader
infrastructure failures, missing reports, and timeouts abort instead of spending
more tokens on model escalation.

The corrected run `acr-baseline-acb14afb52d2` executed the suite:

- Task: `astropy__astropy-14369`
- Pytest: 735 passed, 3 failed (expected target failures)
- Official result: unresolved, with all 3 FAIL_TO_PASS targets failing
- Official PASS_TO_PASS: 731 successful, one ambiguous truncated `...[km` ID
  marked failed. The raw log shows passing `km / s`, `km s-1`, `km*s`, and
  `km**2` cases, plus the expected failing `km/s.Mpc-1` target. The pinned
  grader's result is preserved; no labels or scoring were altered.
- Isolated `/testbed` extraction, Git ancestry check, and cleanup succeeded.
- Regression suite: 98 tests passed.
- No planner or cloud executor was called during this environment/baseline run.

Evidence is retained under `data/swebench_evaluations/` for both runs. The
temporary extraction-probe workspace was removed; the downloaded image remains.

## Next step

Restart the local Qwen llama server at `http://127.0.0.1:8080` (connection was
refused at the final check), then run the one-task `qwen_adaptive` pilot. Do not
silently substitute Luna planning for this comparison. Add genuine tasks for
the three missing categories before any full-corpus efficiency claim.

## Qwen pilot (2026-09-11)

The local server was subsequently restored and the authorized one-task pilot
completed. This is an execution observation, not a savings claim:

- `qwen_adaptive` used `qwen3.8-27b` with `effort=high`; no planner fallback
  occurred.
- Qwen returned a valid plan after 2 response attempts in 578.470 seconds,
  with 60,489 input tokens and 7,850 output tokens. The large context and
  high-reasoning setting are now measured rather than assumed.
- The plan classified the task as debugging and suggested `terra`; adaptive
  routing selected `gpt-5.6-terra/high`.
- Codex executor exited with an infrastructure failure after 2.851 seconds,
  changed no files, and therefore no official task grading was started.
- Result: 0/1 successful; `claims_ready=false`; reported Codex usage was absent.

Artifact: `data/phase5_qwen_pilot.jsonl` with its summary and telemetry sidecar.

The next engineering action is to diagnose the Codex CLI failure and reduce
unnecessary Qwen planning latency/context before repeating this same bounded
pilot. The measured local planning cost remains separate from Codex token usage.

## Executor compatibility investigation (2026-09-11; corrected 2026-09-13)

The earlier claim that `--ask-for-approval` was unsupported was incorrect:
only `codex exec --help` had been checked, but the option is global. The native
`codex.exe --help` on September 13 confirms support for `never`. The executor
now preserves `never` instead of silently mapping it to `--approve-for-me`;
Luna planning also explicitly uses `never`. Workspace-write for execution and
read-only for planning remain in place. Targeted regression tests cover this
distinction. Earlier startup diagnoses from sandboxed smoke tests should not be
treated as proven causes of the user's separate PowerShell runs; the final
September 11 pilot explicitly reported an account usage limit.

## Qwen output fix verified (2026-09-11)

The raw llama-server response showed High reasoning consuming the entire
8,192-token completion budget, leaving `message.content` empty and an
incomplete `reasoning_content`. The planner now uses a 16,384-token completion
budget and states the exact JSON keys in the prompt. A direct live check then
completed successfully in one attempt:

- provider: `qwen3.8-27b`
- reasoning: High; status: online; local inference: true
- planning latency: 106.879 seconds
- input tokens: 1,464 (42 cached); output tokens: 5,945
- parsed task type: debugging
- implementation steps: 1; verification steps: 3
- planner fallback: none

This confirms the Qwen planning provider and output parser are operational. The
full SWE-bench pilot still requires a fresh run after the Codex usage-limit
reset; its previous result must not be reused as Qwen evidence.

## Retry result (2026-09-11)

The retry was later launched after Docker was available, but it did not produce
a valid Qwen comparison:

- Qwen returned invalid planning JSON after its retry and the planner core
  correctly fell back to deterministic `none` planning. The fallback reason was
  `invalid qwen planning output: Expecting value: line 3 column 13 (char 46)`.
- The fallback selected Luna Low for the simple-edit classification.
- Codex executor again exited with infrastructure failure in 3.924 seconds,
  with no changed files and no official grading run.
- Result: 0/1; Qwen planner used: 0; local planning tokens: 0; Codex usage:
  missing. This run must not be treated as a Qwen success or token-savings
  comparison.

The artifact is `data/phase5_qwen_pilot_retry.jsonl` with summary and telemetry.
Attempt telemetry now includes a sanitized executor error field for the next
retry, instead of only an exit code.

The subsequent `phase5_qwen_pilot_fixed` run still used the earlier Qwen request
behavior and recorded the same malformed-output fallback plus a generic Codex
failure. After that run, the Qwen retry path was tightened to remove llama.cpp's
`response_format=json_schema` on the second attempt and the executor now falls
back to stdout when CLI stderr is empty. Run the fixed pilot again before
interpreting planner or executor quality.

## Follow-up fixes (2026-09-11)

The exact Codex error was reproduced with a read-only smoke call:

1. The extracted workspace was not trusted, and Codex exited because
   `--skip-git-repo-check` was missing. The executor now always passes that
   explicit non-interactive flag after its own Git preflight.
2. The shared Codex Desktop state database could not be opened by the child
   process (`failed to initialize in-process app-server client: Access is
   denied`). The executor now prepares an isolated writable `CODEX_HOME` under
   the user's profile and copies only `auth.json`; it does not copy user config,
   sessions, or workspace data. If that optional home cannot be prepared, the
   original environment is preserved and the CLI error remains visible.
3. Qwen parsing now tries both `message.content` and
   `message.reasoning_content`, including text-list content blocks. A malformed
   final channel no longer forces fallback when the reasoning channel contains
   valid schema JSON.

The targeted executor/planner/Phase 5 tests pass 29/29. A read-only smoke with
the isolated runtime passed the previous startup gates but timed out waiting
for the real model request; the full SWE-bench retry still needs to be run after
these fixes.

