"""b1 runner — wires prompt + tools + runtime."""

from __future__ import annotations

from typing import Any

from agent_runtime import AgentResult, AgentSpec, run_agent
from tracing import Tracer

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MODEL = "gemini-2.5-flash"
MAX_STEPS = 15  # Tally flow needs more: list_sheets + 3 x (sniff + extract) + pan question


def build_spec() -> AgentSpec:
    return AgentSpec(
        name="column_reader",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        max_steps=MAX_STEPS,
    )


async def run_column_reader(
    file_path: str,
    session_id: str,
    tracer: Tracer,
    initial_history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Invoke b1. If resuming after an escalation, pass initial_history."""
    spec = build_spec()
    task = (
        "An expense file has been uploaded. Turn it into normalized expense rows "
        "the calculator can use. For .xlsx files, start by calling list_sheets. "
        "For CSV files, call fingerprint_columns. Emit final JSON when ready."
    )
    return await run_agent(
        spec=spec,
        task=task,
        tracer=tracer,
        initial_history=initial_history,
        tool_context={"file_path": file_path, "session_id": session_id},
    )
