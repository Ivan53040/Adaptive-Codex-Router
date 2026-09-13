# Native repository picker

The dashboard repository field now supports a native Windows folder picker.
Because browser file APIs do not expose absolute local paths, the dashboard
handles `POST /api/pick-directory` with tkinter and returns the selected folder.
The selected path is then submitted to the existing router through `POST
/api/run`; planner and routing logic remain in the core CLI.

Evidence: dashboard page contains the Browse control, `/api/summary` remains
healthy after restart, and the dashboard test suite passes.
