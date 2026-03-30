"""
Parser Agent — Parse Form 26 + Tally XLSX into database entries.

Reads XLSX files, extracts structured data, writes to:
- tds_entry table (Form 26 deductions)
- ledger_entry table (Tally expenses)

Preserves ALL parsing logic from MVP (tds-recon/agents/parser_agent.py).
Changes: writes to DB instead of JSON files, uses EventEmitter instead of global logger.
"""

import re
from datetime import datetime, date

import openpyxl

from app.agents.base import AgentBase


# ── Helpers ──

def clean_name(raw_name: str) -> dict:
    """Parse Form 26 name field: 'Adi Debnath (34); PAN: AAAAA0001A' → {name, id, pan}"""
    if not raw_name:
        return {"name": "", "id": "", "pan": ""}
    match = re.match(r"^(.+?)\s*\((\d+)\);\s*PAN:\s*(\S+)", raw_name)
    if match:
        return {"name": match.group(1).strip(), "id": match.group(2), "pan": match.group(3)}
    return {"name": raw_name.strip(), "id": "", "pan": ""}


def to_date_str(val) -> str | None:
    """Convert date/datetime to ISO string for DB storage."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, str):
        return val[:10]  # assume ISO format
    return str(val)[:10]


def safe_float(val) -> float:
    """Convert value to float, defaulting to 0."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ── Column classification (from MVP — dynamic detection) ──

GST_COLUMN_PATTERNS = {"input c gst", "input s gst", "input i gst", "c gst", "s gst", "i gst", "igst", "cgst", "sgst"}

META_COLUMNS_GST_EXP = {"Date", "Particulars", "Voucher No.", "Value", "Addl. Cost", "Gross Total", "Rounded (+/-)"}
JOURNAL_META_COLUMNS = {"Date", "Particulars", "Voucher No.", "Value", "Gross Total"}

LOAN_COLUMN_PATTERN = re.compile(r"^(.+?)\s*\(Loan\)$", re.IGNORECASE)


def _is_gst_column(col_name: str) -> bool:
    return col_name.lower().strip() in GST_COLUMN_PATTERNS or \
           "gst" in col_name.lower() and ("input" in col_name.lower() or
           col_name.strip() in {"C GST", "S GST", "I GST"})


def _is_expense_column(col_name: str) -> bool:
    return col_name not in META_COLUMNS_GST_EXP and not _is_gst_column(col_name)


def _classify_journal_entry(postings: dict) -> str:
    """Classify a journal entry by which account heads are posted."""
    keys = set(postings.keys())
    if "Interest Paid" in keys:
        return "interest_payment"
    if "TDS Payable" in keys and len(keys) == 1:
        return "tds_deduction"
    if "Freight Charges" in keys:
        return "freight_expense"
    if "Packing Charges" in keys:
        return "packing_expense"
    if "Salary & Bonus" in keys or "Director's Salary" in keys:
        return "salary"
    if "Brokerage and Commission" in keys:
        return "brokerage"
    if "Shop Rent" in keys:
        return "rent"
    if "Consultancy Charges" in keys:
        return "consultancy"
    if "Professonal Charges" in keys:
        return "professional_fees"
    if "Audit Fees" in keys or "Outstanding Audit Fees" in keys:
        return "audit_fees"
    if "TDS Payable" in keys:
        return "tds_deduction"
    if any(re.match(r"^[A-Z][a-z]+(?: [A-Z][a-z]+){1,3}$", k) for k in keys):
        return "salary"
    if "Cash Discount" in keys or "Discount (CD)" in keys:
        return "discount"
    return "other"


# ── Map expense type to TDS section ──

EXPENSE_TO_SECTION = {
    "interest_payment": "194A",
    "freight_expense": "194C",
    "packing_expense": "194C",
    "brokerage": "194H",
    "rent": "194I(b)",
    "consultancy": "194J(b)",
    "professional_fees": "194J(b)",
    "audit_fees": "194J(b)",
}


