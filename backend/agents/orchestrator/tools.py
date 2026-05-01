"""a1 tool implementations.

a1 (LLM) is the only agent the user talks to. Its tools:

  invoke_column_reader        run b1; returns mapping or escalation
  invoke_tds_calculator       run b2; persists results to session, returns summary
  apply_flag_resolutions      patch b2's results with user answers
  web_search                  Gemini Google Search grounding (fallback to mock)
  ask_user                    sequential popup with progress UI
  return_final_result         end of pipeline
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime import EscalationRequest, ToolSpec
from shared_tools.web_search import web_search as _web_search_impl


# ─── ask_user ──────────────────────────────────────────────────────────────

def _ask_user(args: dict[str, Any], **ctx: Any) -> Any:
    raise EscalationRequest(
        kind="ask_user",
        payload={
            "question": args.get("question", ""),
            "options": args.get("options", []),
            "recommended": args.get("recommended"),
            "research_note": args.get("research_note"),
            "batch": args.get("batch"),
            "allow_free_text": bool(args.get("allow_free_text", False)),
            "flag_row_id": args.get("flag_row_id"),
        },
    )


# ─── web_search ────────────────────────────────────────────────────────────

async def _web_search(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    return await _web_search_impl(args.get("query", ""))


# ─── invoke_column_reader ─────────────────────────────────────────────────

async def _invoke_column_reader(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Run b1 — or resume a suspended b1 with the user's answer.

    If a1 passes `resume_with_answer`, b1 picks up from its pending escalation:
    we append the answer as a tool_response for ask_orchestrator and continue
    the ReAct loop from the same point.
    """
    from agents.column_reader import run_column_reader
    from session import PendingEscalation, load_session

    session = load_session(ctx["session_id"])
    tracer = ctx["tracer"]
    if not session.file_path:
        return {"error": "no file uploaded"}

    initial_history: list[dict[str, Any]] | None = None
    resume_answer = args.get("resume_with_answer")
    pe = session.pending_escalation
    if resume_answer and pe and pe.from_agent == "column_reader":
        initial_history = list(pe.chat_history)
        initial_history.append({
            "role": "user",
            "parts": [{"function_response": {
                "name": "ask_orchestrator",
                "response": {"answer": resume_answer},
            }}],
        })
        session.pending_escalation = None
        session.save()

    result = await run_column_reader(
        file_path=session.file_path,
        session_id=ctx["session_id"],
        tracer=tracer,
        initial_history=initial_history,
    )
    if result.escalation:
        session.pending_escalation = PendingEscalation(
            kind=result.escalation.kind,
            from_agent="column_reader",
            payload=result.escalation.payload,
            chat_history=result.chat_history,
        )
        session.save()
        return {
            "status": "escalation_from_column_reader",
            "question": result.escalation.payload.get("question"),
            "options": result.escalation.payload.get("options"),
            "context": result.escalation.payload.get("context"),
            "recommended": result.escalation.payload.get("recommended"),
        }

    # Parse b1's final text. Two legal shapes:
    #   {"format": "flat",  "mapping": {...}, "notes": "..."}
    #   {"format": "tally", "pan_policy": "...", "total_rows_extracted": N, "sheets_extracted": [...]}
    parsed = _extract_mapping(result.final_text or "")
    fmt = parsed.get("format") or ("flat" if parsed.get("mapping") else None)

    if fmt == "tally":
        # Rows were already written to session.extracted_rows by extract_tally_rows tool.
        session = load_session(ctx["session_id"])  # reload after tools mutated it
        return {
            "status": "ok",
            "format": "tally",
            "pan_policy": session.pan_policy,
            "row_count": len(session.extracted_rows or []),
            "sheets": parsed.get("sheets_extracted"),
        }

    # Flat format (default)
    session.column_mapping = parsed.get("mapping", {})
    session.save()
    return {
        "status": "ok",
        "format": "flat",
        "mapping": session.column_mapping,
        "notes": parsed.get("notes"),
    }


