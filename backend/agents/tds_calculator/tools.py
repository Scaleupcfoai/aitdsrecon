"""b2 tool implementations and Gemini function declarations.

file_path + column mapping are passed via tool_context (not LLM args) so the
model cannot accidentally operate on a different file or re-declare the mapping.
"""

from __future__ import annotations

from typing import Any

from agent_runtime import EscalationRequest, ToolSpec

from .core import (
    apply_206aa_info,
    calculate_batch as _calculate_batch,
    check_threshold_info,
    classify_section_info,
    lookup_rate_info,
)


def _calculate_batch_tool(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Run the deterministic TDS calculation + persist the full payload to the session.

    We do NOT return per-row results to b2 — for large files (HPCL: 1,495 rows)
    that would force Gemini to echo ~200 KB of JSON back, taking minutes and
    sometimes timing out. Instead the full (results + flags + aggregates) goes
    into session.tds_results; b2 sees only a small summary and emits a tiny
    summary JSON as its final answer.
    """
    from session import load_session

    rows = ctx.get("rows")
    if rows is not None:
        payload = _calculate_batch(rows=rows, pan_policy=ctx.get("pan_policy"))
    else:
        payload = _calculate_batch(file_path=ctx["file_path"], mapping=ctx["mapping"])

    # Persist server-side so the orchestrator can read it without it going
    # through the LLM.
    session_id = ctx.get("session_id")
    if session_id:
        session = load_session(session_id)
        session.tds_results = payload
        session.save()

    results = payload.get("results") or []
    flags = payload.get("flags") or []
    total_tds = sum((r.get("tds_amount") or 0) for r in results)
    # Summary only. Full results already persisted.
    return {
        "status": "ok",
        "row_count": len(results),
        "flag_count": len(flags),
        "total_tds_estimate": round(total_tds, 2),
        "diagnostics": payload.get("diagnostics", {}),
        "persisted_to_session": bool(session_id),
    }


def _apply_resolutions_tool(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """b2-owned: take resolutions from a1 and update b2's results in session.

    Contract: a1 hands us {resolutions: [{row_ids, section?, skip_reason?, rate_pct?, ...}, ...]}.
    Each resolution covers one or more rows. We recompute rate/TDS deterministically
    from rates.py given (section, PAN), apply 206AA when PAN missing, and persist.
    """
    from session import load_session
    from tds_knowledge.pan_utils import is_valid_pan
    from tds_knowledge.rates import SECTION_206AA_RATE, expected_rate

    session = load_session(ctx["session_id"])
    if not session.tds_results or not session.tds_results.get("results"):
        return {"error": "no tds_results to patch — calculate_batch first"}

    SECTION_ALIASES = {"194J": "194J(b)", "194 C": "194C", "194 H": "194H", "194 Q": "194Q", "194 A": "194A"}

    def normalise_section(s: str) -> str:
        if not s:
            return ""
        x = s.strip().upper().replace(" ", "")
        if x in {"194A", "194C", "194H", "194J(A)", "194J(B)", "194Q", "194I(A)", "194I(B)", "194D", "194T", "194O", "194R", "195"}:
            return x.replace("(A)", "(a)").replace("(B)", "(b)")
        return SECTION_ALIASES.get(x, s)

    resolutions = args.get("resolutions") or []
    results = session.tds_results["results"]
    by_id = {r["row_id"]: r for r in results}
    applied = 0
    resolved_ids: set[int] = set()

    for res in resolutions:
        target_ids = res.get("row_ids") or ([res["row_id"]] if res.get("row_id") is not None else [])
        if not target_ids:
            continue
        skip_reason = res.get("skip_reason")
        section = normalise_section(res.get("section") or "") if res.get("section") else None
        explicit_rate = res.get("rate_pct")
        explicit_tds = res.get("tds_amount")
        note = res.get("note", "user_resolved")

        for row_id in target_ids:
            row = by_id.get(row_id)
            if not row:
                continue
            if skip_reason:
                row["skip_reason"] = skip_reason
                row["tds_amount"] = 0.0
                row["rate_pct"] = 0.0
                row["section"] = None
                row["resolved"] = True
                row["resolution_note"] = note
                applied += 1
                resolved_ids.add(row_id)
                continue
            if section:
                row["section"] = section
            if explicit_rate is not None:
                rate = float(explicit_rate)
            elif row["section"]:
                rate = expected_rate(row["section"], row.get("pan", "") or "") or 0.0
            else:
                rate = float(row.get("rate_pct") or 0.0)
            if not is_valid_pan(row.get("pan", "") or ""):
                rate = max(rate, SECTION_206AA_RATE)
            row["rate_pct"] = rate
            if explicit_tds is not None:
                row["tds_amount"] = float(explicit_tds)
            elif row.get("amount") is not None:
                row["tds_amount"] = round(float(row["amount"]) * rate / 100, 2)
            row["skip_reason"] = None
            row["resolved"] = True
            row["resolution_note"] = note
            applied += 1
            resolved_ids.add(row_id)

    # Drop flags whose row is now resolved.
    session.tds_results["flags"] = [
        f for f in session.tds_results.get("flags", []) if f.get("row_id") not in resolved_ids
    ]
    session.save()
    return {"applied": applied, "resolution_groups": len(resolutions),
            "remaining_flags": len(session.tds_results["flags"])}


def _lookup_rate(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    return lookup_rate_info(section=args.get("section", ""), pan=args.get("pan", ""))


def _classify_section(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    return classify_section_info(description=args.get("description", ""))


def _check_threshold(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    return check_threshold_info(
        section=args.get("section", ""),
        aggregate_amount=float(args.get("aggregate_amount", 0)),
        single_amount=args.get("single_amount"),
    )


def _apply_206aa(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    return apply_206aa_info(applicable_rate_pct=float(args.get("applicable_rate_pct", 0)))


def _ask_orchestrator(args: dict[str, Any], **ctx: Any) -> Any:
    raise EscalationRequest(
        kind="ask_orchestrator",
        payload={
            "from_agent": "tds_calculator",
            "question": args.get("question", ""),
            "options": args.get("options", []),
            "context": args.get("context", ""),
            "recommended": args.get("recommended"),
        },
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="calculate_batch",
        description=(
            "Run the full deterministic TDS pass on the uploaded file. Returns per-row "
            "results, human-review flags, vendor annual aggregates, and diagnostics. "
            "Call this first. Usually sufficient by itself."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_calculate_batch_tool,
    ),
    ToolSpec(
        name="apply_resolutions",
        description=(
            "Update b2's per-row results with resolutions handed in by a1. "
            "Each resolution carries row_ids and either a section (apply path) "
            "or a skip_reason. Rate + TDS are recomputed from rates.py."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resolutions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "row_ids": {"type": "array", "items": {"type": "integer"}},
                            "row_id": {"type": "integer"},
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
        fn=_apply_resolutions_tool,
    ),
    ToolSpec(
        name="lookup_rate",
        description="Look up the expected TDS rate for a specific TDS section and PAN. Returns rate_pct + entity_type.",
        parameters={
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "TDS section, e.g. '194C'."},
                "pan": {"type": "string", "description": "PAN (AAAAA9999A)."},
            },
            "required": ["section", "pan"],
        },
        fn=_lookup_rate,
    ),
    ToolSpec(
        name="classify_section",
        description="Classify a single expense description into likely TDS section(s). Returns sections + ambiguity note.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Expense description / narration."},
            },
            "required": ["description"],
        },
        fn=_classify_section,
    ),
    ToolSpec(
        name="check_threshold",
        description="Check whether aggregate/single amount crosses the section's TDS threshold.",
        parameters={
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "aggregate_amount": {"type": "number"},
                "single_amount": {"type": "number"},
            },
            "required": ["section", "aggregate_amount"],
        },
        fn=_check_threshold,
    ),
    ToolSpec(
        name="apply_206aa",
        description="Compute the effective TDS rate under Section 206AA when PAN is missing/invalid (max of applicable rate and 20%).",
        parameters={
            "type": "object",
            "properties": {
                "applicable_rate_pct": {"type": "number", "description": "The standard rate for the section."},
            },
            "required": ["applicable_rate_pct"],
        },
        fn=_apply_206aa,
    ),
    ToolSpec(
        name="ask_orchestrator",
        description=(
            "Escalate a single genuinely unusual case to the orchestrator. Use rarely — "
            "most flags belong in the batched flags[] of your final JSON output."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
                "recommended": {"type": "string"},
            },
            "required": ["question", "options", "context"],
        },
        fn=_ask_orchestrator,
    ),
]
