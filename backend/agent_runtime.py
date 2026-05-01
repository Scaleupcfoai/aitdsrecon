"""ReAct agent loop using Gemini function-calling.

An AgentSpec bundles:
  - system prompt
  - tool registry (name -> callable + JSON schema)
  - max reasoning steps
  - model id

`run_agent` drives the loop:
  1. Seed chat with the task message.
  2. Call Gemini with tools. Receive either text or function_calls.
  3. If function_calls: execute each via the tool registry, send results back.
  4. Repeat until the model emits text (final answer) or max_steps hit.

Escalations (ask_orchestrator, ask_user) are just tools. The tool handler can
pause the loop by raising `EscalationRequest` — the outer orchestrator handles
the round-trip, then resumes the loop with the answer injected as the tool
result.

Every LLM call and every tool call is written to the session trace.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from llm_client import generate_with_tools
from tracing import Tracer


ToolFn = Callable[[dict[str, Any]], Awaitable[Any] | Any]


class EscalationRequest(Exception):
    """Raised by a tool to pause the loop and hand control to the caller.

    Carries structured payload the outer orchestrator can act on.
    """

    def __init__(self, kind: str, payload: dict[str, Any]):
        self.kind = kind
        self.payload = payload
        super().__init__(f"escalation: {kind}")


class MaxStepsExceeded(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn


@dataclass
class AgentSpec:
    name: str                       # "orchestrator" | "column_reader" | "tds_calculator"
    model: str
    system_prompt: str
    tools: list[ToolSpec]
    max_steps: int = 10

    def tool_registry(self) -> dict[str, ToolSpec]:
        return {t.name: t for t in self.tools}

    def gemini_tool_declarations(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self.tools
        ]


@dataclass
class AgentResult:
    final_text: str | None = None
    escalation: EscalationRequest | None = None
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    steps_used: int = 0


async def run_agent(
    spec: AgentSpec,
    task: str,
    tracer: Tracer,
    initial_history: list[dict[str, Any]] | None = None,
    tool_context: dict[str, Any] | None = None,
) -> AgentResult:
    """Drive one agent to completion or escalation.

    `initial_history` allows resuming a suspended loop (for escalation returns).
    `tool_context` is passed to every tool as kwargs; used for session_id etc.
    """
    registry = spec.tool_registry()
    history: list[dict[str, Any]] = list(initial_history or [])
    if not history:
        history.append({"role": "user", "parts": [{"text": task}]})

    ctx = tool_context or {}

    for step in range(spec.max_steps):
        tracer.write({
            "t": time.time(),
            "event": "llm_call_start",
            "agent": spec.name,
            "step": step,
        })

        response = await generate_with_tools(
            model=spec.model,
            system_prompt=spec.system_prompt,
            history=history,
            tool_declarations=spec.gemini_tool_declarations(),
            tracer=tracer,
            agent_name=spec.name,
        )

        tracer.write({
            "t": time.time(),
            "event": "llm_call_done",
            "agent": spec.name,
            "step": step,
            "text": response.text,
            "function_calls": [{"name": fc["name"], "args": fc["args"]} for fc in response.function_calls],
        })

        # Append the model's turn to history so subsequent turns see it.
        model_parts: list[dict[str, Any]] = []
        if response.text:
            model_parts.append({"text": response.text})
        for fc in response.function_calls:
            model_parts.append({"function_call": {"name": fc["name"], "args": fc["args"]}})
        history.append({"role": "model", "parts": model_parts})

        if not response.function_calls:
            return AgentResult(final_text=response.text, chat_history=history, steps_used=step + 1)

        # Execute each tool call. If any tool raises EscalationRequest we
        # return immediately with the in-flight history so the outer caller
        # can resume once the escalation is resolved.
        tool_result_parts: list[dict[str, Any]] = []
        for fc in response.function_calls:
            name = fc["name"]
            args = fc["args"]
            if name not in registry:
                tool_result_parts.append({
                    "function_response": {
                        "name": name,
                        "response": {"error": f"tool not in registry for agent '{spec.name}'"},
                    }
                })
                tracer.write({
                    "t": time.time(),
                    "event": "tool_error",
                    "agent": spec.name,
                    "tool": name,
                    "error": "not_in_registry",
                })
                continue

            tracer.write({
                "t": time.time(),
                "event": "tool_call",
                "agent": spec.name,
                "tool": name,
                "args": _redact(args),
            })
            try:
                result = registry[name].fn(args, **ctx) if _accepts_kwargs(registry[name].fn) else registry[name].fn(args)
                if asyncio.iscoroutine(result):
                    result = await result
            except EscalationRequest as esc:
                # Record partial history — caller must append the tool response once resolved.
                return AgentResult(
                    escalation=esc,
                    chat_history=history,
                    steps_used=step + 1,
                )
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}

            tracer.write({
                "t": time.time(),
                "event": "tool_result",
                "agent": spec.name,
                "tool": name,
                "result_preview": _truncate(result),
            })
            tool_result_parts.append({
                "function_response": {
                    "name": name,
                    "response": {"result": result} if not isinstance(result, dict) else result,
                }
            })

        history.append({"role": "user", "parts": tool_result_parts})

    raise MaxStepsExceeded(f"{spec.name} exceeded {spec.max_steps} steps")


def _accepts_kwargs(fn: Callable) -> bool:
    import inspect
    try:
        sig = inspect.signature(fn)
        return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()) \
            or len(sig.parameters) > 1
    except (TypeError, ValueError):
        return False


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    """Never log raw PAN/amount values. Log field names + lengths only."""
    safe: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > 120:
            safe[k] = f"<str len={len(v)}>"
        elif isinstance(v, (list, dict)):
            safe[k] = f"<{type(v).__name__} size={len(v)}>"
        else:
            safe[k] = v
    return safe


def _truncate(result: Any, limit: int = 400) -> Any:
    try:
        s = json.dumps(result, default=str)
    except TypeError:
        s = str(result)
    return s if len(s) <= limit else s[:limit] + "...<truncated>"
