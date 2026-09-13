# Phase 4 benchmark corpus

`phase4_tasks.example.jsonl` documents the corpus format and supplies two tiny
fixtures for free mock verification. It is not the required 100-task real
corpus and must not be used to claim model quality or token savings.

Each JSONL row has this shape:

```json
{
  "id": "unique-task-id",
  "prompt": "The coding task given to every strategy",
  "repository": "path/to/local/git/repository",
  "base_ref": "full commit SHA",
  "category": "debugging",
  "minimum_model": "terra",
  "high_value": false,
  "metadata": {
    "files_explicitly_mentioned": 2,
    "tests_requested": true,
    "number_of_expected_steps": 3,
    "cross_module_dependency": true
  },
  "validation": {
    "require_changed_files": true,
    "command": ["python", "-m", "unittest", "-q"],
    "timeout_seconds": 120
  }
}
```

## Corpus rules

- Use a real historical or newly authored coding task with an objective pass/fail
  check; do not manufacture 100 prompt paraphrases.
- Pin `base_ref` to a commit SHA. The runner resolves a moving ref once per
  process, but a SHA makes separate and resumed runs reproducible.
- The validation command must be an argument array, never a shell string. It is
  run with `shell=False`.
- The validation command must fail at the base commit and pass after a correct
  solution. The runner checks the failing baseline before any model call.
- Keep tasks independent. Every strategy receives a detached Git worktree at the
  same resolved commit, and worktrees are removed after each run unless
  `--keep-workspaces` is set.
- Cover the plan categories: simple coding, normal implementation, debugging,
  large refactor, architecture, repository analysis, long agentic work, and
  large-context work.
- Do not place API keys, passwords, proprietary repository contents, or other
  secrets in the dataset. Prompts are omitted from result files unless
  `--log-prompts` is explicitly enabled.

The `minimum_model` label is optional. When supplied, it is used only to measure
under- and over-routing; it does not influence the route selected by the router.

## Real-corpus staging

Use the corpus tool to import a leak-safe, pinned candidate slice from the
official `SWE-bench/SWE-bench_Verified` dataset:

```powershell
python -m adaptive_codex_router.benchmark.corpus import-swebench --limit 100
python -m adaptive_codex_router.benchmark.corpus audit data/swebench_verified_candidates.jsonl
```

After Qwen proposal generation and user-delegated review, finalize and audit the
hash-pinned reviewed manifest:

```powershell
python -m adaptive_codex_router.benchmark.category_finalize
python -m adaptive_codex_router.benchmark.corpus audit data/swebench_verified_reviewed.jsonl
```

The importer verifies the current Hub revision before and after paging through
the Dataset Viewer API. By default it scans all 500 rows and deterministically
round-robins repository/difficulty buckets instead of trusting source row order.
It copies the issue, repository, base commit, container image, source metadata,
test identifiers, and an evaluation-script hash into the candidate manifest.
Gold patch, test patch, hints, and evaluation script body stay out of that
manifest and all model workspaces. Grading-only fields are stored in a sealed
`.validation.jsonl` sidecar; the manifest pins each sidecar row by SHA-256.

Imported rows remain candidates until user-authorized category review. The
finalized `data/swebench_verified_reviewed.jsonl` is the execution manifest.
Its local validation command is empty and provenance declares `swebench_container`.
That backend extracts an isolated `/testbed` from the reviewed image and grades
the resulting Git patch with the official per-repository SWE-bench parser. The
official task report controls pass/fail; the harness process exit code does not.

Before a candidate can enter a claims-producing run, it needs human category
review and successful container/base-commit verification. Check the runtime
without starting any model or pulling an image:

```powershell
python -m adaptive_codex_router.benchmark.phase5 --dataset data/swebench_verified_reviewed.jsonl --workspace-backend swebench_container --validation-assets data/swebench_verified_candidates.validation.jsonl --mode real --limit 1 --check-environment
```

Install the pinned harness with `uv sync --extra phase5-swebench`. Image pulls
remain blocked unless `--allow-image-pull` is explicitly added.

## Phase 5 scenario matrix

`adaptive_codex_router.benchmark.phase5` reuses this corpus, baseline validation,
and detached-worktree isolation. Its default matrix is:

```text
Qwen Planner + Adaptive Router
Luna Planner + Adaptive Router
No Planner + Adaptive Router
No Planner + Always Sol High
No Planner + Always Astra Low
```

Use `--include-planned-sol-controls` to add Qwen + Always Sol and Luna + Always
Sol, which isolates whether an outcome changed because of the planning handoff
or the selected execution route.

Phase 5 groups results into these exact categories: `simple_coding`,
`normal_implementation`, `debugging`, `large_refactor`, `architecture`,
`repository_analysis`, `long_agentic`, and `large_context`. A full real run is
blocked unless at least 100 tasks cover every category.

The primary efficiency formula is success rate divided by average usage. Usage
per successful task is total usage divided by successful tasks. Local Qwen
tokens are reported separately and excluded from Codex allowance totals; its
latency remains part of end-to-end latency.

```powershell
python -m adaptive_codex_router.benchmark.phase5 --mode real --limit 1 --plan
python -m adaptive_codex_router.benchmark.phase5 --mode mock --output data/phase5_results_mock.jsonl
```
