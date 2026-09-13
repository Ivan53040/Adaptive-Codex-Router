# Worklog

## 2026-09-13 — Dashboard task submission

Implemented `src/adaptive_codex_router/dashboard.py` as a local read-only metrics
view plus an explicit task submission form. The form validates prompt length,
planner mode, and working directory, then launches the existing
`adaptive_codex_router` CLI in a background subprocess without a shell. Added
job status polling, output capture, README instructions, and a dashboard loader
test. Verified with a `none + dry-run` POST smoke: job completed with exit code
0. Dashboard is available at `http://127.0.0.1:8766`.

## 2026-09-13 — Native repository picker

Added a `Browse…` button to the task form. The local server opens a native
Windows directory picker through `tkinter`, returns the selected absolute path,
and fills the repository field. Verified the dashboard page and summary endpoint
after restart.
