"""b3 tools — judge using ONLY data passed in by a1 (tool_context).

No agent reads from session directly. a1 hands b3 everything it needs:
  tool_context["flag_groups"]         the groups to resolve
  tool_context["vendor_aggregates"]   {normalized_name: annual_total}
  tool_context["pan_policy"]          'apply_206aa' | 'assume_pan' | None
  tool_context["file_format"]         'tally' | 'flat'
  tool_context["section_count"]       count of rows already calc'd by b2
"""

from __future__ import annotations

import os
import re
from typing import Any

from agent_runtime import EscalationRequest, ToolSpec
from tds_knowledge.expense_head_kb import lookup_govt_vendor, lookup_kb
from tds_knowledge.pan_utils import normalize_name
from tds_knowledge.thresholds import TDS_THRESHOLDS


# ── KB lookup (no session read) ──────────────────────────────────────────

def _check_known_exemptions(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    descriptions: list[str] = args.get("descriptions") or []
    out = {d: lookup_kb(d) for d in descriptions}
    return {"hits": out, "hit_count": sum(1 for v in out.values() if v)}


# ── Vendor aggregate lookup (reads tool_context, NOT session) ────────────

def _lookup_vendor_aggregate(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    vendor_aggregates: dict[str, float] = ctx.get("vendor_aggregates") or {}
    vendor = args.get("vendor", "")
    norm = normalize_name(vendor)
    return {
        "vendor": vendor,
        "vendor_normalized": norm,
        "annual_aggregate": vendor_aggregates.get(norm),
        "matched": norm in vendor_aggregates,
        "is_govt_vendor": lookup_govt_vendor(vendor),
    }


# ── Threshold verification (deterministic, no session read) ──────────────

def _verify_threshold(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Given a candidate section + a vendor's annual aggregate amount, does TDS apply?

    Returns a structured verdict the LLM can use to flip its recommendation.
    """
    section = args.get("section", "")
    aggregate = float(args.get("aggregate_amount") or 0)
    single = args.get("single_amount")
    rule = TDS_THRESHOLDS.get(section, {})
    agg_limit = rule.get("aggregate_annual")
    monthly = rule.get("monthly")
    single_limit = rule.get("single_txn")

    below_agg = agg_limit is not None and aggregate < agg_limit
    above_single = single_limit is not None and single is not None and float(single) > single_limit
    # For monthly thresholds (194-I etc), we don't have monthly slice here;
    # use aggregate / 12 as a coarse proxy.
    monthly_above = False
    if monthly is not None:
        monthly_above = aggregate / 12 > monthly

    if section in TDS_THRESHOLDS:
        if monthly is not None:
            tds_required = monthly_above
            verdict = "apply" if monthly_above else "skip_below_monthly"
        else:
            tds_required = not (below_agg and not above_single)
            verdict = "apply" if tds_required else "skip_below_threshold"
    else:
        tds_required = None
        verdict = "section_unknown"

    return {
        "section": section,
        "aggregate_amount": aggregate,
        "aggregate_annual_limit": agg_limit,
        "single_txn_limit": single_limit,
        "monthly_limit": monthly,
        "tds_required": tds_required,
        "verdict": verdict,
        "rule_description": rule.get("description"),
    }


# ── Income-vs-expense classifier (deterministic) ─────────────────────────

INCOME_PATTERNS = [
    "received", "accrued on", "accrued from", "earned on", "earned from",
    "income tax refund", "refundable", "refund received",
    "discount earned", "discount received", "rebate received", "rebate earned",
    "incentive received", "scheme received",
    "interest accrued",  # FD interest accrual = income side
    "ddb", "duty drawback", "rodtep", "meis", "seis",
    "foreign inward remittance",
    "sales account", "sales discount",
    "output cgst", "output sgst", "output igst",
]

# Vendor types that strongly suggest the entity is the PAYEE (income),
# not the payer.
PAYEE_VENDOR_PATTERNS = [
    "bank", "co-operative", "co operative", "post office",
    "customer ", "client ", "buyer ",
]


def _classify_income_vs_expense(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    description = (args.get("description") or "").lower()
    vendor = (args.get("vendor") or "").lower()

    desc_match = next((p for p in INCOME_PATTERNS if p in description), None)
    vendor_match = next((p for p in PAYEE_VENDOR_PATTERNS if p in vendor), None) if vendor else None

    is_income = bool(desc_match) or bool(vendor_match)
    return {
        "description": args.get("description"),
        "vendor": args.get("vendor"),
        "is_income_side": is_income,
        "matched_description_pattern": desc_match,
        "matched_vendor_pattern": vendor_match,
        "rationale": (
            f"Description matches income pattern '{desc_match}'." if desc_match
            else f"Vendor name matches payee pattern '{vendor_match}'." if vendor_match
            else "No income-side signal — treat as expense."
        ),
    }


# ── Web research (batched, grounded) ─────────────────────────────────────

async def _research_descriptions_batch(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    descriptions: list[str] = args.get("descriptions") or []
    if not descriptions:
        return {"summaries": {}, "mock": False}
    if not os.getenv("GEMINI_API_KEY"):
        return {
            "summaries": {d: f"Mock research for '{d}'. Real Gemini grounding needs GEMINI_API_KEY." for d in descriptions},
            "mock": True,
        }
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        bullet_list = "\n".join(f"- {d}" for d in descriptions)
        prompt = (
            "You are a senior Indian TDS expert (FY 2025-26). For each expense "
            "description below, return a 2-3 sentence note: which TDS section is "
            "most likely, the rate, threshold, and any practical exemption. Reply "
            "as JSON: {\"<description>\": \"<note>\", ...}. JSON only.\n\n"
            f"{bullet_list}"
        )
        response = await client.aio.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ),
        )
        text = (response.text or "").strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        import json
        try:
            summaries = json.loads(text)
        except json.JSONDecodeError:
            summaries = {d: response.text[:300] for d in descriptions}
        for d in descriptions:
            summaries.setdefault(d, "")
        return {"summaries": summaries, "mock": False}
    except Exception as e:  # noqa: BLE001
        return {
            "summaries": {d: f"Research failed: {type(e).__name__}." for d in descriptions},
            "mock": True, "error": str(e)[:200],
        }


# ── Escalation ──────────────────────────────────────────────────────────

def _ask_orchestrator(args: dict[str, Any], **ctx: Any) -> Any:
    raise EscalationRequest(
        kind="ask_orchestrator",
        payload={
            "from_agent": "flag_resolver",
            "question": args.get("question", ""),
            "options": args.get("options", []),
            "context": args.get("context", ""),
            "recommended": args.get("recommended"),
        },
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="check_known_exemptions",
        description="Look up a list of expense descriptions in the deterministic Indian TDS KB. FREE — call this BEFORE web research. Returns one entry per description (or null if no KB hit).",
        parameters={"type": "object",
                    "properties": {"descriptions": {"type": "array", "items": {"type": "string"}}},
                    "required": ["descriptions"]},
        fn=_check_known_exemptions,
    ),
    ToolSpec(
        name="lookup_vendor_aggregate",
        description="Get the annual aggregate amount AND govt-vendor flag for a vendor. Read against the data a1 handed to you.",
        parameters={"type": "object", "properties": {"vendor": {"type": "string"}}, "required": ["vendor"]},
        fn=_lookup_vendor_aggregate,
    ),
    ToolSpec(
        name="verify_threshold",
        description=(
            "MANDATORY before recommending action='apply'. Given the candidate section "
            "and the vendor's annual aggregate, returns whether TDS is actually required. "
            "If verdict='skip_below_threshold' or 'skip_below_monthly', flip your recommendation to skip."
        ),
        parameters={"type": "object", "properties": {
            "section": {"type": "string"},
            "aggregate_amount": {"type": "number"},
            "single_amount": {"type": "number"},
        }, "required": ["section", "aggregate_amount"]},
        fn=_verify_threshold,
    ),
    ToolSpec(
        name="classify_income_vs_expense",
        description=(
            "MANDATORY check. Detects if a description / vendor pair is income-side "
            "(receipt) rather than an expense. If is_income_side=true, recommend "
            "skip(income_side) at confidence:high — there's nothing for the entity to deduct."
        ),
        parameters={"type": "object", "properties": {
            "description": {"type": "string"}, "vendor": {"type": "string"},
        }, "required": ["description"]},
        fn=_classify_income_vs_expense,
    ),
    ToolSpec(
        name="research_descriptions_batch",
        description="ONE Gemini-grounded call covering all KB-miss descriptions. Use AFTER check_known_exemptions, never before.",
        parameters={"type": "object",
                    "properties": {"descriptions": {"type": "array", "items": {"type": "string"}}},
                    "required": ["descriptions"]},
        fn=_research_descriptions_batch,
    ),
    ToolSpec(
        name="ask_orchestrator",
        description="Last resort. Escalate a single genuinely-unusual case to a1.",
        parameters={"type": "object", "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "context": {"type": "string"}, "recommended": {"type": "string"},
        }, "required": ["question", "options", "context"]},
        fn=_ask_orchestrator,
    ),
]
