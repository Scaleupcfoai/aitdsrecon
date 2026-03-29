"""
Intelligent Column Mapper — takes any XLSX/CSV and figures out what each column means.

3-step cross-verification:
1. Rule-based + fuzzy matching → confidence score per column
2. Send ALL columns to LLM (with headers + sample data + our fuzzy suggestions)
3. Cross-verify: fuzzy agrees with LLM → auto-map. Disagreement → ask user.

Saves confirmed mappings to column_map table for reuse (same company, same format = instant).

Usage:
    from app.services.column_mapper import ColumnMapper
    mapper = ColumnMapper(repo)
    result = mapper.map_file("path/to/file.xlsx", company_id="abc-123")
"""

import csv
import re
from difflib import SequenceMatcher
from pathlib import Path

import openpyxl
from groq import Groq

from app.config import settings


# ═══════════════════════════════════════════════════════════
# Known field patterns — what we're looking for in any file
# ═══════════════════════════════════════════════════════════

# Target fields for TDS entries (Form 26 side)
TDS_FIELDS = {
    "party_name": {
        "keywords": ["name", "party", "vendor", "deductee", "payee", "particulars"],
        "description": "Name of the vendor/party",
    },
    "pan": {
        "keywords": ["pan", "pan no", "pan number", "permanent account"],
        "description": "PAN number (10-char alphanumeric like AAACH1234A)",
    },
    "tds_section": {
        "keywords": ["section", "tds section", "sec"],
        "description": "TDS section (194A, 194C, 194H, 194J, etc.)",
    },
    "gross_amount": {
        "keywords": ["amount paid", "amt paid", "gross amount", "amount credited",
                     "amt. paid", "amt paid credited", "payment amount"],
        "description": "Gross amount paid or credited",
    },
    "tds_amount": {
        "keywords": ["tax deducted", "tds amount", "tds deducted", "tax amount",
                     "income tax", "tds amt"],
        "description": "TDS amount deducted",
    },
    "date_of_deduction": {
        "keywords": ["date", "deduction date", "tax date", "payment date",
                     "date of deduction", "date of payment"],
        "description": "Date of TDS deduction or payment",
    },
    "tax_rate": {
        "keywords": ["rate", "tax rate", "tds rate", "rate %", "percentage"],
        "description": "TDS rate percentage",
    },
    "certificate_number": {
        "keywords": ["certificate", "cert no", "certificate no", "tds certificate"],
        "description": "TDS certificate number",
    },
}

# Target fields for ledger entries (books side)
LEDGER_FIELDS = {
    "party_name": {
        "keywords": ["particulars", "party", "vendor", "name", "ledger"],
        "description": "Vendor/party name",
    },
    "amount": {
        "keywords": ["amount", "gross total", "total", "value", "debit", "credit"],
        "description": "Transaction amount",
    },
    "invoice_number": {
        "keywords": ["voucher", "voucher no", "invoice", "bill no", "ref"],
        "description": "Invoice or voucher number",
    },
    "invoice_date": {
        "keywords": ["date"],
        "description": "Transaction date",
    },
    "expense_type": {
        "keywords": ["expense", "account", "head", "nature", "type", "ledger"],
        "description": "Expense head / account type",
    },
}


# ═══════════════════════════════════════════════════════════
# Step 1: Read file headers + sample data
# ═══════════════════════════════════════════════════════════

def read_file_headers(filepath: str) -> list[dict]:
    """Read headers and sample data from XLSX or CSV.

    Returns list of sheet results, each with:
        {sheet_name, header_row, headers: [{col_index, col_letter, name}], sample_rows: [[values]]}
    """
    path = Path(filepath)

    if path.suffix.lower() in (".xlsx", ".xls"):
        return _read_xlsx_headers(filepath)
    elif path.suffix.lower() == ".csv":
        return [_read_csv_headers(filepath)]
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}. Use XLSX or CSV.")


