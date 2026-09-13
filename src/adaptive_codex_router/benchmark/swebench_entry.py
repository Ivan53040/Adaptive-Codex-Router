"""Launch the pinned official harness with Windows-safe Linux artifact writes.

SWE-bench 5.0.2 writes eval.sh and patch.diff using Path.write_text defaults,
which translate LF to CRLF on Windows. Keep this compatibility fix confined to
the harness subprocess; do not change the installed package or grading logic.
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from unittest.mock import patch

_write_text = Path.write_text


def _write_harness_text(self, data, encoding=None, errors=None, newline=None):
    if self.name in {"eval.sh", "patch.diff"}:
        encoding = "utf-8"
        newline = "\n"
    return _write_text(self, data, encoding=encoding, errors=errors, newline=newline)


def main() -> None:
    if os.name == "nt":
        with patch.object(Path, "write_text", _write_harness_text):
            runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")
    else:
        runpy.run_module("swebench.harness.run_evaluation", run_name="__main__")


if __name__ == "__main__":
    main()
