# Planning Provider Refactor Results

Date: 2026-09-09  
Version: 0.5.0

## Outcome

The production routing path now uses `PlanningCore` and provider-neutral
`PlanningResult` instead of hard-coding Luna classification. Qwen, Luna, auto,
and no-planner modes are available through configuration and `--planner`.

Selection behavior:

```text
qwen -> Qwen -> none
luna -> Luna -> none
auto -> Qwen -> Luna -> none
none -> deterministic routing features
```

The final execution route is still selected by `RoutingPolicy`; planner tier
suggestions are advisory. Planning output is handed to the executor as a compact
plan, while existing objective validation, escalation, availability handling,
and Astra guardrails remain in force.

## Local Qwen configuration

- Server: `http://127.0.0.1:8080`
- Model: `qwen3.8-27b`
- API: `/v1/chat/completions`
- Thinking: enabled
- Reasoning effort: high
- Maximum planning output: 8,192 tokens
- Timeout: 300 seconds
- Maximum repository snapshot: 240,000 characters

## Real smoke test

A real, planning-only call was run against the small Phase 4 calculator fixture.
It completed in one attempt with no fallback and returned schema-valid task
classification, relevant files, an implementation plan, verification steps,
risks, and a suggested execution tier.

- Duration: 230,706 ms
- Prompt tokens: 320
- Cached prompt tokens: 42
- Completion tokens: 6,810
- Provider status: online
- Local inference: true

These are local inference measurements and do not consume Codex allowance. The
latency is evidence that high reasoning needs the configured 300-second timeout;
it is not yet evidence of end-to-end Codex savings.

## Verification

- Full unit suite: 65/65 passed
- Python compileall: passed
- Real llama-server structured planning: passed
- Qwen -> Luna -> none fallback tests: passed
- Provider-equivalent common-schema tests: passed
- Legacy Phase 2 classifier and Phase 4 benchmark tests: passed

## Next benchmark step

Extend the benchmark matrix to compare Qwen + Adaptive, Luna + Adaptive, and No
Planner + Adaptive. Report local planning latency separately from Codex token
usage, then compare first-attempt success, escalation, total Codex allowance,
and end-to-end success on the same objectively validated corpus.
