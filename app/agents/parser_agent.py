"""
Parser Agent — Parse any XLSX/CSV file using column mapper output.

Zero hardcoded column positions. The column mapper tells us which column
is party_name, which is amount, etc. The parser reads values from those
mapped positions.

Flow:
1. Column mapper identifies file structure (header row, column mappings)
2. Parser reads rows using the mapped column positions
3. Writes to ledger_entry and tds_entry tables
"""

import re
from datetime import datetime, date

import openpyxl

from app.agents.base import AgentBase
from app.services.column_mapper import ColumnMapper, read_file_headers


# ── Helpers ──

def clean_name(raw_name: str) -> dict:
    """Parse Form 26 name field: 'Adi Debnath (34); PAN: AAAAA0001A' → {name, id, pan}"""
    if not raw_name:
        return {"name": "", "id": "", "pan": ""}
    match = re.match(r"^(.+?)\s*\((\d+)\);\s*PAN:\s*(\S+)", str(raw_name))
    if match:
        return {"name": match.group(1).strip(), "id": match.group(2), "pan": match.group(3)}
    # Try PAN-only pattern
    match2 = re.match(r"^(.+?);\s*PAN:\s*(\S+)", str(raw_name))
    if match2:
        return {"name": match2.group(1).strip(), "id": "", "pan": match2.group(2)}
    return {"name": str(raw_name).strip(), "id": "", "pan": ""}


def to_date_str(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, str):
        return val[:10]
    return str(val)[:10]


def safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ── Expense type classification (from knowledge base) ──
# Reads expense keywords from tds_rules.json so they stay in sync

def _build_expense_keywords() -> dict:
    """Build expense keywords from knowledge base."""
    try:
        from app.knowledge import get_sections
        keywords = {}
        section_to_type = {
            "194A": "interest_payment", "194C": "freight_expense",
            "194H": "brokerage", "194I_a": "rent", "194I_b": "rent",
            "194J_a": "consultancy", "194J_b": "professional_fees",
            "194D": "insurance", "194Q": "purchase", "192": "salary",
            "194O": "ecommerce",
        }
        for code, section in get_sections().items():
            exp_type = section_to_type.get(code, "other")
            if exp_type != "other":
                keywords[exp_type] = section.get("expense_keywords", [])
        # Add non-section types
        keywords["tds_deduction"] = ["tds payable"]
        keywords["salary"] = keywords.get("salary", []) + ["bonus", "director's salary"]
        return keywords
    except Exception:
        # Fallback if knowledge base not available
        return {
            "interest_payment": ["interest paid", "interest on loan"],
            "freight_expense": ["freight", "carriage", "transport", "logistics"],
            "packing_expense": ["packing"],
            "brokerage": ["brokerage", "commission"],
            "rent": ["rent", "shop rent", "office rent"],
            "consultancy": ["consultancy", "consulting"],
            "professional_fees": ["professional", "legal", "audit fees"],
            "salary": ["salary", "bonus", "director's salary"],
            "tds_deduction": ["tds payable"],
            "insurance": ["insurance"],
            "advertisement": ["advertisement"],
            "software": ["software", "domain"],
            "purchase": ["purchase"],
        }

EXPENSE_KEYWORDS = _build_expense_keywords()

EXPENSE_TO_SECTION = {
    "interest_payment": "194A",
    "freight_expense": "194C",
    "packing_expense": "194C",
    "brokerage": "194H",
    "rent": "194I(b)",
    "consultancy": "194J(b)",
    "professional_fees": "194J(b)",
    "insurance": "194D",
    "advertisement": "194C",  # default, may be 194J(b) — checker will validate
    "software": "194J(b)",
    "purchase": "194Q",
}


def classify_expense(text: str) -> str:
    """Classify expense type from column name or account head."""
    if not text:
        return "other"
    lower = text.lower()
    for exp_type, keywords in EXPENSE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return exp_type
    return "other"


# ═══════════════════════════════════════════════════════════
# Parser Agent
# ═══════════════════════════════════════════════════════════

