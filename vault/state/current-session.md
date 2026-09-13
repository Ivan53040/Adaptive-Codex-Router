# Current session

- Feature: dashboard prompt submission for Adaptive Codex Router.
- Status: implemented and smoke-tested on 2026-09-13.
- Dashboard: `http://127.0.0.1:8766`.
- Read-only metrics endpoint: `/api/summary`.
- Task submission endpoint: `POST /api/run`; jobs endpoint: `/api/jobs`.
- Repository field has a `Browse…` button backed by a native Windows folder
  picker at `POST /api/pick-directory`.
- The dashboard starts the existing CLI with `shell=False`; it does not contain
  separate planner or routing logic.
- Full SWE-bench claims remain blocked by the corpus and real-matrix gates.