def _read_xlsx_headers(filepath: str) -> list[dict]:
    """Read headers from all sheets in an XLSX file."""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    results = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if ws.max_row < 2:
            continue  # empty sheet

        # Find header row — scan first 15 rows, pick the one with most text cells
        best_row = 1
        best_count = 0
        for row_num in range(1, min(16, ws.max_row + 1)):
            text_count = 0
            for col in range(1, min(ws.max_column + 1, 100)):
                val = ws.cell(row_num, col).value
                if val and isinstance(val, str) and not val.replace(".", "").replace(",", "").isdigit():
                    text_count += 1
            if text_count > best_count:
                best_count = text_count
                best_row = row_num

        # Extract headers
        headers = []
        for col in range(1, ws.max_column + 1):
            val = ws.cell(best_row, col).value
            if val:
                headers.append({
                    "col_index": col,
                    "col_letter": openpyxl.utils.get_column_letter(col),
                    "name": str(val).strip(),
                })

        # Extract 3 sample data rows (after header)
        sample_rows = []
        for row_num in range(best_row + 1, min(best_row + 4, ws.max_row + 1)):
            row_data = []
            for col in range(1, ws.max_column + 1):
                val = ws.cell(row_num, col).value
                row_data.append(str(val) if val is not None else "")
            # Skip if row is all empty or is a total row
            if any(row_data) and not any("total" in str(v).lower() for v in row_data[:3]):
                sample_rows.append(row_data)

        if headers:
            results.append({
                "sheet_name": sheet_name,
                "header_row": best_row,
                "headers": headers,
                "sample_rows": sample_rows[:3],
                "total_rows": ws.max_row - best_row,
                "total_cols": len(headers),
            })

    wb.close()
    return results


def _read_csv_headers(filepath: str) -> dict:
    """Read headers from a CSV file."""
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = []
        for i, row in enumerate(reader):
            rows.append(row)
            if i >= 5:
                break

    # First row with multiple text values is the header
    header_row_idx = 0
    for i, row in enumerate(rows):
        text_count = sum(1 for v in row if v and not v.replace(".", "").replace(",", "").isdigit())
        if text_count >= 3:
            header_row_idx = i
            break

    headers = [
        {"col_index": j + 1, "col_letter": chr(65 + j) if j < 26 else f"C{j}", "name": v.strip()}
        for j, v in enumerate(rows[header_row_idx]) if v.strip()
    ]

    sample_rows = rows[header_row_idx + 1: header_row_idx + 4]

    return {
        "sheet_name": "CSV",
        "header_row": header_row_idx + 1,
        "headers": headers,
        "sample_rows": sample_rows,
        "total_rows": "unknown",
        "total_cols": len(headers),
    }


# ═══════════════════════════════════════════════════════════
# Step 2: Fuzzy matching — score each column against known fields
# ═══════════════════════════════════════════════════════════

def fuzzy_match_columns(headers: list[dict], field_definitions: dict) -> list[dict]:
    """For each header, find the best matching field using keyword similarity.

    Returns list of:
        {col_name, suggested_field, confidence, method}
    """
    results = []

    for header in headers:
        col_name = header["name"].lower().strip()
        best_field = None
        best_score = 0.0
        best_method = "none"

        for field_name, field_def in field_definitions.items():
            for keyword in field_def["keywords"]:
                keyword_lower = keyword.lower()

                # Exact match
                if col_name == keyword_lower:
                    score = 1.0
                    method = "exact"
                # Column contains the keyword
                elif keyword_lower in col_name:
                    score = 0.7 + (len(keyword_lower) / len(col_name)) * 0.2
                    method = "contains"
                # Keyword contains the column name
                elif col_name in keyword_lower:
                    score = 0.6 + (len(col_name) / len(keyword_lower)) * 0.2
                    method = "reverse_contains"
                # Sequence similarity
                else:
                    score = SequenceMatcher(None, col_name, keyword_lower).ratio()
                    method = "sequence"

                if score > best_score:
                    best_score = score
                    best_field = field_name
                    best_method = method

        results.append({
            "col_name": header["name"],
            "col_index": header["col_index"],
            "suggested_field": best_field,
            "confidence": round(best_score, 2),
            "method": best_method,
        })

    return results


# ═══════════════════════════════════════════════════════════
# Step 3: LLM verification — send headers + fuzzy results to Groq
# ═══════════════════════════════════════════════════════════

LLM_SYSTEM_PROMPT = """You are an expert accountant who understands Indian accounting file formats — Tally exports, Form 26 TDS registers, Trial Balances, and expense ledgers.

Given a list of column headers, sample data, and suggested mappings from a fuzzy matching system, your job is to:
1. Verify or correct each column mapping
2. Identify the document type (Form 26, Tally Journal, Tally GST Exp, Tally Purchase, Trial Balance, Expense Ledger)
3. Flag any columns that need human review

For each column, respond with:
- field: the correct target field name (or "skip" for irrelevant columns, or "unknown" if unsure)
- confidence: your confidence (0.0 to 1.0)
- reason: brief explanation

Respond in valid JSON format only. No markdown, no explanation outside JSON."""


