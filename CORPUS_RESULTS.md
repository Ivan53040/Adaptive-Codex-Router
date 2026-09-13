# Phase 5 real-corpus staging

Status: importer and integrity audit implemented; real execution remains
blocked intentionally.

## Selected seed source

- Dataset: `SWE-bench/SWE-bench_Verified`
- Reviewed Hub revision: `78f471bf655a3137b2e8a75af1501690ec009ec3`
- Size at review: 500 human-validated issue/PR pairs
- Imported default selection: 100 rows chosen after scanning all 500 test rows,
  using deterministic repository/difficulty round-robin sampling
- Candidate manifest SHA-256:
  `e18ef1f67cb941377e12d614e6a857ae2f2c2f639550a6611503af31fbcdc0af`
- Sealed validation asset file SHA-256:
  `fb8fc303dd3be7b440392df8b9074d8b0c0c5f776fcd279a56c19da0ca8e17ff`
- Selected repository coverage: 12 repositories
- Source difficulty distribution: 38 under 15 minutes, 38 from 15 minutes to
  1 hour, 21 from 1 to 4 hours, and 3 over 4 hours
- Evaluation contract in the source: per-task container image plus evaluation
  script and fail-to-pass/pass-to-pass test identifiers

The source is suitable for genuine historical issue-resolution tasks. It is a
seed rather than the complete Phase 5 corpus: semantic coverage is concentrated
in debugging and implementation, so the eight required router categories must
be reviewed and supplemented rather than inferred from the source difficulty
label.

## Safety and reproducibility controls

- The importer rejects a Hub revision that differs from the reviewed SHA and
  checks again after the paginated fetch.
- Each output manifest has its own SHA-256 in the audit sidecar.
- Gold patch, test patch, maintainer hints, and evaluation-script body are not
  copied into the candidate manifest. Official grading inputs live in a sealed
  sidecar outside model workspaces; every manifest row pins its asset SHA-256.
- Full base commits, source row indexes, repository names, container images,
  test identifiers, and evaluation-script hashes remain available for audit.
- Candidate rows stay `uncategorized` and have no local validation command.
  Their declared backend is `swebench_container`, whose official report—not
  the evaluation process exit code—determines resolution.

## Remaining promotion gates

1. Start Docker Desktop's Linux engine and install the pinned optional official
   SWE-bench harness dependency.
2. Materialize each selected image and verify every exact base commit ancestry.
3. Review categories and metadata; supplement SWE-bench where the eight-category
   distribution is not defensible.
4. Prove each baseline validation fails before any model call.
5. Run a very small authorized real pilot before approving the 100-task matrix.

No Codex executor, Astra baseline, or claims-producing Phase 5 run was started
during corpus staging.

The final static audit reports 100 unique tasks, `source_valid=true`,
`manifest_runnable=false`, and `claims_corpus_ready=false`. Validation backend
declaration is no longer a blocker; category/human review and runtime image
verification remain blockers. A direct key scan
found zero copied `patch`, `test_patch`, `hints_text`, or `eval_script` fields.
Docker CLI 29.4.3 is installed on the current machine, but its Linux engine was
not running during this check, so container validation was not attempted.