def _extract_mapping(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from b1's final text. Permissive on fences.

    Returns the raw parsed dict so callers can inspect both flat-format
    ({mapping, notes}) and tally-format ({format, pan_policy, ...}) shapes.
    """
    if not text:
        return {}
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"notes": text[:200]}


# ─── invoke_tds_calculator ─────────────────────────────────────────────────

async def _invoke_tds_calculator(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    from agents.tds_calculator import run_tds_calculator
    from session import PendingEscalation, load_session

    session = load_session(ctx["session_id"])
    tracer = ctx["tracer"]

    # Tally path: b1 populated session.extracted_rows.
    if session.extracted_rows:
        result = await run_tds_calculator(
            file_path=None,
            mapping=None,
            rows=session.extracted_rows,
            pan_policy=session.pan_policy,
            tracer=tracer,
            session_id=ctx["session_id"],
        )
    # Flat path: b1 produced a column mapping.
    elif session.file_path and session.column_mapping:
        result = await run_tds_calculator(
            file_path=session.file_path,
            mapping=session.column_mapping,
            tracer=tracer,
            session_id=ctx["session_id"],
        )
    else:
        return {"error": "no data staged — invoke column_reader first"}
    if result.escalation:
        session.pending_escalation = PendingEscalation(
            kind=result.escalation.kind,
            from_agent="tds_calculator",
            payload=result.escalation.payload,
            chat_history=result.chat_history,
        )
        session.save()
        return {
            "status": "escalation_from_tds_calculator",
            "question": result.escalation.payload.get("question"),
            "options": result.escalation.payload.get("options"),
            "context": result.escalation.payload.get("context"),
            "recommended": result.escalation.payload.get("recommended"),
        }

    # Read full results from the session — calculate_batch wrote them
    # there directly (avoids Gemini having to echo hundreds of KB of JSON).
    session = load_session(ctx["session_id"])
    tds_payload = session.tds_results or {}
    results = tds_payload.get("results") or []
    flags = tds_payload.get("flags") or []
    diagnostics = tds_payload.get("diagnostics") or {}
    total_tds = sum((r.get("tds_amount") or 0) for r in results)

    # Dedupe flags into groups so a1 asks once per unique (reason, description)
    # instead of once per row. HPCL had 242 raw flags -> ~22 groups.
    flag_groups = _group_flags(flags)

    return {
        "status": "ok",
        "row_count": len(results),
        "flag_count": len(flags),
        "unique_flag_groups": len(flag_groups),
        "total_tds_estimate": round(total_tds, 2),
        "diagnostics": diagnostics,
        "flag_groups": flag_groups,
    }


def _group_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse per-row flags into per-(reason, description) groups.

    Each group carries the full row_id list so the orchestrator can apply a
    single user decision to all matching rows at once.
    """
    from collections import defaultdict

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for f in flags:
        reason = f.get("reason", "")
        desc = f.get("description", "")
        key = (reason, desc.lower().strip())
        g = grouped.setdefault(key, {
            "reason": reason,
            "description": desc,
            "row_ids": [],
            "row_count": 0,
            "total_amount": 0.0,
            "sample_vendors": set(),
            "current_section": f.get("current_section"),
            "possible_sections": f.get("possible_sections"),
            "context": f.get("context"),
        })
        g["row_ids"].append(f.get("row_id"))
        g["row_count"] += 1
        g["total_amount"] += float(f.get("amount") or 0)
        if len(g["sample_vendors"]) < 5:
            g["sample_vendors"].add(f.get("vendor") or "")

    # Serialise for JSON + sort largest first.
    out = []
    for g in grouped.values():
        out.append({
            "reason": g["reason"],
            "description": g["description"],
            "row_count": g["row_count"],
            "row_ids": g["row_ids"],
            "total_amount": round(g["total_amount"], 2),
            "sample_vendors": sorted(v for v in g["sample_vendors"] if v)[:5],
            "current_section": g["current_section"],
            "possible_sections": g["possible_sections"],
            "context": g["context"],
        })
    out.sort(key=lambda x: x["total_amount"], reverse=True)
    return out


_SECTION_ALIASES = {
    # Gemini sometimes drops the "(b)" qualifier; default to professional-services.
    "194J": "194J(b)",
    # Legacy / loose forms we've seen.
    "194 C": "194C",
    "194 H": "194H",
    "194 Q": "194Q",
    "194 A": "194A",
}


def _normalize_section(section: str) -> str:
    if not section:
        return ""
    s = section.strip().upper().replace(" ", "")
    # Already canonical?
    if s in {"194A", "194C", "194H", "194J(A)", "194J(B)", "194Q"}:
        return s.replace("(A)", "(a)").replace("(B)", "(b)")
    # Raw "194J" defaults to the more common 194J(b).
    return _SECTION_ALIASES.get(s, section)


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"parse_error": True, "text_preview": text[:300]}


# ─── apply_flag_resolutions ────────────────────────────────────────────────

