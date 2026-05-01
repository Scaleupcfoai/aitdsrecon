"""b1 tool implementations + Gemini function declarations.

Tools are deterministic Python. The file path is passed via tool_context
(not a tool argument) so the LLM cannot accidentally read a different file.

Two shapes of tools:
  FLAT-FILE tools
    fingerprint_columns / read_headers / read_samples
  TALLY-REGISTER tools (from aitdsrecon parser_agent)
    list_sheets / sniff_sheet / extract_tally_rows
  + ask_orchestrator for doubts (format unclear, PAN policy, etc.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from agent_runtime import EscalationRequest, ToolSpec

from . import core_tally


# ── Flat-file tools (unchanged) ──────────────────────────────────────────

def _load_dataframe(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=0, dtype=str, keep_default_na=False)
    raise ValueError(f"Unsupported file extension: {suffix}")


def _fingerprint(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    path = Path(ctx["file_path"])
    df = _load_dataframe(path)
    samples_per_column = {
        col: [str(v) for v in df[col].head(5).tolist()]
        for col in df.columns
    }
    return {
        "headers": list(df.columns),
        "row_count": int(len(df)),
        "samples_per_column": samples_per_column,
    }


def _read_headers(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    path = Path(ctx["file_path"])
    df = _load_dataframe(path)
    return {"headers": list(df.columns), "row_count": int(len(df))}


def _read_samples(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    path = Path(ctx["file_path"])
    n = int(args.get("n", 10))
    n = max(1, min(n, 50))
    df = _load_dataframe(path).head(n)
    return {
        "headers": list(df.columns),
        "rows": [[str(v) for v in row] for row in df.values.tolist()],
    }


# ── Tally-register tools ────────────────────────────────────────────────

def _list_sheets(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Return every sheet name + dimensions. First move for Excel workbooks."""
    path = ctx["file_path"]
    sheets = core_tally.list_sheets(path)
    return {"sheets": sheets, "count": len(sheets)}


