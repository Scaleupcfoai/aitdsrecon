"""b2 runner — wires prompt + tools + runtime."""

from __future__ import annotations

from typing import Any

from agent_runtime import AgentResult, AgentSpec, run_agent
from tracing import Tracer

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MODEL = "gemini-2.5-flash"
MAX_STEPS = 12


def build_spec() -> AgentSpec:
    return AgentSpec(
        name="tds_calculator",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        max_steps=MAX_STEPS,
    )


async def run_tds_calculator(
    file_path: str | None,
    mapping: dict[str, str] | None,
    tracer: Tracer,
    session_id: str,
    rows: list[dict[str, Any]] | None = None,
    pan_policy: str | None = None,
    initial_history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Invoke b2. Either pass rows (Tally) OR file_path+mapping (flat)."""
    spec = build_spec()
    base_ctx: dict[str, Any] = {"session_id": session_id}
    if rows is not None:
        task = (
            f"{len(rows)} pre-extracted expense rows are ready on the session. "
            f"PAN policy: {pan_policy or 'standard'}. Call calculate_batch, "
            "then emit the small summary JSON described in your prompt."
        )
        tool_ctx = {**base_ctx, "rows": rows, "pan_policy": pan_policy}
    else:
        mapping_str = ", ".join(f"'{k}' -> {v}" for k, v in (mapping or {}).items() if v)
        task = (
            "The uploaded expense file is at the configured path. Column mapping: "
            f"{mapping_str}. Call calculate_batch, then emit the small summary JSON."
        )
        tool_ctx = {**base_ctx, "file_path": file_path, "mapping": mapping}
    return await run_agent(
        spec=spec,
        task=task,
        tracer=tracer,
        initial_history=initial_history,
        tool_context=tool_ctx,
    )
