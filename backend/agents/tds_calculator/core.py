"""Deterministic TDS calculation core.

Two entry points into `calculate_batch`:
  (a) flat file    - pass file_path + column mapping; we parse the sheet into rows.
  (b) pre-extracted - pass `rows` already normalized (Tally case from b1's extract).

Normalized row shape (produced by either path before evaluation):
  {
    "row_id":       int,
    "date":         ISO string | None,
    "vendor":       str,
    "pan":          str (may be "" in Tally files),
    "amount":       float | None,
    "description":  str (column name for Tally, description field for flat),
    "section_hint": str | None,   # from Tally column name; None for flat
    "source":       str | None,   # journal / purchase_gst_exp / purchase_plain / None
    "voucher_no":   str | None,
    "pan_policy":   str | None,   # per-row override; "apply_206aa" forces 20%
  }

Flag reasons:
  - ambiguous_section      multiple possible TDS sections
  - unknown_expense        no section keyword match
  - missing_pan            PAN missing/invalid -> Section 206AA decision
  - near_threshold         vendor aggregate within ~10% of annual threshold
  - gst_inclusive_amount   amount column looks GST-inclusive (flat files only)
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tds_knowledge.pan_utils import is_valid_pan, normalize_name
from tds_knowledge.rates import (
    SECTION_206AA_RATE,
    entity_type_from_pan,
    expected_rate,
)
from tds_knowledge.expense_head_kb import lookup_kb
from tds_knowledge.section_classifier import (
    AMBIGUOUS_EXPENSE_HEADS,
    classify_expense_head,
)
from tds_knowledge.thresholds import TDS_THRESHOLDS


# ── Parsing helpers ──────────────────────────────────────────────────────

def _parse_amount(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("Rs.", "").replace("Rs", "").replace("INR", "")
    s = s.replace("₹", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d %H:%M:%S",
)


def _parse_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


_GST_RATIOS = (1.18, 1.12, 1.05, 1.28, 1.03)


def _looks_gst_inclusive(samples: list[float], tolerance: float = 0.5) -> bool:
    if len(samples) < 3:
        return False
    hits = 0
    for amt in samples:
        if amt <= 0:
            continue
        for ratio in _GST_RATIOS:
            base = amt / ratio
            if abs(round(base / 100) * 100 - base) < tolerance:
                hits += 1
                break
    return hits / max(1, len(samples)) >= 0.6


def _load_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=0, dtype=str, keep_default_na=False)
    raise ValueError(f"Unsupported file extension: {suffix}")


# ── Path A: flat file + mapping -> normalized rows ───────────────────────

def _rows_from_flat_file(file_path: str, mapping: dict[str, str]) -> tuple[list[dict[str, Any]], bool]:
    """Read flat file, return normalized rows + gst_suspicion flag."""
    path = Path(file_path)
    df = _load_dataframe(path)

    canon_to_col: dict[str, str] = {}
    for original, canonical in (mapping or {}).items():
        if canonical and canonical != "null" and canonical not in canon_to_col:
            canon_to_col[canonical] = original

    required = {"vendor", "amount", "description"}
    missing = required - canon_to_col.keys()
    if missing:
        raise ValueError(f"missing required columns in mapping: {sorted(missing)}")

    # GST-inclusive heuristic
    amount_samples: list[float] = []
    for _, r in df.head(20).iterrows():
        amt = _parse_amount(r[canon_to_col["amount"]])
        if amt is not None:
            amount_samples.append(amt)
    gst_suspicion = _looks_gst_inclusive(amount_samples)

    rows: list[dict[str, Any]] = []
    for idx, r in df.iterrows():
        rows.append({
            "row_id": int(idx) + 1,
            "date": (_parse_date(r[canon_to_col["date"]]).isoformat()
                     if "date" in canon_to_col and _parse_date(r[canon_to_col["date"]]) else None),
            "vendor": str(r[canon_to_col["vendor"]]).strip(),
            "pan": (str(r[canon_to_col["pan"]]).strip().upper()
                    if "pan" in canon_to_col else ""),
            "amount": _parse_amount(r[canon_to_col["amount"]]),
            "description": str(r[canon_to_col["description"]]).strip(),
            "section_hint": None,
            "source": None,
            "voucher_no": None,
            "pan_policy": None,
        })
    return rows, gst_suspicion


# ── Path B: pre-extracted rows (Tally) -> normalize keys ─────────────────

def _normalize_extracted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        out.append({
            "row_id": int(r.get("row_id") or (i + 1)),
            "date": r.get("date"),
            "vendor": str(r.get("vendor") or "").strip(),
            "pan": str(r.get("pan") or "").strip().upper(),
            "amount": r.get("amount") if isinstance(r.get("amount"), (int, float)) else _parse_amount(r.get("amount")),
            "description": str(r.get("description") or "").strip(),
            "section_hint": r.get("section_hint"),
            "source": r.get("source"),
            "voucher_no": r.get("voucher_no"),
            "pan_policy": r.get("pan_policy"),
        })
    return out


# ── Shared per-row evaluation ────────────────────────────────────────────

def _evaluate(
    rows: list[dict[str, Any]],
    gst_suspicion: bool,
    pan_policy_global: str | None = None,
) -> dict[str, Any]:
    # Vendor aggregates across the whole batch
    vendor_aggregates: dict[str, float] = defaultdict(float)
    for r in rows:
        v = normalize_name(r.get("vendor") or "")
        if v and r.get("amount") is not None:
            vendor_aggregates[v] += float(r["amount"])

    results: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []

    for row in rows:
        row_id = row["row_id"]
        vendor = row["vendor"]
        description = row["description"]
        amount = row["amount"]
        pan_raw = row["pan"]
        section_hint = row.get("section_hint")
        per_row_policy = row.get("pan_policy")
        effective_policy = per_row_policy or pan_policy_global

        row_flags: list[str] = []

        # ── KB short-circuit ──
        # If the unified KB has a HIGH-confidence verdict, we apply it here
        # and the row never gets flagged. Medium / low confidence still flow
        # through the existing classifier + flag pipeline so b3 can review.
        kb_hit = None if section_hint else lookup_kb(description)
        kb_auto_skip = bool(kb_hit and kb_hit["action"] == "skip" and kb_hit["confidence"] == "high")
        kb_auto_apply = bool(
            kb_hit and kb_hit["action"] == "apply" and kb_hit["confidence"] == "high"
            and kb_hit.get("section")
        )

        # Section: honour explicit Tally hint first, then KB apply, else classifier.
        if section_hint:
            sections = [section_hint]
            is_ambiguous = False
        elif kb_hit and kb_hit["action"] == "apply" and kb_hit.get("section"):
            sections = [kb_hit["section"]]
            is_ambiguous = False
        elif kb_hit and kb_hit["action"] == "ask":
            sections = classify_expense_head(description)
            is_ambiguous = True
        else:
            sections = classify_expense_head(description)
            is_ambiguous = (
                (description or "").lower().strip() in AMBIGUOUS_EXPENSE_HEADS
                or any(k in (description or "").lower() for k in AMBIGUOUS_EXPENSE_HEADS)
            )
        picked_section = sections[0] if sections and sections[0] != "unknown" else None

        vendor_norm = normalize_name(vendor)
        aggregate = vendor_aggregates.get(vendor_norm, amount or 0)
        pan_valid = is_valid_pan(pan_raw)

        section: str | None = None
        rate: float | None = None
        tds: float | None = None
        skip_reason: str | None = None

        kb_resolution: dict[str, Any] | None = None
        if kb_auto_skip:
            # ── KB high-confidence skip — auto-resolved, no user popup ──
            section = None
            rate = 0.0
            tds = 0.0
            skip_reason = kb_hit["skip_reason"] or "kb_skip"
            kb_resolution = {
                "auto_resolved": True,
                "source": "kb",
                "category": kb_hit.get("category"),
                "matched_keyword": kb_hit.get("matched_keyword"),
                "rationale": kb_hit.get("rationale"),
            }
        elif picked_section and not is_ambiguous:
            section = picked_section
            threshold = TDS_THRESHOLDS.get(section, {})
            agg_limit = threshold.get("aggregate_annual")
            single_limit = threshold.get("single_txn")
            below_aggregate = agg_limit is not None and aggregate < agg_limit
            above_single = single_limit is not None and (amount or 0) > single_limit
            below_threshold = below_aggregate and not above_single

            if below_threshold:
                skip_reason = "below_threshold"
                rate = 0.0
                tds = 0.0
                if agg_limit and aggregate > 0.9 * agg_limit:
                    row_flags.append("near_threshold")
            else:
                if effective_policy == "apply_206aa":
                    base_rate = expected_rate(section, pan_raw) or 0.0
                    rate = max(base_rate, SECTION_206AA_RATE)
                elif effective_policy == "assume_pan" and not pan_valid:
                    rate = expected_rate(section, "AAACC0000A") or 0.0
                elif pan_valid:
                    rate = expected_rate(section, pan_raw) or 0.0
                else:
                    rate = SECTION_206AA_RATE
                    row_flags.append("missing_pan")
                tds = round((amount or 0) * rate / 100, 2)

            # If the section came from a KB high-confidence apply, mark it auto-resolved.
            if kb_auto_apply:
                kb_resolution = {
                    "auto_resolved": True,
                    "source": "kb",
                    "category": kb_hit.get("category"),
                    "matched_keyword": kb_hit.get("matched_keyword"),
                    "rationale": kb_hit.get("rationale"),
                }
        elif is_ambiguous:
            row_flags.append("ambiguous_section")
        else:
            row_flags.append("unknown_expense")

        # GST suspicion only meaningful for flat files (Tally rows come from
        # specific columns with known GST semantics).
        if gst_suspicion and row.get("source") is None:
            row_flags.append("gst_inclusive_amount")

        result_row = {
            "row_id": row_id,
            "date": row.get("date"),
            "vendor": vendor,
            "pan": pan_raw,
            "entity_type": entity_type_from_pan(pan_raw) if pan_valid else "unknown",
            "amount": amount,
            "description": description,
            "section": section,
            "rate_pct": rate,
            "tds_amount": tds,
            "skip_reason": skip_reason,
            "flags": row_flags,
            "aggregate_for_vendor": round(aggregate, 2),
            "source": row.get("source"),
            "voucher_no": row.get("voucher_no"),
            "kb_resolution": kb_resolution,
        }
        results.append(result_row)

        for f in row_flags:
            flags.append({
                "row_id": row_id,
                "reason": f,
                "vendor": vendor,
                "description": description,
                "amount": amount,
                "pan": pan_raw,
                "current_section": section,
                "possible_sections": sections if f == "ambiguous_section" else None,
                "context": _flag_context(f, description, pan_raw, amount, aggregate, section),
            })

    return {
        "results": results,
        "flags": flags,
        "vendor_aggregates": dict(vendor_aggregates),
        "diagnostics": {
            "row_count": len(results),
            "flag_count": len(flags),
            "auto_resolved_kb_rows": sum(1 for r in results if r.get("kb_resolution")),
            "gst_suspicion_on_amount": gst_suspicion,
            "pan_policy": pan_policy_global,
        },
    }


# ── Public API ───────────────────────────────────────────────────────────

def calculate_batch(
    file_path: str | None = None,
    mapping: dict[str, str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    pan_policy: str | None = None,
) -> dict[str, Any]:
    """Compute TDS across a batch of expenses.

    Call ONE of the two paths:
      calculate_batch(file_path=..., mapping=...)   # flat
      calculate_batch(rows=..., pan_policy=...)      # pre-extracted (Tally)
    """
    if rows is not None:
        normalized = _normalize_extracted(rows)
        return _evaluate(normalized, gst_suspicion=False, pan_policy_global=pan_policy)
    if file_path and mapping is not None:
        try:
            normalized, gst = _rows_from_flat_file(file_path, mapping)
        except ValueError as e:
            return {
                "results": [],
                "flags": [],
                "vendor_aggregates": {},
                "diagnostics": {"error": str(e)},
            }
        return _evaluate(normalized, gst_suspicion=gst, pan_policy_global=pan_policy)
    return {
        "results": [],
        "flags": [],
        "vendor_aggregates": {},
        "diagnostics": {"error": "calculate_batch requires either rows= or file_path+mapping"},
    }


def _flag_context(
    reason: str,
    description: str,
    pan: str,
    amount: float | None,
    aggregate: float,
    section: str | None,
) -> str:
    if reason == "ambiguous_section":
        note = AMBIGUOUS_EXPENSE_HEADS.get(description.lower().strip(), {}).get("note", "")
        return note or f"Expense '{description}' could fall under multiple sections."
    if reason == "unknown_expense":
        return f"No TDS section matches '{description}'. Needs classification."
    if reason == "missing_pan":
        return (
            f"PAN missing or invalid. Section 206AA requires 20% TDS or applicable rate, "
            f"whichever is higher. Current section {section}."
        )
    if reason == "near_threshold":
        return (
            f"Aggregate for this vendor (~Rs {aggregate:,.0f}) is close to the section's "
            f"annual threshold. Confirm whether TDS applies."
        )
    if reason == "gst_inclusive_amount":
        return (
            "Amount column values suggest GST-inclusive figures (many values divisible by "
            "1.18/1.12/1.05). TDS should be on base amount."
        )
    return ""


# ── Individual helper tools (for b2 to drill into a single case) ─────────

def lookup_rate_info(section: str, pan: str) -> dict[str, Any]:
    return {
        "section": section,
        "entity_type": entity_type_from_pan(pan),
        "rate_pct": expected_rate(section, pan),
        "pan_valid": is_valid_pan(pan),
    }


def classify_section_info(description: str) -> dict[str, Any]:
    sections = classify_expense_head(description)
    key = (description or "").lower().strip()
    ambiguous = None
    for keyword, info in AMBIGUOUS_EXPENSE_HEADS.items():
        if keyword in key:
            ambiguous = info
            break
    return {
        "description": description,
        "sections": sections,
        "is_ambiguous": ambiguous is not None,
        "ambiguous_note": ambiguous.get("note") if ambiguous else None,
    }


def check_threshold_info(section: str, aggregate_amount: float, single_amount: float | None = None) -> dict[str, Any]:
    threshold = TDS_THRESHOLDS.get(section, {})
    agg_limit = threshold.get("aggregate_annual")
    single_limit = threshold.get("single_txn")
    below_aggregate = agg_limit is not None and aggregate_amount < agg_limit
    above_single = single_limit is not None and single_amount is not None and single_amount > single_limit
    return {
        "section": section,
        "aggregate_amount": aggregate_amount,
        "single_amount": single_amount,
        "aggregate_annual_limit": agg_limit,
        "single_txn_limit": single_limit,
        "below_aggregate_threshold": below_aggregate,
        "above_single_threshold": above_single,
        "tds_required": not (below_aggregate and not above_single),
        "description": threshold.get("description"),
    }


def apply_206aa_info(applicable_rate_pct: float) -> dict[str, Any]:
    effective = max(applicable_rate_pct, SECTION_206AA_RATE)
    return {
        "applicable_rate_pct": applicable_rate_pct,
        "section_206aa_rate_pct": SECTION_206AA_RATE,
        "effective_rate_pct": effective,
        "note": "Section 206AA: without valid PAN, rate = max(applicable, 20%).",
    }
