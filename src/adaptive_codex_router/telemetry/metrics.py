"""Small aggregate metrics used by the mock benchmark and future dashboard."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def summarize(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(events)
    total = len(rows)
    successes = sum(bool(row.get("success")) for row in rows)
    total_usage = sum(float(row.get("estimated_usage") or 0) for row in rows)
    return {
        "tasks": total,
        "success_rate": successes / total if total else 0.0,
        "first_attempt_success_rate": (
            sum(bool(row.get("first_attempt_success")) for row in rows) / total if total else 0.0
        ),
        "escalation_rate": (
            sum(bool(row.get("escalated")) for row in rows) / total if total else 0.0
        ),
        "usage_per_success": total_usage / successes if successes else None,
        "model_distribution": dict(Counter(row.get("selected_model") for row in rows)),
        "effort_distribution": dict(Counter(row.get("selected_effort") for row in rows)),
    }