class ParserAgent(AgentBase):
    agent_name = "Parser Agent"

    def run(self, form26_path: str, tally_path: str) -> dict:
        """Parse both files using column mapper output. Zero hardcoded positions.

        Returns: {tds_count, ledger_count, sections, column_mapping}
        """
        self.events.agent_start(self.agent_name, "Starting Parser Agent...")

        # Step 1: Column mapper identifies structure
        mapper = ColumnMapper(repo=self.db, llm=self.llm)

        f26_mapping = mapper.map_file(form26_path, company_id=self.company_id, file_type="tds")
        tally_mapping = mapper.map_file(tally_path, company_id=self.company_id, file_type="ledger")

        # Log mapping stats
        for sheet_result in f26_mapping.get("sheets", []):
            stats = sheet_result.get("stats", {})
            self.events.detail(self.agent_name,
                f"Form 26 columns: {stats.get('auto_mapped', 0)} auto + "
                f"{stats.get('llm_mapped', 0)} LLM + {stats.get('needs_review', 0)} review")

        for sheet_result in tally_mapping.get("sheets", []):
            stats = sheet_result.get("stats", {})
            self.events.detail(self.agent_name,
                f"{sheet_result['sheet_name']}: {stats.get('auto_mapped', 0)} auto + "
                f"{stats.get('llm_mapped', 0)} LLM + {stats.get('needs_review', 0)} review")

        # Step 2: Parse Form 26 using mapped columns
        tds_entries = self._parse_with_mapping(form26_path, f26_mapping, entry_type="tds")
        tds_count = self.db.entries.bulk_insert_tds(tds_entries) if tds_entries else 0
        sections = set(e["tds_section"] for e in tds_entries if e.get("tds_section"))
        self.events.detail(self.agent_name, f"Form 26: {tds_count} entries across {len(sections)} sections")

        # Step 3: Parse Tally using mapped columns
        ledger_entries = self._parse_with_mapping(tally_path, tally_mapping, entry_type="ledger")
        ledger_count = self.db.entries.bulk_insert_ledger(ledger_entries) if ledger_entries else 0
        self.events.detail(self.agent_name, f"Tally: {ledger_count} ledger entries")

        # Update run status
        self.db.runs.update_status(self.run_id, "processing")

        self.events.success(self.agent_name, f"Parsed {tds_count} TDS + {ledger_count} ledger entries")
        self.events.agent_done(self.agent_name, "Parsing complete")

        return {
            "tds_count": tds_count,
            "ledger_count": ledger_count,
            "sections": sorted(sections),
            "column_mapping": {"form26": f26_mapping, "tally": tally_mapping},
        }

    def _parse_with_mapping(self, filepath: str, mapping_result: dict, entry_type: str) -> list[dict]:
        """Parse a file using column mapper output. No hardcoded positions.

        Args:
            filepath: XLSX or CSV path
            mapping_result: output from ColumnMapper.map_file()
            entry_type: "tds" or "ledger"
        """
        all_entries = []

        for sheet_result in mapping_result.get("sheets", []):
            if sheet_result.get("from_cache"):
                # Saved mapping — still need to read the actual file
                pass

            # Build field → column_index lookup from mappings
            field_to_col = {}
            for m in sheet_result.get("mappings", []):
                if m.get("field") and m["field"] not in ("skip", "unknown"):
                    field_to_col[m["field"]] = m.get("col_index", 0) - 1  # 0-based

            if not field_to_col:
                continue

            # Read the actual file data
            sheet_name = sheet_result.get("sheet_name", "")
            header_row = sheet_result.get("header_row", 1)

            entries = self._read_rows_with_field_map(
                filepath, sheet_name, header_row, field_to_col, entry_type
            )
            all_entries.extend(entries)

        return all_entries

    def _read_rows_with_field_map(
        self, filepath: str, sheet_name: str, header_row: int,
        field_to_col: dict, entry_type: str,
    ) -> list[dict]:
        """Read rows from a sheet using the field→column mapping."""

        if filepath.lower().endswith(".csv"):
            return self._read_csv_rows(filepath, header_row, field_to_col, entry_type)

        wb = openpyxl.load_workbook(filepath, data_only=True)

        # Find the sheet
        if sheet_name and sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        elif sheet_name == "saved":
            # Saved mapping — use first sheet or find by headers
            ws = wb[wb.sheetnames[0]]
        else:
            ws = wb[wb.sheetnames[0]]

        entries = []
        for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
            # Extract values using the field map
            values = {}
            for field_name, col_idx in field_to_col.items():
                if col_idx < len(row):
                    values[field_name] = row[col_idx].value

            # Skip empty/total rows
            if not any(values.values()):
                continue
            first_val = str(list(values.values())[0] or "")
            if "total" in first_val.lower() or "grand" in first_val.lower():
                continue

            if entry_type == "tds":
                entry = self._build_tds_entry(values)
            else:
                entry = self._build_ledger_entry(values, ws, row, header_row, field_to_col)

            if entry:
                entries.append(entry)

        wb.close()
        return entries

    def _read_csv_rows(self, filepath, header_row, field_to_col, entry_type):
        """Read CSV rows using field map."""
        import csv
        entries = []
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i < header_row:
                    continue
                values = {}
                for field_name, col_idx in field_to_col.items():
                    if col_idx < len(row):
                        values[field_name] = row[col_idx]
                if not any(values.values()):
                    continue
                if entry_type == "tds":
                    entry = self._build_tds_entry(values)
                else:
                    entry = self._build_ledger_entry_simple(values)
                if entry:
                    entries.append(entry)
        return entries

    def _build_tds_entry(self, values: dict) -> dict | None:
        """Build a tds_entry dict from mapped field values."""
        party_raw = values.get("party_name", "")
        if not party_raw:
            return None

        parsed = clean_name(str(party_raw))
        pan = values.get("pan") or parsed["pan"]
        section = str(values.get("tds_section", "")).strip()
        if not section:
            return None

        return {
            "reconciliation_run_id": self.run_id,
            "company_id": self.company_id,
            "financial_year": self.financial_year,
            "party_name": parsed["name"],
            "pan": pan,
            "tds_section": section,
            "tds_amount": safe_float(values.get("tds_amount")),
            "gross_amount": safe_float(values.get("gross_amount")),
            "date_of_deduction": to_date_str(values.get("date_of_deduction")),
            "raw_data": {
                "vendor_id": parsed["id"],
                "tax_rate_pct": safe_float(values.get("tax_rate")),
                "certificate_number": values.get("certificate_number"),
            },
        }

    def _build_ledger_entry(self, values: dict, ws, row, header_row, field_to_col) -> dict | None:
        """Build a ledger_entry dict from mapped field values.

        For Tally multi-column registers (Journal, GST Exp), also collects
        unmapped columns as expense heads / account postings.
        """
        party = str(values.get("party_name", "")).strip()
        if not party:
            return None

        amount = safe_float(values.get("amount"))

        # Collect ALL non-mapped, non-zero columns as expense data
        # These are the expense heads in Tally's 2D registers
        mapped_cols = set(field_to_col.values())
        expense_heads = {}
        gst_amounts = {}

        # Read headers for this sheet
        headers = {}
        for cell in ws[header_row]:
            if cell.value:
                headers[cell.column - 1] = str(cell.value).strip()

        for col_idx, cell in enumerate(row):
            if col_idx in mapped_cols:
                continue  # already mapped to a field
            if cell.value is None or cell.value == 0:
                continue
            col_name = headers.get(col_idx, "")
            if not col_name:
                continue

            # Classify as GST or expense
            col_lower = col_name.lower()
            if any(kw in col_lower for kw in ["gst", "cgst", "sgst", "igst", "input c", "input s", "input i"]):
                gst_amounts[col_name] = safe_float(cell.value)
            elif col_name not in ("Date", "Particulars", "Voucher No.", "Value", "Gross Total",
                                   "Addl. Cost", "Rounded (+/-)", "Rounded"):
                expense_heads[col_name] = safe_float(cell.value)

        # Determine expense type from expense heads
        exp_type = "other"
        for head in expense_heads:
            classified = classify_expense(head)
            if classified != "other":
                exp_type = classified
                break

        tds_section = EXPENSE_TO_SECTION.get(exp_type)
        total_gst = sum(gst_amounts.values()) if gst_amounts else None

        return {
            "reconciliation_run_id": self.run_id,
            "company_id": self.company_id,
            "financial_year": self.financial_year,
            "party_name": party,
            "expense_type": exp_type,
            "amount": amount if amount else safe_float(sum(expense_heads.values())),
            "gst_amount": total_gst,
            "tds_section": tds_section,
            "invoice_number": str(values.get("invoice_number", "")).strip() or None,
            "invoice_date": to_date_str(values.get("invoice_date")),
            "raw_data": {
                "expense_heads": expense_heads if expense_heads else None,
                "gst_breakup": gst_amounts if gst_amounts else None,
            },
        }

    def _build_ledger_entry_simple(self, values: dict) -> dict | None:
        """Build a ledger_entry from simple (CSV) field values."""
        party = str(values.get("party_name", "")).strip()
        if not party:
            return None

        exp_type = classify_expense(values.get("expense_type", ""))

        return {
            "reconciliation_run_id": self.run_id,
            "company_id": self.company_id,
            "financial_year": self.financial_year,
            "party_name": party,
            "expense_type": exp_type,
            "amount": safe_float(values.get("amount")),
            "tds_section": EXPENSE_TO_SECTION.get(exp_type),
            "invoice_number": str(values.get("invoice_number", "")).strip() or None,
            "invoice_date": to_date_str(values.get("invoice_date")),
            "raw_data": None,
        }