def _sniff_sheet(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Classify a single sheet and return its real header row + headers + 3 samples.

    Classification returns one of:
      - journal               (large journal register with many expense-head ledgers)
      - purchase_gst_exp      (expense vouchers with GST breakup; base = sum of expense heads)
      - purchase_plain        (goods-purchase register; amount = Value column, pre-GST)
      - flat                  (ordinary 1-row-per-expense spreadsheet)
      - unknown               (couldn't classify; don't extract from this sheet)
    """
    path = ctx["file_path"]
    sheet_name = args.get("sheet_name", "")
    return core_tally.sniff_sheet(path, sheet_name)


def _extract_tally_rows(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Extract normalized expense rows from one sheet and append them to the session.

    Rows are persisted at session.extracted_rows (so the LLM doesn't have to echo
    them). Returns a small summary: row_count + per-section breakdown.
    """
    from session import load_session  # local import to avoid cycle at module load

    path = ctx["file_path"]
    session_id = ctx["session_id"]
    sheet_name = args.get("sheet_name", "")
    sheet_type = args.get("sheet_type", "")

    result = core_tally.extract_tally_rows(path, sheet_name, sheet_type)
    new_rows = result["rows"]

    # Apply the PAN policy already recorded on the session (if any).
    session = load_session(session_id)
    pan_policy = (session.pan_policy or "").strip()
    if pan_policy == "assume_pan":
        # Leave PAN blank; b2 / rates.py will apply the section rate with a
        # PAN-assumed entity type. Nothing to do here.
        pass
    elif pan_policy == "apply_206aa":
        for r in new_rows:
            r["pan_policy"] = "apply_206aa"  # calculator will force 20%
    # else: no policy yet (b1 will ask orchestrator before calling this).

    existing = list(session.extracted_rows or [])
    existing.extend(new_rows)
    session.extracted_rows = existing
    session.save()

    # Per-section summary for b1's reasoning.
    from collections import Counter
    section_counter: Counter = Counter()
    for r in new_rows:
        section_counter[r.get("section_hint") or "unclassified"] += 1
    return {
        "sheet": sheet_name,
        "sheet_type": sheet_type,
        "extracted_count": len(new_rows),
        "session_total_rows": len(existing),
        "section_breakdown": dict(section_counter),
    }


def _set_pan_policy(args: dict[str, Any], **ctx: Any) -> dict[str, Any]:
    """Record the user-selected PAN policy on the session.

    Only called AFTER ask_orchestrator has resolved. Values: 'apply_206aa' or 'assume_pan'.
    """
    from session import load_session

    policy = args.get("policy", "").strip()
    if policy not in ("apply_206aa", "assume_pan"):
        return {"error": f"invalid policy: {policy!r}. Use 'apply_206aa' or 'assume_pan'."}
    session = load_session(ctx["session_id"])
    session.pan_policy = policy
    session.save()
    return {"pan_policy": policy}


# ── Escalation ────────────────────────────────────────────────────────────

def _ask_orchestrator(args: dict[str, Any], **ctx: Any) -> Any:
    raise EscalationRequest(
        kind="ask_orchestrator",
        payload={
            "from_agent": "column_reader",
            "question": args.get("question", ""),
            "options": args.get("options", []),
            "context": args.get("context", ""),
            "recommended": args.get("recommended"),
        },
    )


TOOLS: list[ToolSpec] = [
    # Flat-file tools
    ToolSpec(
        name="fingerprint_columns",
        description=(
            "FLAT files only. Read headers and 5 sample values per column. "
            "Use when the uploaded file is a single-sheet CSV or simple Excel."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_fingerprint,
    ),
    ToolSpec(
        name="read_headers",
        description="FLAT files only. Read just the column headers.",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_read_headers,
    ),
    ToolSpec(
        name="read_samples",
        description="FLAT files only. Read the first N rows (1-50).",
        parameters={
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
        fn=_read_samples,
    ),

    # Tally tools
    ToolSpec(
        name="list_sheets",
        description=(
            "List every sheet in the uploaded Excel with row/col counts. "
            "FIRST MOVE for any .xlsx file — multi-sheet workbooks are usually Tally exports."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_list_sheets,
    ),
    ToolSpec(
        name="sniff_sheet",
        description=(
            "Classify one sheet and fetch its real header row + 3 sample rows. "
            "Returns type in {journal, purchase_gst_exp, purchase_plain, flat, unknown}. "
            "Call once per sheet after list_sheets."
        ),
        parameters={
            "type": "object",
            "properties": {"sheet_name": {"type": "string"}},
            "required": ["sheet_name"],
        },
        fn=_sniff_sheet,
    ),
    ToolSpec(
        name="extract_tally_rows",
        description=(
            "Extract normalized expense rows from one Tally sheet and save them to the session. "
            "Only call after sniff_sheet classified the sheet as journal / purchase_gst_exp / purchase_plain. "
            "Call set_pan_policy BEFORE this tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sheet_name": {"type": "string"},
                "sheet_type": {
                    "type": "string",
                    "description": "journal | purchase_gst_exp | purchase_plain",
                },
            },
            "required": ["sheet_name", "sheet_type"],
        },
        fn=_extract_tally_rows,
    ),
    ToolSpec(
        name="set_pan_policy",
        description=(
            "Record the user-chosen PAN policy for Tally files. "
            "'apply_206aa' = deduct 20% on every row (safest when PANs unknown). "
            "'assume_pan' = compute at standard section rate assuming PANs are on file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "policy": {
                    "type": "string",
                    "description": "apply_206aa | assume_pan",
                },
            },
            "required": ["policy"],
        },
        fn=_set_pan_policy,
    ),

    # Escalation
    ToolSpec(
        name="ask_orchestrator",
        description=(
            "Ask the orchestrator a specific question. Use for: "
            "(a) PAN policy on a Tally file, (b) Amount column looks GST-inclusive, "
            "(c) any ambiguity you can't resolve with other tools."
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