# ═══════════════════════════════════════════════════════════
# Parser Agent
# ═══════════════════════════════════════════════════════════

class ParserAgent(AgentBase):
    agent_name = "Parser Agent"

    def run(self, form26_path: str, tally_path: str) -> dict:
        """Parse both files and write entries to database.

        Uses column mapper (with LLM) to identify columns if format is unknown.
        Returns summary: {tds_count, ledger_count, sections, column_mapping}
        """
        self.events.agent_start(self.agent_name, "Starting Parser Agent...")

        # Run column mapper to understand file structure
        from app.services.column_mapper import ColumnMapper
        mapper = ColumnMapper(repo=self.db, llm=self.llm)

        # Map Form 26 columns
        f26_mapping = mapper.map_file(form26_path, company_id=self.company_id, file_type="tds")
        if f26_mapping["sheets"]:
            stats = f26_mapping["sheets"][0].get("stats", {})
            self.events.detail(self.agent_name,
                f"Form 26 columns: {stats.get('auto_mapped', 0)} auto-mapped, "
                f"{stats.get('llm_mapped', 0)} LLM-mapped, "
                f"{stats.get('needs_review', 0)} need review")

        # Map Tally columns
        tally_mapping = mapper.map_file(tally_path, company_id=self.company_id, file_type="ledger")
        if tally_mapping["sheets"]:
            for sheet in tally_mapping["sheets"]:
                stats = sheet.get("stats", {})
                self.events.detail(self.agent_name,
                    f"{sheet['sheet_name']}: {stats.get('auto_mapped', 0)} auto, "
                    f"{stats.get('llm_mapped', 0)} LLM, {stats.get('needs_review', 0)} review")

        # Parse Form 26
        tds_entries = self._parse_form26(form26_path)
        tds_count = self.db.entries.bulk_insert_tds(tds_entries)
        sections = set(e["tds_section"] for e in tds_entries)
        self.events.detail(self.agent_name, f"Form 26: {tds_count} entries across {len(sections)} sections")
        self.events.detail(self.agent_name, f"Sections: {', '.join(sorted(sections))}")

        # Parse Tally
        ledger_entries = self._parse_tally(tally_path)
        ledger_count = self.db.entries.bulk_insert_ledger(ledger_entries)
        self.events.detail(self.agent_name, f"Tally: {ledger_count} ledger entries")

        # Update run progress
        self.db.runs.update_status(self.run_id, "processing")

        self.events.success(self.agent_name, f"Parsed {tds_count} TDS + {ledger_count} ledger entries")
        self.events.agent_done(self.agent_name, "Parsing complete")

        return {
            "tds_count": tds_count,
            "ledger_count": ledger_count,
            "sections": sorted(sections),
            "column_mapping": {
                "form26": f26_mapping,
                "tally": tally_mapping,
            },
        }

    def _parse_form26(self, filepath: str) -> list[dict]:
        """Parse Form 26 XLSX → list of dicts ready for tds_entry table."""
        wb = openpyxl.load_workbook(filepath, data_only=True)

        # Find the sheet (try common names)
        sheet_names = wb.sheetnames
        ws = None
        for name in ["Deduction Details", "Sheet1", sheet_names[0]]:
            if name in sheet_names:
                ws = wb[name]
                break
        if ws is None:
            ws = wb[sheet_names[0]]

        # Find header row (scan first 15 rows for "Name" or "Section")
        header_row = 4  # default
        for row_num in range(1, 16):
            for col in range(1, 15):
                val = ws.cell(row_num, col).value
                if val and "section" in str(val).lower():
                    header_row = row_num
                    break

        entries = []
        for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
            raw_name = row[1].value
            section = row[2].value

            if not raw_name or not section:
                continue
            if "Total" in str(raw_name) or "Grand" in str(raw_name):
                continue

            parsed = clean_name(str(raw_name))
            entry = {
                "reconciliation_run_id": self.run_id,
                "company_id": self.company_id,
                "financial_year": self.financial_year,
                "party_name": parsed["name"],
                "pan": parsed["pan"],
                "tds_section": str(section).strip(),
                "tds_amount": safe_float(row[9].value) if len(row) > 9 else 0,  # Tax Deducted
                "gross_amount": safe_float(row[3].value),  # Amount Paid
                "date_of_deduction": to_date_str(row[4].value),  # Date
                "raw_data": {
                    "vendor_id": parsed["id"],
                    "income_tax": safe_float(row[5].value) if len(row) > 5 else 0,
                    "surcharge": safe_float(row[6].value) if len(row) > 6 else 0,
                    "cess": safe_float(row[7].value) if len(row) > 7 else 0,
                    "tax_rate_pct": safe_float(row[8].value) if len(row) > 8 else 0,
                    "tax_deducted_date": to_date_str(row[10].value) if len(row) > 10 else None,
                    "non_deduction_reason": str(row[11].value or "") if len(row) > 11 else "",
                },
            }
            entries.append(entry)

        wb.close()
        return entries

    def _parse_tally(self, filepath: str) -> list[dict]:
        """Parse Tally XLSX → list of dicts ready for ledger_entry table."""
        wb = openpyxl.load_workbook(filepath, data_only=True)
        all_entries = []

        # Parse each sheet type
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            name_lower = sheet_name.lower()

            if "journal" in name_lower:
                entries = self._parse_journal_register(ws)
                self.events.detail(self.agent_name, f"Journal Register: {len(entries)} entries")
            elif "gst" in name_lower and ("exp" in name_lower or "purchase" in name_lower):
                entries = self._parse_gst_exp_register(ws)
                self.events.detail(self.agent_name, f"GST Exp Register: {len(entries)} entries")
            elif "purchase" in name_lower:
                entries = self._parse_purchase_register(ws)
                self.events.detail(self.agent_name, f"Purchase Register: {len(entries)} entries")
            else:
                continue

            all_entries.extend(entries)

        wb.close()
        return all_entries

    def _parse_journal_register(self, ws) -> list[dict]:
        """Parse Journal Register → ledger entries."""
        headers = {}
        # Find header row
        header_row = 7
        for row_num in range(1, 15):
            val = ws.cell(row_num, 1).value
            if val and str(val).strip() == "Date":
                header_row = row_num
                break

        for cell in ws[header_row]:
            if cell.value:
                headers[cell.column_letter] = str(cell.value).strip()

        entries = []
        for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
            date_val = row[0].value
            particulars = row[1].value
            voucher_no = row[2].value
            gross_total = row[4].value if len(row) > 4 else None

            if particulars and "Grand Total" in str(particulars):
                continue
            if gross_total is None and date_val is None:
                continue

            account_postings = {}
            for cell in row:
                col_letter = cell.column_letter
                if col_letter in headers and cell.value is not None and cell.value != 0:
                    col_name = headers[col_letter]
                    if col_name in JOURNAL_META_COLUMNS:
                        continue
                    account_postings[col_name] = cell.value

            if not account_postings:
                continue

            entry_type = _classify_journal_entry(account_postings)

            # Extract loan party for interest entries
            loan_party = None
            if "Interest Paid" in account_postings:
                for col_name in account_postings:
                    m = LOAN_COLUMN_PATTERN.match(col_name)
                    if m:
                        loan_party = m.group(1).strip()
                        break

            # Determine TDS section from entry type
            tds_section = EXPENSE_TO_SECTION.get(entry_type)

            entry = {
                "reconciliation_run_id": self.run_id,
                "company_id": self.company_id,
                "financial_year": self.financial_year,
                "party_name": loan_party or str(particulars or "").strip(),
                "expense_type": entry_type,
                "amount": safe_float(gross_total),
                "tds_section": tds_section,
                "invoice_number": str(voucher_no or "").strip(),
                "invoice_date": to_date_str(date_val),
                "raw_data": {
                    "source": "journal_register",
                    "account_postings": {k: float(v) if isinstance(v, (int, float)) else str(v)
                                         for k, v in account_postings.items()},
                    "loan_party": loan_party,
                },
            }
            entries.append(entry)

        return entries

    def _parse_gst_exp_register(self, ws) -> list[dict]:
        """Parse Purchase GST Exp Register → ledger entries."""
        headers = {}
        header_row = 7
        for row_num in range(1, 15):
            val = ws.cell(row_num, 1).value
            if val and str(val).strip() == "Date":
                header_row = row_num
                break

        for cell in ws[header_row]:
            if cell.value:
                headers[cell.column_letter] = str(cell.value).strip()

        entries = []
        for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
            date_val = row[0].value
            particulars = row[1].value
            voucher_no = row[2].value

            if particulars and "Grand Total" in str(particulars):
                continue
            if date_val is None and particulars is None:
                continue

            gross_total = None
            expense_heads = {}
            gst_amounts = {}

            for cell in row:
                col_letter = cell.column_letter
                if col_letter not in headers or cell.value is None or cell.value == 0:
                    continue
                col_name = headers[col_letter]

                if col_name == "Gross Total":
                    gross_total = cell.value
                elif _is_gst_column(col_name):
                    gst_amounts[col_name] = cell.value
                elif _is_expense_column(col_name):
                    expense_heads[col_name] = cell.value

            if not expense_heads and not gst_amounts:
                continue

            base_amount = sum(expense_heads.values())
            total_gst = sum(gst_amounts.values())

            entry = {
                "reconciliation_run_id": self.run_id,
                "company_id": self.company_id,
                "financial_year": self.financial_year,
                "party_name": str(particulars or "").strip(),
                "expense_type": "; ".join(sorted(expense_heads.keys())),
                "amount": safe_float(base_amount),
                "gst_amount": safe_float(total_gst),
                "invoice_number": str(voucher_no or "").strip(),
                "invoice_date": to_date_str(date_val),
                "raw_data": {
                    "source": "gst_exp_register",
                    "gross_total": safe_float(gross_total) if gross_total else None,
                    "expense_heads": {k: float(v) for k, v in expense_heads.items()},
                    "gst_breakup": {k: float(v) for k, v in gst_amounts.items()},
                },
            }
            entries.append(entry)

        return entries

    def _parse_purchase_register(self, ws) -> list[dict]:
        """Parse Purchase Register → ledger entries."""
        headers = {}
        header_row = 7
        for row_num in range(1, 15):
            val = ws.cell(row_num, 1).value
            if val and str(val).strip() == "Date":
                header_row = row_num
                break

        for cell in ws[header_row]:
            if cell.value:
                headers[cell.column_letter] = str(cell.value).strip()

        entries = []
        for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
            date_val = row[0].value
            particulars = row[1].value
            voucher_no = row[2].value

            if particulars and "Grand Total" in str(particulars):
                continue
            if date_val is None and particulars is None:
                continue

            amounts = {}
            for cell in row:
                col_letter = cell.column_letter
                if col_letter not in headers or cell.value is None:
                    continue
                col_name = headers[col_letter]
                if col_name not in ("Date", "Particulars", "Voucher No."):
                    amounts[col_name] = cell.value

            if not amounts:
                continue

            gross_total = amounts.get("Gross Total", 0)
            total_gst = safe_float(amounts.get("Input C GST", 0)) + \
                        safe_float(amounts.get("Input S GST", 0)) + \
                        safe_float(amounts.get("Input I GST", 0))

            entry = {
                "reconciliation_run_id": self.run_id,
                "company_id": self.company_id,
                "financial_year": self.financial_year,
                "party_name": str(particulars or "").strip(),
                "expense_type": "purchase",
                "amount": safe_float(gross_total),
                "gst_amount": safe_float(total_gst),
                "invoice_number": str(voucher_no or "").strip(),
                "invoice_date": to_date_str(date_val),
                "raw_data": {
                    "source": "purchase_register",
                    "amounts": {k: float(v) if isinstance(v, (int, float)) else str(v)
                                for k, v in amounts.items()},
                },
            }
            entries.append(entry)

        return entries
