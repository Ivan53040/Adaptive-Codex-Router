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

## 2026-09-13 — Project relocation and CV update

Copied the complete project to `C:\Users\ivank\Desktop\Sideproject\Adaptive-Codex-Router`
and verified 18,055 files / 668,402,310 bytes match the source. The old source
could not be removed because the active Windows workspace holds a directory lock;
it remains as a recovery copy. Initialized the target Git repository on `main`,
excluded `.venv`, runtime artifacts, and JSONL outputs, flattened the fixture
repository, and created commits `a2b37fa` and `93242ce`. Updated the master CV
with an English Adaptive Codex Router project entry and verified six rendered
pages using Word PDF export and Poppler rasterization. GitHub push is blocked by
an invalid `gh` authentication token. GitHub authentication was then refreshed,
the public repository was created, and all local commits were pushed to
`origin/main`.
