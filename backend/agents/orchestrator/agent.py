"""a1 runner."""

from __future__ import annotations

from typing import Any

from agent_runtime import AgentResult, AgentSpec, run_agent
from tracing import Tracer

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS

MODEL = "gemini-2.5-flash"
# 3 setup turns + ~2 turns per flag group (web_search + ask_user) + apply + finalize.
# With dedup, Tally files typically produce 10-20 groups -> ~45 steps worst case.
MAX_STEPS = 60


def build_spec() -> AgentSpec:
    return AgentSpec(
        name="orchestrator",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
        max_steps=MAX_STEPS,
    )


async def run_orchestrator(
    task: str,
    tracer: Tracer,
    session_id: str,
    initial_history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    spec = build_spec()
    return await run_agent(
        spec=spec,
        task=task,
        tracer=tracer,
        initial_history=initial_history,
        tool_context={"session_id": session_id, "tracer": tracer},
    )
