# Phase 3 — Real Codex Executor Results

Date: 2026-09-08

## Outcome

Phase 3 is implemented. The router can invoke the logged-in Codex CLI with the
routed model and reasoning effort, run it in a selected Git working tree, and
capture the final message, exit state, changed files, duration, and available
token usage. The deterministic executor remains available through `--dry-run`.

## Responsibility checklist

| Plan requirement | Result |
|---|---|
| Invoke Codex CLI | Implemented with `codex exec` and prompt over stdin |
| Choose model | Routed model ID passed explicitly |
| Choose effort | Routed reasoning effort passed explicitly |
| Set working directory | Resolved target passed with `--cd` and as process cwd |
| Capture result and exit status | Final-message file, JSONL fallback, and process exit code |
| Capture available usage | Input, cached input, output, and reasoning output tokens |
| Cancellation and errors | Programmatic cancel, Ctrl+C, timeout, launch/non-zero/write-denial failures |
| Astra availability | Existing availability resolver and guarded fallback remain in the shared pipeline |
| Isolate Codex behavior | Real CLI details remain inside `executor/codex.py` |

## Safety and token controls

- Real execution defaults to `workspace-write`, ephemeral state, ignored user
  config, and Codex auto-review approvals.
- `OPENAI_API_KEY` and `CODEX_API_KEY` are removed from child environments.
- Target, CLI, and Git-working-tree checks run before the classifier call.
- Executor infrastructure failures, cancellation, and timeout stop immediately;
  they do not spend another attempt on a stronger model.
- Write-denial text is treated as failure even when the CLI exits with status 0,
  and any partial file changes remain visible in telemetry.
- `--require-changed-files` and `--required-output` provide objective validation
  hooks. Prompt logging remains disabled by default.

## Verification

The automated suite passes 46 tests, including eight executor-boundary tests for
command construction, authentication isolation, usage/file capture, timeout,
Ctrl+C cancellation, programmatic cancellation, non-zero exit, Git preflight,
and zero-exit write denial with and without a partial change.

The final controlled smoke test used a deterministic mock classifier so it
measured only the real executor path:

```text
route:                  gpt-5.6-luna / low
task:                   replace one marker in hello.txt
attempts:               1
result:                 success
changed files:          hello.txt
duration:               28.878 s
input tokens:           59,770
cached input tokens:    51,200
output tokens:          346
reasoning output tokens: 43
```

The file changed from `PHASE3_PENDING` to `PHASE3_OK`, and no escalation ran.

## Issue found during integration

The first Windows smoke run used approvals disabled. Codex returned exit status
0 while reporting that the workspace was read-only, so ordinary validation
mistook it for a capability failure and escalated through three models. That run
used 166,590 input tokens, of which 141,824 were cached.

The executor now uses Codex auto-review for workspace writes and recognizes
explicit write-denial messages as terminal executor failures. Tests cover the
zero-exit edge case so this regression cannot silently trigger paid escalation.

## Decision for Phase 4

Phase 3 proves that routing can drive a real coding executor, but it does not yet
prove token savings. Even the one-line final smoke test reported 8,570 uncached
input tokens after subtracting cached input, in addition to the classifier cost
used by a normal end-to-end run. Phase 4 should compare the complete router
against always-Luna, always-Terra, always-Sol, and always-Astra baselines using
real tasks, first-attempt success, total tokens, cached/uncached tokens, latency,
and escalation cost. No savings claim should be made before that benchmark.
