"""b3 runner — receives all reference data via parameters from a1."""

from __future__ import annotations

from typing import Any

from agent_runtime import AgentResult, AgentSpec, run_agent
from tracing import Tracer

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MODEL = "gemini-2.5-flash"
MAX_STEPS = 14  # KB + income-check + verify-threshold + research + compose


def build_spec() -> AgentSpec:
    return AgentSpec(
        name="flag_resolver",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        max_steps=MAX_STEPS,
    )


async def run_flag_resolver(
    flag_groups: list[dict[str, Any]],
    vendor_aggregates: dict[str, float],
    pan_policy: str | None,
    file_format: str,
    tracer: Tracer,
    initial_history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Invoke b3. ALL data needed is in parameters — b3 never reads session."""
    spec = build_spec()
    summary_lines = []
    for i, g in enumerate(flag_groups, 1):
        summary_lines.append(
            f"{i}. reason={g['reason']!r} description={g['description']!r} "
            f"row_count={g['row_count']} total_amount={g['total_amount']:.2f} "
            f"sample_vendors={g.get('sample_vendors')} "
            f"current_section={g.get('current_section')!r}"
        )
    task = (
        f"You have {len(flag_groups)} flag groups to resolve.\n"
        f"pan_policy={pan_policy!r}  file_format={file_format!r}  "
        f"vendor_count_in_aggregates={len(vendor_aggregates)}\n\n"
        "Workflow: A check_known_exemptions → B classify_income_vs_expense → "
        "C verify_threshold (for any apply candidate) → D govt vendor check → "
        "E research_descriptions_batch (only if needed) → F compose proposals.\n\n"
        "Flag groups:\n" + "\n".join(summary_lines)
    )
    return await run_agent(
        spec=spec,
        task=task,
        tracer=tracer,
        initial_history=initial_history,
        tool_context={
            "flag_groups": flag_groups,
            "vendor_aggregates": vendor_aggregates,
            "pan_policy": pan_policy,
            "file_format": file_format,
        },
    )
