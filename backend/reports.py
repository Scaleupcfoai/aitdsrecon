"""Report aggregation.

Given tds_results (per-row), build the three views used by the UI:
  - party view:    vendor | total_paid | total_tds | sections[]
  - section view:  section | total_base | total_tds | row_count
  - quarter view:  quarter | total_tds | deposit_due | fy
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from tds_knowledge.pan_utils import normalize_name
from tds_knowledge.thresholds import get_deposit_due_date, get_fy_label, get_quarter


def _safe_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def build_views(tds_results: dict[str, Any] | None) -> dict[str, Any]:
    rows = (tds_results or {}).get("results") or []

    # ── Party view ─────────────────────────────────────────────────────
    by_vendor: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "vendor": "",
        "vendor_normalized": "",
        "pan": "",
        "total_paid": 0.0,
        "total_tds": 0.0,
        "sections": set(),
        "row_count": 0,
    })
    for r in rows:
        key = normalize_name(r.get("vendor") or "")
        entry = by_vendor[key]
        entry["vendor"] = entry["vendor"] or (r.get("vendor") or "")
        entry["vendor_normalized"] = key
        entry["pan"] = entry["pan"] or (r.get("pan") or "")
        entry["total_paid"] += float(r.get("amount") or 0)
        entry["total_tds"] += float(r.get("tds_amount") or 0)
        if r.get("section"):
            entry["sections"].add(r["section"])
        entry["row_count"] += 1
    party_view = [
        {
            "vendor": v["vendor"],
            "pan": v["pan"],
            "total_paid": round(v["total_paid"], 2),
            "total_tds": round(v["total_tds"], 2),
            "sections": sorted(v["sections"]),
            "row_count": v["row_count"],
        }
        for v in by_vendor.values()
    ]
    party_view.sort(key=lambda x: x["total_paid"], reverse=True)

    # ── Section view ───────────────────────────────────────────────────
    by_section: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "section": "",
        "total_base": 0.0,
        "total_tds": 0.0,
        "row_count": 0,
        "vendor_count": set(),
    })
    for r in rows:
        sec = r.get("section") or "Unclassified"
        entry = by_section[sec]
        entry["section"] = sec
        entry["total_base"] += float(r.get("amount") or 0)
        entry["total_tds"] += float(r.get("tds_amount") or 0)
        entry["row_count"] += 1
        entry["vendor_count"].add(normalize_name(r.get("vendor") or ""))
    section_view = [
        {
            "section": s["section"],
            "total_base": round(s["total_base"], 2),
            "total_tds": round(s["total_tds"], 2),
            "row_count": s["row_count"],
            "vendor_count": len(s["vendor_count"]),
        }
        for s in by_section.values()
    ]
    section_view.sort(key=lambda x: x["total_tds"], reverse=True)

    # ── Quarter view ───────────────────────────────────────────────────
    by_quarter: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "quarter": "",
        "fy": "",
        "total_tds": 0.0,
        "row_count": 0,
        "deposit_due_dates": set(),
    })
    for r in rows:
        d = _safe_date(r.get("date"))
        if not d:
            continue
        q = get_quarter(d)
        fy = get_fy_label(d)
        key = (fy, q)
        entry = by_quarter[key]
        entry["quarter"] = q
        entry["fy"] = fy
        entry["total_tds"] += float(r.get("tds_amount") or 0)
        entry["row_count"] += 1
        entry["deposit_due_dates"].add(get_deposit_due_date(d).isoformat())
    quarter_view = [
        {
            "quarter": q["quarter"],
            "fy": q["fy"],
            "total_tds": round(q["total_tds"], 2),
            "row_count": q["row_count"],
            "deposit_due_dates": sorted(q["deposit_due_dates"]),
        }
        for q in by_quarter.values()
    ]
    quarter_view.sort(key=lambda x: (x["fy"], x["quarter"]))

    return {
        "party_view": party_view,
        "section_view": section_view,
        "quarter_view": quarter_view,
        "totals": {
            "total_paid": round(sum(r["total_paid"] for r in party_view), 2),
            "total_tds": round(sum(s["total_tds"] for s in section_view), 2),
            "row_count": sum(s["row_count"] for s in section_view),
        },
    }
