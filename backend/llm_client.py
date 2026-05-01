"""Gemini 2.5 Flash client with deterministic mock fallback.

Public API: `async generate_with_tools(...)` returns a LLMResponse with
`.text` and `.function_calls` so agent_runtime can drive the ReAct loop
uniformly in both real and mock modes.

Mock mode:
  When GEMINI_API_KEY is unset, returns structured mock responses that
  exercise the tool-calling paths of each agent. Lets the full pipeline
  run locally with no API quota.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


@dataclass
class LLMResponse:
    text: str | None = None
    function_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


async def generate_with_tools(
    model: str,
    system_prompt: str,
    history: list[dict[str, Any]],
    tool_declarations: list[dict[str, Any]],
    tracer=None,
    agent_name: str = "",
) -> LLMResponse:
    """Call Gemini with function-calling enabled, or mock when key is unset."""
    if is_configured():
        return await _real_call(model, system_prompt, history, tool_declarations)
    return _mock_call(system_prompt, history, tool_declarations, agent_name)


async def _real_call(
    model: str,
    system_prompt: str,
    history: list[dict[str, Any]],
    tool_declarations: list[dict[str, Any]],
) -> LLMResponse:
    """Real Gemini 2.5 Flash call via google-genai SDK.

    Implicit caching is active by default on 2.5 Flash — no explicit setup
    needed for system prompt caching.
    """
    from google import genai  # local import so mock mode doesn't need the SDK
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(**fd) for fd in tool_declarations
    ])] if tool_declarations else None

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=tools,
        temperature=0.2,
    )
    response = await client.aio.models.generate_content(
        model=model,
        contents=history,
        config=config,
    )
    text_parts: list[str] = []
    function_calls: list[dict[str, Any]] = []
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc:
                function_calls.append({"name": fc.name, "args": dict(fc.args or {})})
    return LLMResponse(
        text="\n".join(text_parts) if text_parts else None,
        function_calls=function_calls,
        usage={
            "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
            "output_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
        },
    )


def _last_tool_response(history: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for msg in reversed(history):
        for part in msg.get("parts", []):
            fr = part.get("function_response") if isinstance(part, dict) else None
            if fr and fr.get("name") == name:
                return fr.get("response") or {}
    return None


def _mock_flag_resolver(
    turn: int,
    history: list[dict[str, Any]],
    tool_names: set[str],
) -> LLMResponse:
    """Drive b3 deterministically:
       0  fetch_session_context
       1  check_known_exemptions  (one batched call with all descriptions)
       2  research_descriptions_batch
       3  emit final proposals JSON
    """
    from tds_knowledge.exemptions import lookup_exemption

    # Pull the original task to recover the flag-group descriptions.
    task_text = ""
    for msg in history:
        if msg.get("role") == "user":
            for part in msg.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    task_text = part["text"]
                    break
            if task_text:
                break

    # Extract descriptions from the task lines (formatted as "description=..." in agent.py).
    import re
    descriptions = re.findall(r"description='([^']+)'", task_text)

    if turn == 0 and "fetch_session_context" in tool_names:
        return LLMResponse(function_calls=[{"name": "fetch_session_context", "args": {}}])
    if turn == 1 and "check_known_exemptions" in tool_names:
        return LLMResponse(function_calls=[{
            "name": "check_known_exemptions",
            "args": {"descriptions": descriptions},
        }])
    if turn == 2 and "research_descriptions_batch" in tool_names:
        # Only research what KB didn't resolve.
        unresolved = [d for d in descriptions if not lookup_exemption(d)]
        return LLMResponse(function_calls=[{
            "name": "research_descriptions_batch",
            "args": {"descriptions": unresolved},
        }])

    # Compose final proposals from KB + research.
    research_summaries: dict[str, str] = {}
    research_resp = _last_tool_response(history, "research_descriptions_batch") or {}
    research_summaries = research_resp.get("summaries") or {}

    proposals = []
    for d in descriptions:
        kb = lookup_exemption(d)
        if kb:
            recommended = {
                "action": kb["action"],
                "section": kb.get("section"),
                "skip_reason": kb.get("skip_reason"),
                "confidence": kb["confidence"],
            }
            options: list[str] = []
            if kb["action"] == "skip":
                options.append(f"Skip TDS — {kb.get('skip_reason', 'exempt').replace('_', ' ')}")
                options.extend(kb.get("alt_options") or [])
            elif kb["action"] == "apply":
                rate_label = {
                    "194A": "194A at 10%", "194C": "194C at 2%", "194H": "194H at 2%",
                    "194J(b)": "194J(b) at 10%", "194I": "194I at 10%", "194Q": "194Q at 0.1%",
                }.get(kb["section"], kb["section"])
                options.append(rate_label)
                options.extend(kb.get("alt_options") or [])
            else:  # ask
                options.extend(kb.get("alt_options") or [])
            note = kb["rationale"]
            source = "kb"
        else:
            recommended = {
                "action": "ask",
                "section": None,
                "skip_reason": None,
                "confidence": "medium",
            }
            options = ["Skip TDS", "194C at 2%", "194J(b) at 10%"]
            note = research_summaries.get(d, "No KB hit. Surface to user with default options.")
            source = "web" if research_summaries else "fallback"

        proposals.append({
            "description": d,
            "recommended": recommended,
            "options": options,
            "research_note": note,
            "source": source,
        })

    return LLMResponse(text=json.dumps({"status": "ok", "proposals": proposals}))


def _mock_orchestrator(
    turn: int,
    history: list[dict[str, Any]],
    tool_names: set[str],
) -> LLMResponse:
    """Drive a1 through:
        invoke_column_reader -> (escalation? ask_user, then resume) ->
        invoke_tds_calculator ->
        invoke_flag_resolver  (only if flag_count > 0) ->
        surface_proposals_to_user (suspend; resume on user complete) ->
        send_resolutions_to_b2 ->
        return_final_result.
    """
    def last_fn_response(name: str) -> dict[str, Any] | None:
        for msg in reversed(history):
            for part in msg.get("parts", []):
                fr = part.get("function_response") if isinstance(part, dict) else None
                if fr and fr.get("name") == name:
                    return fr.get("response") or {}
        return None

    def model_calls(name: str) -> int:
        n = 0
        for msg in history:
            if msg.get("role") != "model":
                continue
            for part in msg.get("parts", []):
                fc = part.get("function_call") or {}
                if fc.get("name") == name:
                    n += 1
        return n

    cr = last_fn_response("invoke_column_reader") or {}
    tc = last_fn_response("invoke_tds_calculator") or {}
    fr = last_fn_response("invoke_flag_resolver") or {}
    sp = last_fn_response("surface_proposals_to_user") or {}
    af = last_fn_response("send_resolutions_to_b2") or {}
    au = last_fn_response("ask_user") or {}
    final = last_fn_response("return_final_result") or {}

    cr_calls = model_calls("invoke_column_reader")

    # Step 1: kick off b1
    if cr_calls == 0 and "invoke_column_reader" in tool_names:
        return LLMResponse(function_calls=[{"name": "invoke_column_reader", "args": {}}])

    # b1 escalated for PAN — forward to user
    if cr.get("status") == "escalation_from_column_reader" and not au:
        return LLMResponse(function_calls=[{
            "name": "ask_user",
            "args": {
                "question": cr.get("question", ""),
                "options": cr.get("options", []),
                "recommended": cr.get("recommended"),
                "research_note": "Tally export lacks a PAN column.",
            },
        }])

    # User answered — resume b1
    if cr.get("status") == "escalation_from_column_reader" and au and cr_calls == 1:
        return LLMResponse(function_calls=[{
            "name": "invoke_column_reader",
            "args": {"resume_with_answer": au.get("answer", "")},
        }])

    # Step 2: invoke b2 once b1 is ok
    if cr.get("status") == "ok" and not tc.get("status") == "ok":
        return LLMResponse(function_calls=[{"name": "invoke_tds_calculator", "args": {}}])

    # Step 3: if b2 had flags, invoke b3
    if tc.get("status") == "ok" and (tc.get("unique_flag_groups") or 0) > 0 and not fr:
        return LLMResponse(function_calls=[{"name": "invoke_flag_resolver", "args": {}}])

    # Step 4: surface b3's proposals to user (suspend until /complete)
    if fr.get("status") == "ok" and (fr.get("proposal_count") or 0) > 0 and not sp:
        return LLMResponse(function_calls=[{
            "name": "surface_proposals_to_user",
            "args": {"proposal_count": fr.get("proposal_count", 0)},
        }])

    # Step 5: user finished — apply resolutions
    if sp and not af:
        answers = sp.get("answers") or []
        return LLMResponse(function_calls=[{
            "name": "send_resolutions_to_b2",
            "args": {"resolutions": answers},
        }])

    # Step 6: finalise
    if (
        tc.get("status") == "ok"
        and (af.get("applied") is not None or (tc.get("unique_flag_groups") or 0) == 0)
        and not final
    ):
        return LLMResponse(function_calls=[{
            "name": "return_final_result",
            "args": {"status": "ok", "summary": "Pipeline complete (mock)."},
        }])

    return LLMResponse(text="Pipeline complete (mock mode).")


def _mock_column_reader(
    turn: int,
    history: list[dict[str, Any]],
    tool_names: set[str],
) -> LLMResponse:
    """Drive either the Flat or Tally path deterministically.

    Decision: if list_sheets returned >1 sheet, take Tally path; otherwise Flat.
    """
    sheets_resp = _last_tool_response(history, "list_sheets")
    is_tally = bool(sheets_resp and sheets_resp.get("count", 0) > 1)

    # Turn 0: start with list_sheets for Excel (we can't detect .xlsx here,
    # so use list_sheets for everything and fall back to fingerprint on flat).
    if turn == 0 and "list_sheets" in tool_names:
        return LLMResponse(function_calls=[{"name": "list_sheets", "args": {}}])

    if is_tally:
        # Which sheets have we already sniffed?
        sheets = (sheets_resp or {}).get("sheets") or []
        sniffed: dict[str, dict[str, Any]] = {}
        for msg in history:
            for part in msg.get("parts", []):
                fr = part.get("function_response") if isinstance(part, dict) else None
                if fr and fr.get("name") == "sniff_sheet":
                    resp = fr.get("response") or {}
                    if resp.get("sheet"):
                        sniffed[resp["sheet"]] = resp
        # Sniff any sheet we haven't yet.
        for s in sheets:
            if s["name"] not in sniffed:
                return LLMResponse(function_calls=[{
                    "name": "sniff_sheet",
                    "args": {"sheet_name": s["name"]},
                }])

        # All sheets sniffed. Has PAN policy been set?
        policy_resp = _last_tool_response(history, "set_pan_policy")
        if policy_resp is None:
            # Still no policy. Ask orchestrator once, then set policy once.
            asked = any(
                (part.get("function_call") or {}).get("name") == "ask_orchestrator"
                for msg in history if msg.get("role") == "model"
                for part in msg.get("parts", [])
            )
            if not asked:
                return LLMResponse(function_calls=[{
                    "name": "ask_orchestrator",
                    "args": {
                        "question": "The uploaded Tally file has no PAN column. Apply 20% (Section 206AA) to every row, or assume PANs are available?",
                        "options": [
                            "Apply 20% (Section 206AA) to every row - safest without PANs",
                            "Assume I have PANs - compute at standard section rates",
                        ],
                        "context": "Tally export has no PAN per vendor. PAN policy applies to the whole batch.",
                        "recommended": "Apply 20% (Section 206AA) to every row - safest without PANs",
                    },
                }])
            # After the escalation returned, set_pan_policy.
            return LLMResponse(function_calls=[{
                "name": "set_pan_policy",
                "args": {"policy": "apply_206aa"},
            }])

        # Policy set. Extract any sheet we haven't yet extracted.
        extracted_sheets = set()
        for msg in history:
            for part in msg.get("parts", []):
                fr = part.get("function_response") if isinstance(part, dict) else None
                if fr and fr.get("name") == "extract_tally_rows":
                    resp = fr.get("response") or {}
                    if resp.get("sheet"):
                        extracted_sheets.add(resp["sheet"])
        for name, s in sniffed.items():
            if s["type"] in ("journal", "purchase_gst_exp", "purchase_plain") and name not in extracted_sheets:
                return LLMResponse(function_calls=[{
                    "name": "extract_tally_rows",
                    "args": {"sheet_name": name, "sheet_type": s["type"]},
                }])

        # All done — emit summary JSON.
        total = sum(
            (_last_tool_response(history, "extract_tally_rows") or {}).get("session_total_rows", 0)
            for _ in [0]
        )
        sheets_out = []
        for name, s in sniffed.items():
            if s["type"] in ("journal", "purchase_gst_exp", "purchase_plain"):
                sheets_out.append({"name": name, "type": s["type"]})
        return LLMResponse(text=json.dumps({
            "format": "tally",
            "pan_policy": "apply_206aa",
            "total_rows_extracted": total,
            "sheets_extracted": sheets_out,
            "notes": "mock-mode: Tally path",
        }))

    # Flat path: fall back to fingerprint + header mapping.
    if "fingerprint_columns" in tool_names and _last_tool_response(history, "fingerprint_columns") is None:
        return LLMResponse(function_calls=[{"name": "fingerprint_columns", "args": {}}])
    fp = _last_tool_response(history, "fingerprint_columns") or {}
    mapping = _mock_header_mapping(fp.get("headers") or [])
    return LLMResponse(text=json.dumps({
        "format": "flat",
        "mapping": mapping,
        "notes": "mock-mode: flat file, headers matched by lowercase substring.",
    }))


def _mock_header_mapping(headers: list[str]) -> dict[str, str | None]:
    """Map uploaded headers to canonical fields by simple keyword heuristics.

    Used only in mock mode; the real LLM does richer reasoning (distinguishing
    base-vs-GST amounts, detecting GST-inclusive columns, etc).
    """
    out: dict[str, str | None] = {}
    for h in headers:
        low = (h or "").strip().lower()
        if any(k in low for k in ("date", "dt")):
            out[h] = "date"
        elif "pan" in low:
            out[h] = "pan"
        elif any(k in low for k in ("amount", "amt", "value", "total")):
            out[h] = "amount"
        elif any(k in low for k in ("vendor", "party", "name", "payee")):
            out[h] = "vendor"
        elif any(k in low for k in ("description", "narration", "expense", "particular", "head")):
            out[h] = "description"
        elif any(k in low for k in ("mode", "payment")):
            out[h] = "payment_mode"
        else:
            out[h] = None
    return out


def _mock_call(
    system_prompt: str,
    history: list[dict[str, Any]],
    tool_declarations: list[dict[str, Any]],
    agent_name: str,
) -> LLMResponse:
    """Deterministic mock keyed on agent name + history length.

    Goal: exercise the real tool call paths so the rest of the pipeline
    behaves correctly without a live API.
    """
    turn = sum(1 for m in history if m.get("role") == "model")
    tool_names = {t["name"] for t in tool_declarations}

    if agent_name == "column_reader":
        return _mock_column_reader(turn, history, tool_names)

    if agent_name == "orchestrator":
        return _mock_orchestrator(turn, history, tool_names)

    if agent_name == "flag_resolver":
        return _mock_flag_resolver(turn, history, tool_names)

    if agent_name == "tds_calculator":
        if turn == 0 and "calculate_batch" in tool_names:
            return LLMResponse(function_calls=[{"name": "calculate_batch", "args": {}}])
        # calculate_batch returned its summary; echo that tiny summary.
        summary = _last_tool_response(history, "calculate_batch")
        if summary is not None:
            return LLMResponse(text=json.dumps({
                "status": summary.get("status", "ok"),
                "row_count": summary.get("row_count", 0),
                "flag_count": summary.get("flag_count", 0),
                "total_tds_estimate": summary.get("total_tds_estimate", 0),
                "summary": "mock-mode",
            }))
        return LLMResponse(text=json.dumps({"status": "error", "error": "no calc result"}))

    return LLMResponse(text="mock-mode")