def llm_verify_mappings(
    sheet_name: str,
    headers: list[dict],
    sample_rows: list[list],
    fuzzy_results: list[dict],
) -> dict:
    """Send columns + fuzzy suggestions to LLM for verification.

    Returns:
        {
            document_type: "form26" | "tally_journal" | "tally_gst_exp" | ...,
            mappings: [{col_name, field, confidence, reason}],
            needs_user_review: [col_names that LLM isn't sure about]
        }
    """
    if not settings.groq_api_key:
        # LLM not available — return fuzzy results as-is
        return {
            "document_type": "unknown",
            "mappings": [
                {
                    "col_name": r["col_name"],
                    "field": r["suggested_field"] if r["confidence"] >= 0.9 else "unknown",
                    "confidence": r["confidence"],
                    "reason": f"Fuzzy match ({r['method']}), LLM not available",
                }
                for r in fuzzy_results
            ],
            "needs_user_review": [r["col_name"] for r in fuzzy_results if r["confidence"] < 0.9],
        }

    # Build the prompt
    columns_info = []
    for fr in fuzzy_results:
        # Get sample values for this column
        col_idx = fr["col_index"] - 1
        sample_values = []
        for row in sample_rows:
            if col_idx < len(row) and row[col_idx]:
                sample_values.append(str(row[col_idx])[:50])

        columns_info.append({
            "column_name": fr["col_name"],
            "fuzzy_suggestion": fr["suggested_field"],
            "fuzzy_confidence": fr["confidence"],
            "sample_values": sample_values[:3],
        })

    user_prompt = f"""Sheet: "{sheet_name}"
Total columns: {len(headers)}

Columns with fuzzy matching results and sample data:
{_format_columns_for_llm(columns_info)}

Available target fields for TDS entries: {list(TDS_FIELDS.keys())}
Available target fields for ledger entries: {list(LEDGER_FIELDS.keys())}

Respond with JSON:
{{
    "document_type": "form26 | tally_journal | tally_gst_exp | tally_purchase | trial_balance | expense_ledger",
    "mappings": [
        {{"col_name": "...", "field": "...", "confidence": 0.95, "reason": "..."}}
    ],
    "needs_user_review": ["col_name1", "col_name2"]
}}"""

    try:
        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # low temperature = more deterministic
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        import json
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        # LLM failed — fall back to fuzzy results
        print(f"[ColumnMapper] LLM call failed: {e}")
        return {
            "document_type": "unknown",
            "mappings": [
                {
                    "col_name": r["col_name"],
                    "field": r["suggested_field"] if r["confidence"] >= 0.9 else "unknown",
                    "confidence": r["confidence"],
                    "reason": f"Fuzzy only (LLM error: {str(e)[:50]})",
                }
                for r in fuzzy_results
            ],
            "needs_user_review": [r["col_name"] for r in fuzzy_results if r["confidence"] < 0.9],
        }