async def _invoke_flag_resolver(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Invoke b3 on the flag groups returned by b2. Persists b3's proposals
    to session.pending_proposals so a1 can surface them via surface_proposals_to_user.
    """
    import json

    from agents.flag_resolver import run_flag_resolver
    from session import load_session

    session = load_session(ctx["session_id"])
    tracer = ctx["tracer"]
    flags = (session.tds_results or {}).get("flags") or []
    if not flags:
        return {"status": "ok", "proposal_count": 0, "note": "no flags to resolve"}

    flag_groups = _group_flags(flags)
    if not flag_groups:
        return {"status": "ok", "proposal_count": 0}

    # a1 explicitly extracts what b3 needs from b2's output and hands it over.
    # b3 never reads the session — it sees only what's passed via tool_context.
    vendor_aggregates = (session.tds_results or {}).get("vendor_aggregates") or {}
    pan_policy = session.pan_policy
    file_format = "tally" if session.extracted_rows else ("flat" if session.column_mapping else "unknown")

    result = await run_flag_resolver(
        flag_groups=flag_groups,
        vendor_aggregates=vendor_aggregates,
        pan_policy=pan_policy,
        file_format=file_format,
        tracer=tracer,
    )
    if result.escalation:
        # Rare — b3 hit an unusual case it wants to escalate before composing.
        return {
            "status": "escalation_from_flag_resolver",
            "question": result.escalation.payload.get("question"),
            "options": result.escalation.payload.get("options"),
            "context": result.escalation.payload.get("context"),
            "recommended": result.escalation.payload.get("recommended"),
        }

    parsed = _extract_json(result.final_text or "")
    proposals = parsed.get("proposals") or []
    # Stitch row_ids from the original groups onto each proposal in order.
    for i, p in enumerate(proposals):
        if "row_ids" not in p and i < len(flag_groups):
            p["row_ids"] = flag_groups[i].get("row_ids", [])
        # Make sure UI-required fields exist.
        p.setdefault("description", flag_groups[i]["description"] if i < len(flag_groups) else "")
        p.setdefault("row_count", flag_groups[i]["row_count"] if i < len(flag_groups) else 0)
        p.setdefault("total_amount", flag_groups[i]["total_amount"] if i < len(flag_groups) else 0)
        p.setdefault("sample_vendors", flag_groups[i].get("sample_vendors") if i < len(flag_groups) else [])

    # ── Split into auto-apply (high-confidence) vs user-review ──
    # If b3 returned a CLEAR recommendation at confidence:high (either skip or
    # apply with a known section), we apply it server-side without surfacing.
    auto_resolutions: list[dict[str, Any]] = []
    user_proposals: list[dict[str, Any]] = []
    for p in proposals:
        rec = p.get("recommended") or {}
        action = rec.get("action")
        confidence = rec.get("confidence")
        section = rec.get("section")
        skip_reason = rec.get("skip_reason")
        row_ids = p.get("row_ids", [])
        if confidence == "high" and row_ids and (
            (action == "skip" and skip_reason)
            or (action == "apply" and section)
        ):
            auto_resolutions.append({
                "row_ids": row_ids,
                "section": section if action == "apply" else None,
                "skip_reason": skip_reason if action == "skip" else None,
                "note": f"auto_resolved_b3_{rec.get('confidence', 'high')}",
            })
        else:
            user_proposals.append(p)

    # Auto-resolutions go to b2 (b2 owns the calc; a1 is just routing).
    if auto_resolutions:
        from agents.tds_calculator.tools import _apply_resolutions_tool
        _apply_resolutions_tool({"resolutions": auto_resolutions}, session_id=ctx["session_id"])

    session = load_session(ctx["session_id"])
    session.pending_proposals = user_proposals
    session.proposal_answers = []
    session.save()
    return {
        "status": "ok",
        "proposal_count": len(user_proposals),
        "auto_resolved_b3_groups": len(auto_resolutions),
    }


def _surface_proposals_to_user(args: dict[str, Any], **ctx: Any) -> Any:
    """Hand the entire proposal list to the user for review.

    Tool suspends a1. Frontend reads session.pending_proposals via GET
    /api/session/<id>/proposals and walks the user through them locally
    (no LLM in the popup loop). When the user finishes, the frontend POSTs
    /proposal/complete which resumes a1 with the full answer list as the
    function_response for surface_proposals_to_user.
    """
    raise EscalationRequest(
        kind="proposal_review",
        payload={"proposal_count": args.get("proposal_count", 0)},
    )


def _send_resolutions_to_b2(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """a1's tool: hand resolutions to b2 (the TDS calculator owns the deliverable).

    Calls b2's apply_resolutions tool directly (deterministic — no extra LLM turn).
    The conceptual ownership is preserved: a1 routes; b2 updates its own results.
    """
    from agents.tds_calculator.tools import _apply_resolutions_tool

    return _apply_resolutions_tool(args, session_id=ctx["session_id"])


# Legacy alias retained so older history references still resolve.
_apply_flag_resolutions = _send_resolutions_to_b2


# ─── return_final_result ──────────────────────────────────────────────────

def _return_final_result(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    from session import load_session

    session = load_session(ctx["session_id"])
    session.completed = True
    session.final_result = {
        "status": args.get("status", "ok"),
        "summary": args.get("summary", ""),
    }
    session.save()
    return {"acknowledged": True}


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="invoke_column_reader",
        description=(
            "Invoke the Column Reader subagent. First call (no args): runs b1 fresh. "
            "If b1 escalated earlier and the user just answered, call again with "
            "resume_with_answer=<the user's answer string> so b1 picks up where it left off."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resume_with_answer": {
                    "type": "string",
                    "description": "Pass when b1 had asked via ask_orchestrator and the user answered.",
                },
            },
            "required": [],
        },
        fn=_invoke_column_reader,
    ),
    ToolSpec(
        name="invoke_tds_calculator",
        description=(
            "Invoke the TDS Calculator subagent on the uploaded file and stored mapping. "
            "Returns a SUMMARY (row_count, flag_count, total_tds_estimate, flags). "
            "Full per-row results stay on the session; use apply_flag_resolutions to patch them."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_invoke_tds_calculator,
    ),
    ToolSpec(
        name="invoke_flag_resolver",
        description=(
            "Invoke the Flag Resolver subagent (b3). It reads the calculator's "
            "flag list, groups by (reason, description), looks up the deterministic "
            "exemptions KB, fires ONE batched grounded research call, and writes "
            "rich proposals (recommended action + research note + options) to the "
            "session. Returns proposal_count. Call this once, after invoke_tds_calculator."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_invoke_flag_resolver,
    ),
    ToolSpec(
        name="surface_proposals_to_user",
        description=(
            "Hand the entire proposal list to the user for review. Suspends a1. "
            "The UI walks the user through proposals one at a time and resumes a1 "
            "when done. Returns the user's answers as a list aligned with proposals."
        ),
        parameters={
            "type": "object",
            "properties": {
                "proposal_count": {"type": "integer", "description": "How many proposals are pending."},
            },
            "required": [],
        },
        fn=_surface_proposals_to_user,
    ),
    ToolSpec(
        name="send_resolutions_to_b2",
        description=(
            "Hand a list of resolutions to b2 (the TDS calculator) so b2 updates "
            "its per-row deliverable. b2 owns the calc; you are routing. Each "
            "resolution either targets one row (row_id) or a whole group (row_ids)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resolutions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "row_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Batch of row ids to apply the same decision to.",
                            },
                            "row_id": {
                                "type": "integer",
                                "description": "Single row (legacy). Prefer row_ids.",
                            },
                            "section": {"type": "string"},
                            "rate_pct": {"type": "number"},
                            "tds_amount": {"type": "number"},
                            "skip_reason": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["resolutions"],
        },
        fn=_send_resolutions_to_b2,
    ),
    ToolSpec(
        name="web_search",
        description="Search the web (Gemini Google Search grounding) for TDS rules, expense classification, or vendor details. Use BEFORE asking the user.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        fn=_web_search,
    ),
    ToolSpec(
        name="ask_user",
        description=(
            "Ask the end user a single question. Always include research_note and recommended when possible. "
            "For a multi-question series, pass batch={id, current, total} so the UI shows progress."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "recommended": {"type": "string"},
                "research_note": {"type": "string"},
                "batch": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "current": {"type": "integer"},
                        "total": {"type": "integer"},
                    },
                },
                "allow_free_text": {"type": "boolean"},
                "flag_row_id": {"type": "integer", "description": "row_id of the flag this question resolves (if applicable)"},
            },
            "required": ["question", "options"],
        },
        fn=_ask_user,
    ),
    ToolSpec(
        name="return_final_result",
        description="Signal the end of the pipeline. Session will be marked completed.",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["status"],
        },
        fn=_return_final_result,
    ),
]
