"""Shared structured-output prompt for local and Codex planning providers."""

from __future__ import annotations

import json

from ..router.schemas import TaskMetadata


_CONTRACT = """Return one JSON object matching the supplied schema exactly.
Classify the task, identify files that matter, give an ordered implementation plan,
give concrete verification steps, list real risks, and suggest the least expensive
execution tier likely to succeed. The suggestion is advisory: routing policy makes
the final decision. Do not include markdown or commentary outside the JSON object.
Do not modify files. The final JSON object must contain exactly these keys:
task_type, scope, reasoning_complexity, agentic_complexity, ambiguity, risk,
verification_difficulty, context_requirement, expected_task_length, confidence,
number_of_expected_steps, cross_module_dependency, relevant_files,
implementation_plan, verification_steps, risks, suggested_execution_tier.
Finish the reasoning before the output limit, then emit the complete JSON object.
Do not expose chain-of-thought. Reason briefly and spend the remaining output
budget on the complete JSON object."""


def build_planning_prompt(
    prompt: str,
    metadata: TaskMetadata,
    *,
    workspace_context: str | None = None,
    retry: bool = False,
) -> str:
    sections = [_CONTRACT]
    if retry:
        sections.append(
            "The prior response was malformed. Return complete schema-valid JSON only."
        )
    sections.extend(
        [
            "TASK_METADATA\n" + json.dumps(metadata.__dict__, ensure_ascii=False),
            "TASK\n" + prompt,
        ]
    )
    if workspace_context:
        sections.append("WORKSPACE_CONTEXT\n" + workspace_context)
    return "\n\n".join(sections)