def _format_columns_for_llm(columns_info: list[dict]) -> str:
    """Format column info for LLM prompt."""
    lines = []
    for c in columns_info:
        samples = ", ".join(c["sample_values"]) if c["sample_values"] else "no data"
        lines.append(
            f'  - "{c["column_name"]}" → fuzzy suggests "{c["fuzzy_suggestion"]}" '
            f'(confidence: {c["fuzzy_confidence"]}) | samples: [{samples}]'
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Step 4: Cross-verify fuzzy vs LLM
# ═══════════════════════════════════════════════════════════

def cross_verify(fuzzy_results: list[dict], llm_result: dict) -> list[dict]:
    """Compare fuzzy and LLM results. Agreement = high confidence. Disagreement = flag.

    Returns final mapping list:
        [{col_name, field, confidence, source, needs_review}]
    """
    llm_mappings = {m["col_name"]: m for m in llm_result.get("mappings", [])}
    needs_review = set(llm_result.get("needs_user_review", []))
    final = []

    for fr in fuzzy_results:
        col_name = fr["col_name"]
        fuzzy_field = fr["suggested_field"]
        fuzzy_conf = fr["confidence"]

        llm_m = llm_mappings.get(col_name, {})
        llm_field = llm_m.get("field", "unknown")
        llm_conf = llm_m.get("confidence", 0)
        llm_reason = llm_m.get("reason", "")

        if llm_field in ("skip", "unknown", None):
            # LLM says skip or doesn't know
            if fuzzy_conf >= 0.9:
                # Fuzzy is very confident — trust it but flag
                final.append({
                    "col_name": col_name,
                    "field": fuzzy_field,
                    "confidence": fuzzy_conf * 0.8,  # discount slightly
                    "source": "fuzzy_only",
                    "reason": f"LLM unsure, fuzzy confident ({fr['method']})",
                    "needs_review": col_name in needs_review,
                })
            else:
                # Both unsure — skip or flag
                final.append({
                    "col_name": col_name,
                    "field": llm_field if llm_field != "unknown" else fuzzy_field,
                    "confidence": max(fuzzy_conf, llm_conf) * 0.5,
                    "source": "unresolved",
                    "reason": llm_reason or "Neither fuzzy nor LLM confident",
                    "needs_review": True,
                })
        elif fuzzy_field == llm_field:
            # AGREEMENT — highest confidence
            final.append({
                "col_name": col_name,
                "field": llm_field,
                "confidence": min(1.0, (fuzzy_conf + llm_conf) / 2 + 0.1),  # boost for agreement
                "source": "both_agree",
                "reason": llm_reason,
                "needs_review": False,
            })
        else:
            # DISAGREEMENT — trust LLM but flag for review
            final.append({
                "col_name": col_name,
                "field": llm_field,
                "confidence": llm_conf * 0.7,  # discount for disagreement
                "source": "llm_override",
                "reason": f"LLM: {llm_reason}. Fuzzy suggested: {fuzzy_field}",
                "needs_review": True,
            })

    return final


# ═══════════════════════════════════════════════════════════
# Main: ColumnMapper class
# ═══════════════════════════════════════════════════════════

class ColumnMapper:
    """Intelligent column mapper — reads any file, maps columns, saves to DB.

    Usage:
        mapper = ColumnMapper(repo)
        result = mapper.map_file("path/to/file.xlsx", company_id="abc-123", file_type="tds")
    """

    def __init__(self, repo=None):
        self.repo = repo

    def map_file(self, filepath: str, company_id: str = "",
                 file_type: str = "auto") -> dict:
        """Map columns in a file. Returns mapping result.

        Args:
            filepath: Path to XLSX or CSV file
            company_id: If set, checks for saved mappings first
            file_type: "tds", "ledger", or "auto" (detect from content)

        Returns:
            {
                sheets: [{
                    sheet_name, document_type, header_row,
                    mappings: [{col_name, field, confidence, source, needs_review}],
                    needs_user_review: [col_names],
                }]
            }
        """
        # Check for saved mappings first
        if company_id and self.repo and file_type != "auto":
            saved = self.repo.column_maps.get_confirmed(company_id, file_type)
            if saved:
                return {
                    "sheets": [{
                        "sheet_name": "saved",
                        "document_type": "saved",
                        "header_row": 0,
                        "mappings": [
                            {"col_name": s.source_column, "field": s.mapped_to,
                             "confidence": 1.0, "source": "saved", "needs_review": False}
                            for s in saved
                        ],
                        "needs_user_review": [],
                        "from_cache": True,
                    }],
                }

        # Read file headers + sample data
        sheets = read_file_headers(filepath)

        result_sheets = []
        for sheet in sheets:
            # Pick field definitions based on file_type or auto-detect
            fields = TDS_FIELDS if file_type == "tds" else LEDGER_FIELDS
            if file_type == "auto":
                # If headers contain TDS-specific keywords, use TDS fields
                all_headers = " ".join(h["name"].lower() for h in sheet["headers"])
                if any(kw in all_headers for kw in ["section", "tax deducted", "tds", "deduction"]):
                    fields = TDS_FIELDS
                else:
                    fields = LEDGER_FIELDS

            # Step 1: Fuzzy match
            fuzzy_results = fuzzy_match_columns(sheet["headers"], fields)

            # Step 2: LLM verify
            llm_result = llm_verify_mappings(
                sheet["sheet_name"],
                sheet["headers"],
                sheet["sample_rows"],
                fuzzy_results,
            )

            # Step 3: Cross-verify
            final_mappings = cross_verify(fuzzy_results, llm_result)

            needs_review = [m["col_name"] for m in final_mappings if m.get("needs_review")]

            result_sheets.append({
                "sheet_name": sheet["sheet_name"],
                "document_type": llm_result.get("document_type", "unknown"),
                "header_row": sheet["header_row"],
                "total_rows": sheet["total_rows"],
                "mappings": final_mappings,
                "needs_user_review": needs_review,
            })

            # Save confirmed mappings to DB (confidence > 0.8 and not needing review)
            if company_id and self.repo:
                ft = "tds" if fields == TDS_FIELDS else "ledger"
                for m in final_mappings:
                    if m["confidence"] >= 0.8 and not m.get("needs_review"):
                        self.repo.column_maps.upsert(
                            company_id=company_id,
                            file_type=ft,
                            source_column=m["col_name"],
                            mapped_to=m["field"],
                            confidence=m["confidence"],
                        )

        return {"sheets": result_sheets}
