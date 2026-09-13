# Phase 2 Calibration Results

Date: 2026-09-08

## Outcome

The real GPT-5.6 Luna/Low classifier completed all 40 synthetic cases in one
structured batch call. No coding task was executed.

| Metric | Result |
|---|---:|
| Cases completed | 40 / 40 |
| Task-type accuracy | 95% (38 / 40) |
| Exact initial-route accuracy | 95% (38 / 40) |
| Under-routes | 0 |
| Over-routes | 2 |
| Classifier errors | 0 |
| Batch duration | 64.382 s |
| Batch input tokens | 16,931 |
| Cached input tokens | 0 |
| Batch output tokens | 3,275 |

The two route disagreements were conservative:

- `terra_query_performance`: expected Terra, selected Sol/High.
- `sol_repo_refactor`: expected Sol, selected Astra/Medium.

The two task-type disagreements did not change their expected route:

- `terra_ambiguous_login`: expected Unknown, classified Implementation.
- `astra_long_agentic`: expected Architecture, classified Migration.

## Token finding

Separate single-task smoke runs used about 14.3k uncached input tokens each,
despite the application payload being small. This is fixed context supplied by
the Codex CLI agent runtime. Forty sequential classifications would therefore be
roughly 573k input tokens before coding work.

Batching amortized that overhead to one call: 16,931 input and 3,275 output tokens
for all 40 cases. This is suitable for calibration, but normal interactive routing
still pays the per-call fixed context.

## Phase gate

Classifier quality passes the Phase 2 calibration bar: high route accuracy, no
under-routing in this dataset, strict structured output, and no execution side
effects. Raw per-task token efficiency does not yet pass. Before enabling the
real Phase 3 executor, choose one of these mitigations:

1. Add a deterministic fast path and call Luna only for ambiguous tasks.
2. Queue and batch classifications when latency permits.
3. Accept the fixed overhead only if measured usage weighting makes Luna cheaper
   than the higher-tier tokens it avoids.

The checked-in evaluator requires explicit call volume and supports a one-call
batch mode, so further calibration cannot accidentally launch 40 sequential
requests.
