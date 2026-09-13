# Dashboard task submission

The dashboard now accepts coding prompts and forwards them to the existing
planner-aware CLI. This keeps planner selection and routing in the core engine;
the dashboard only collects inputs, starts a background job, and displays its
status/output. The implementation uses standard-library HTTP and subprocess
APIs, limits prompts to 20,000 characters, validates the selected working
directory, and supports Qwen, auto, Luna, none, and dry-run modes.

Evidence: `tests.test_dashboard` passed; the local `none + dry-run` API smoke
completed successfully; the dashboard served `/api/summary` and `/api/jobs`.
