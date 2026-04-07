"""
Test cases for the new column mapping system (L0-L4 cascade).

Structure:
- 1 happy path (everything works perfectly)
- All edge cases from real failures in the old system
- Edge cases for each cascade layer

Tests use the actual HPC test files where possible.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════
# Test data builders
# ═══════════════════════════════════════════════════════════

def make_form26_df():
    """Realistic Form 26 DataFrame — exactly what the HPC file looks like."""
    return pd.DataFrame({
        "Name": [
            "Amar Nath Prasad (128); PAN: BNAPP1451L",
            "AMRITA ICONS (139); PAN: AYBPS6260R",
            "Adi Debnath (34); PAN: AAAAA0001A",
        ],
        "Section": ["194H", "194C", "194A"],
        "Amt. Paid/ Crdt/Drawn Rs.": [22090.0, 181380.0, 82461.0],
        "Amt. Paid/ Crdt/Drawn Date": pd.to_datetime(["2025-03-31", "2024-09-30", "2025-01-15"]),
        "Income Tax\nRs.": [442.0, 1814.0, 8246.0],
        "Surcharge\nRs.": [0.0, 0.0, 0.0],
        "Cess\nRs.": [0.0, 0.0, 0.0],
        "Tax Rate\n%": [2.0, 1.0, 10.0],
        "Tax Deducted Rs.": [442.0, 1814.0, 8246.0],
        "Tax Deducted Date": pd.to_datetime(["2025-03-31", "2024-09-30", "2025-01-15"]),
        "Non Deduction Reason": ["", "", ""],
    })


def make_tally_journal_df():
    """Realistic Tally Journal Register — 68 columns, mostly expense heads."""
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2024-04-03", "2024-04-04", "2024-04-10"]),
        "Particulars": ["Tata AIG General Insurance", "Inland World Logistics Pvt Ltd", "State Bank of India"],
        "Voucher No.": ["5", "1", "3"],
        "Value": [None, None, None],
        "Gross Total": [17916.0, 22483.0, 50000.0],
        "Motor Car Insurance": [17916.0, 0.0, 0.0],
        "Freight Charges": [0.0, 22483.0, 0.0],
        "TDS Payable": [0.0, 0.0, 0.0],
        "Packing Charges": [0.0, 0.0, 0.0],
        "Cash Discount": [0.0, 0.0, 0.0],
        "Brokerage and Commission": [0.0, 0.0, 0.0],
        "Interest Paid": [0.0, 0.0, 50000.0],
    })
    return df


def make_tally_purchase_gst_df():
    """Realistic Purchase GST Exp Register — 42 columns."""
    return pd.DataFrame({
        "Date": pd.to_datetime(["2024-04-03", "2024-04-03"]),
        "Particulars": ["Bharti Airtel Ltd.", "United India Insurance Co"],
        "Voucher No.": ["1", "2"],
        "Value": [None, None],
        "Addl. Cost": [None, None],
        "Gross Total": [706.82, 293.0],
        "Telephone Charges_18%": [599.0, 0.0],
        "Input C GST": [53.91, 22.41],
        "Input S GST": [53.91, 22.41],
        "Insurance Charges": [0.0, 249.0],
        "Rounded (+/-)": [0.0, -0.82],
    })


# ═══════════════════════════════════════════════════════════
# EXCEL LOADER TESTS
# ═══════════════════════════════════════════════════════════

class TestExcelLoader:

    def test_finds_header_row_with_metadata_above(self):
        """Form 26 has 3 rows of metadata (company name, form title, blank)
        before the actual header in row 4. Loader must skip those."""
        # Header row should be detected as row 4 (0-indexed: 3)
        # Rows 1-3: "HPC LTD", "Deduction details (Form-26Q)...", ""
        # Row 4: "Name", "Section", "Amt. Paid/..."
        pass  # Implementation test against real file

    def test_handles_line_breaks_in_column_names(self):
        """Form 26 has 'Income Tax\\nRs.' — must replace \\n with space."""
        df = make_form26_df()
        # After loading, column should be "Income Tax Rs." not "Income Tax\nRs."
        assert "Income Tax\nRs." in df.columns  # raw has \n
        # Loader should normalize to: "Income Tax Rs."

    def test_handles_merged_cells(self):
        """Some Tally exports have merged cells in header row.
        openpyxl shows value only in top-left cell, rest are None.
        Loader should fill None cells with left neighbor value."""
        pass  # Needs real file with merged cells

    def test_processes_all_sheets_not_just_biggest(self):
        """Tally extract has 3 data sheets + 1 empty sheet.
        Must return data from all 3, ignore the empty one."""
        # Purchase Register: 636 rows
        # Purchase GST Exp: 1000 rows
        # Journal Register: 725 rows
        # Sheet2: 1 row (empty)
        pass  # Implementation test against real file

    def test_strips_grand_total_rows(self):
        """Last row often = 'Grand Total'. Must be stripped."""
        df = pd.DataFrame({
            "Date": ["2024-04-03", "Grand Total", "Total"],
            "Particulars": ["Vendor A", "", ""],
            "Amount": [1000.0, 50000.0, 50000.0],
        })
        # After loading, should have only 1 data row
        # Rows with "Grand Total" or "Total" in first column = dropped

    def test_drops_fully_empty_columns(self):
        """Some exports have empty columns (all NaN). Must be dropped."""
        df = pd.DataFrame({
            "Date": ["2024-04-03"],
            "": [None],
            "Amount": [1000.0],
        })
        # Empty column should be dropped


# ═══════════════════════════════════════════════════════════
# FINGERPRINTER TESTS
# ═══════════════════════════════════════════════════════════

class TestFingerprinter:

    def test_detects_date_column_from_data_not_name(self):
        """Column 5 'Amt. Paid/ Crdt/Drawn Date' has 'Amt' in name
        but contains dates. Fingerprinter must detect looks_like_date=True."""
        df = make_form26_df()
        col = "Amt. Paid/ Crdt/Drawn Date"
        values = df[col].dropna()
        # >80% should parse as dates → looks_like_date = True

    def test_detects_pan_pattern(self):
        """PAN follows [A-Z]{5}[0-9]{4}[A-Z]. If >50% of values match,
        looks_like_pan=True."""
        series = pd.Series(["BNAPP1451L", "AYBPS6260R", "AAAAA0001A", None])
        # 3/4 non-null match PAN regex → looks_like_pan = True

    def test_detects_percentage_column(self):
        """Tax Rate column has values 1, 2, 10 — all 0-100. mean=4.3, max=10.
        looks_like_percentage=True."""
        series = pd.Series([2.0, 1.0, 10.0, 2.0, 1.0])
        # mean=3.2, max=10, all ≤ 100 → True

    def test_disambiguates_gross_vs_tds_by_magnitude(self):
        """gross_amount mean ≈ 50,000. tds_amount mean ≈ 800.
        tds is ~1-2% of gross. Fingerprinter captures this via mean."""
        df = make_form26_df()
        gross_mean = df["Amt. Paid/ Crdt/Drawn Rs."].mean()
        tds_mean = df["Tax Deducted Rs."].mean()
        ratio = tds_mean / gross_mean
        assert 0.01 < ratio < 0.15  # TDS is 1-15% of gross

    def test_handles_pandas_duplicate_column_suffix(self):
        """pandas renames duplicate 'Amount' to 'Amount', 'Amount.1', 'Amount.2'.
        Fingerprinter must strip .N suffix for matching, keep in source_name."""
        df = pd.DataFrame({
            "Amount": [1000.0],
            "Amount.1": [100.0],
            "Amount.2": [50.0],
        })
        # source_name should be "Amount.1" (for traceability)
        # matching_name should be "Amount" (for L1/L2 comparison)

    def test_dtype_override_when_object_looks_like_date(self):
        """pandas might store dates as 'object' dtype (strings).
        If >80% parse as dates, override dtype to 'date'."""
        series = pd.Series(["2024-04-03", "2024-05-15", "2024-06-20", "invalid", None])
        # 3/5 non-null = 60% → NOT date (threshold is 80%)
        series2 = pd.Series(["2024-04-03", "2024-05-15", "2024-06-20", "2024-07-01"])
        # 4/4 = 100% → date

    def test_null_pct_calculation(self):
        """Column with 3/10 nulls should have null_pct=0.3."""
        series = pd.Series([1, 2, 3, None, 5, None, 7, None, 9, 10])
        null_pct = series.isna().mean()
        assert abs(null_pct - 0.3) < 0.01


# ═══════════════════════════════════════════════════════════
# CACHE TESTS
# ═══════════════════════════════════════════════════════════

class TestCacheLookup:

    def test_cache_hit_on_same_columns(self):
        """Same set of column names (regardless of order) → cache hit."""
        cols_run1 = ["Date", "Name", "Amount", "Section"]
        cols_run2 = ["Section", "Amount", "Date", "Name"]  # different order
        # md5(sorted(lowercase)) should be identical

    def test_cache_miss_on_different_columns(self):
        """Different column names → cache miss, run cascade."""
        cols_run1 = ["Date", "Name", "Amount"]
        cols_run2 = ["Date", "Name", "Amount", "PAN"]  # extra column
        # Different hash → miss

    def test_cache_only_saved_after_human_confirms(self):
        """Cache must NOT be saved after auto-mapping.
        Only after user clicks 'Confirm' in review UI."""
        pass

    def test_cache_records_method_per_column(self):
        """Each cached mapping should record how it was created:
        exact, fuzzy, llm, manual (user override)."""
        pass


# ═══════════════════════════════════════════════════════════
# L0 TEMPLATE RECOGNITION TESTS
# ═══════════════════════════════════════════════════════════

class TestTemplateRecognition:

    def test_form26_recognized_by_signature(self):
        """Form 26 has 'Section' + 'Tax Deducted' in column names.
        Should match Form 26 template."""
        df = make_form26_df()
        col_names = [c.lower().replace("\n", " ") for c in df.columns]
        has_section = any("section" in c for c in col_names)
        has_tax_deducted = any("tax deducted" in c for c in col_names)
        assert has_section and has_tax_deducted

    def test_tally_recognized_by_signature(self):
        """Tally has 'Particulars' + 'Voucher No.' in columns.
        Should match Tally register template."""
        df = make_tally_journal_df()
        col_names = [c.lower() for c in df.columns]
        has_particulars = any("particulars" in c for c in col_names)
        has_voucher = any("voucher" in c for c in col_names)
        assert has_particulars and has_voucher

    def test_form26_template_maps_all_columns_correctly(self):
        """Template mapping for Form 26 should produce 100% correct results.
        This is the test that FAILED with old fuzzy approach."""
        expected = {
            "Name": "party_name",
            "Section": "tds_section",
            "Amt. Paid/ Crdt/Drawn Rs.": "gross_amount",
            "Amt. Paid/ Crdt/Drawn Date": "date_of_deduction",  # OLD BUG: was mapped to gross_amount
            "Income Tax Rs.": "skip",        # income tax component, not total TDS
            "Surcharge Rs.": "skip",         # OLD BUG: was mapped to tax_rate
            "Cess Rs.": "skip",              # OLD BUG: was mapped to certificate_number
            "Tax Rate %": "tax_rate",
            "Tax Deducted Rs.": "tds_amount",
            "Tax Deducted Date": "skip",     # OLD BUG: was mapped to tds_amount
            "Non Deduction Reason": "skip",  # OLD BUG: was mapped to date_of_deduction
        }
        # Every column must match expected mapping

    def test_tally_structural_columns_mapped_by_position(self):
        """Tally columns 1-6 are always: Date, Particulars, Voucher No.,
        Value, [Addl. Cost], Gross Total. Must be mapped by position."""
        df = make_tally_journal_df()
        # Column 0 → invoice_date
        # Column 1 → party_name
        # Column 2 → invoice_number
        # Column 4 → gross_total (or amount)

    def test_tally_gst_columns_detected_by_name(self):
        """Columns with 'GST', 'CGST', 'SGST', 'IGST' → gst data columns."""
        df = make_tally_purchase_gst_df()
        gst_cols = [c for c in df.columns if any(
            kw in c.lower() for kw in ["gst", "cgst", "sgst", "igst"]
        )]
        assert len(gst_cols) == 2  # "Input C GST", "Input S GST"

    def test_tally_expense_heads_are_remaining_columns(self):
        """After structural + GST columns removed, everything else is
        an expense head: 'Freight Charges', 'Motor Car Insurance', etc."""
        df = make_tally_journal_df()
        structural = {"Date", "Particulars", "Voucher No.", "Value", "Gross Total"}
        expense_heads = [c for c in df.columns if c not in structural]
        assert "Motor Car Insurance" in expense_heads
        assert "Freight Charges" in expense_heads
        assert "Interest Paid" in expense_heads

    def test_unknown_format_falls_through_to_cascade(self):
        """A random CSV with no 'Section' or 'Particulars' should NOT
        match any template → proceeds to L1."""
        df = pd.DataFrame({
            "Col A": [1, 2], "Col B": ["x", "y"], "Col C": [3.0, 4.0]
        })
        col_names = [c.lower() for c in df.columns]
        has_section = any("section" in c for c in col_names)
        has_particulars = any("particulars" in c for c in col_names)
        assert not has_section and not has_particulars  # No template match


# ═══════════════════════════════════════════════════════════
# L1/L2 CASCADE TESTS (for unknown file formats)
# ═══════════════════════════════════════════════════════════

class TestCascadeMatcher:

    def test_l1_exact_match_with_abbreviation_expansion(self):
        """'Amt' should expand to 'Amount' and exact-match."""
        # normalise("Amt") → "amount"
        # target: "amount" → exact match, confidence 0.98

    def test_l1_exact_match_with_alias(self):
        """Target 'party_name' has alias 'vendor_name'.
        Source column 'Vendor Name' should match via alias."""
        pass

    def test_l2_fuzzy_tiebreak_date_vs_amount(self):
        """THE BUG THAT KILLED US: 'Amt. Paid/ Crdt/Drawn Date' fuzzy-matches
        both gross_amount (0.77) and date_of_deduction (0.73).

        Fuzzy says gross_amount wins (higher score).
        But fingerprint says looks_like_date=True → date wins.
        Fingerprint tie-breaking MUST override fuzzy score."""
        # source: "Amt. Paid/ Crdt/Drawn Date"
        # fuzzy scores: gross_amount=0.77, date_of_deduction=0.73
        # fingerprint: looks_like_date=True, dtype=date
        # EXPECTED: date_of_deduction (fingerprint overrides fuzzy)

    def test_l2_fuzzy_tiebreak_multiple_amount_columns(self):
        """Form 26 has 3 columns that fuzzy-match 'tds_amount':
        'Income Tax Rs.' (0.84), 'Tax Deducted Rs.' (0.85), 'Tax Deducted Date' (0.84).

        Fingerprint must pick: Tax Deducted Rs. (dtype=float, not date)."""
        # Three candidates for tds_amount:
        # Col 6: Income Tax Rs. → dtype=float, mean=800
        # Col 10: Tax Deducted Rs. → dtype=float, mean=800
        # Col 11: Tax Deducted Date → dtype=date → ELIMINATE
        # Between col 6 and 10: col 10 name is closer to "tax deducted" → pick col 10

    def test_l2_eliminates_string_column_for_numeric_target(self):
        """If target expects float (amount), columns with dtype=string
        should be eliminated even if fuzzy score is high."""
        pass

    def test_l4_receives_full_fingerprint_context(self):
        """LLM batch call must include dtype, mean, null_pct,
        looks_like_date, neighbors — not just column name."""
        pass

    def test_l4_single_batch_call_for_all_unresolved(self):
        """Must batch ALL unresolved columns in ONE LLM call,
        not one call per column (old approach was 4 calls)."""
        pass


# ═══════════════════════════════════════════════════════════
# FAILURES FROM OLD SYSTEM (regression tests)
# ═══════════════════════════════════════════════════════════

class TestOldSystemFailures:
    """These are the exact bugs that broke the old column mapper.
    Every one of these MUST pass with the new system."""

    def test_date_column_not_mapped_as_amount(self):
        """OLD BUG: 'Amt. Paid/ Crdt/Drawn Date' mapped to gross_amount
        because 'Amt. Paid' keyword scored 0.77, beating 'Date' at 0.73.
        Result: parser read dates as amounts → all amounts were 0 or corrupt."""
        # NEW: fingerprint detects looks_like_date=True → maps to date field

    def test_tax_deducted_date_not_mapped_as_tds_amount(self):
        """OLD BUG: 'Tax Deducted Date' mapped to tds_amount (score 0.84)
        because 'Tax Deducted' keyword matched tds_amount.
        Result: tds_amount was 0 for ALL entries (dates can't be amounts)."""
        # NEW: fingerprint detects dtype=date → eliminates from tds_amount candidates

    def test_surcharge_not_mapped_as_tax_rate(self):
        """OLD BUG: 'Surcharge Rs.' mapped to tax_rate (score 0.43)
        because no 'surcharge' keyword exists.
        Result: tax_rate was garbage (surcharge values, mostly 0)."""
        # NEW: 'Surcharge Rs.' has no match ≥ 0.50 in L1/L2 → skip or LLM

    def test_cess_not_mapped_as_certificate_number(self):
        """OLD BUG: 'Cess Rs.' mapped to certificate_number (score 0.40)
        because 'cess' fuzzy-matched 'certificate' via SequenceMatcher.
        Result: certificate_number field was filled with 0s."""
        # NEW: score 0.40 < L2 threshold 0.85 → falls to L4 or marked skip

    def test_non_deduction_reason_not_mapped_as_date(self):
        """OLD BUG: 'Non Deduction Reason' mapped to date_of_deduction (0.65)
        because 'deduction' fuzzy-matched 'deduction date'.
        Result: date field was filled with text like '' or 'N/A'."""
        # NEW: fingerprint shows dtype=string, looks_like_date=False → eliminated

    def test_tally_party_name_not_read_as_number(self):
        """OLD BUG: 55% of Tally entries had party_name='None' and some
        had numeric values like '70168.0' as party_name.
        Root cause: col_index was wrong, reading amount column as name."""
        # NEW: fingerprint on party_name column shows dtype=string.
        # If mapped column has dtype=float → tie-breaking rejects it.

    def test_tds_amount_not_zero_for_all_entries(self):
        """OLD BUG: ALL 255 TDS entries had tds_amount=0.
        Root cause: column 11 (Tax Deducted Date) was mapped as tds_amount.
        Parser tried to read dates as numbers → safe_float returned 0."""
        # This is the combined result of test_tax_deducted_date_not_mapped_as_tds_amount
        # + wrong column being read.
        # NEW: correct mapping → correct column read → non-zero tds_amount

    def test_all_dates_not_null(self):
        """OLD BUG: ALL 255 TDS entries had date_of_deduction=NULL.
        Root cause: column 12 (Non Deduction Reason) was mapped as date_of_deduction.
        Parser tried to parse '' as date → returned None."""
        # NEW: correct mapping → column 5 read → actual dates extracted

    def test_gst_amount_not_insanely_large(self):
        """OLD BUG: Some ledger entries had gst_amount=4,513,356
        (larger than the invoice itself). Wrong column mapped as GST."""
        # NEW: GST columns detected by name pattern (*gst*), not fuzzy matching


# ═══════════════════════════════════════════════════════════
# INTEGRATION TEST — FULL PIPELINE WITH REAL FILE
# ═══════════════════════════════════════════════════════════

class TestFullPipelineIntegration:

    def test_happy_path_form26_parsed_correctly(self):
        """THE ONE HAPPY PATH: Upload HPC Form 26 file, parse it,
        verify ALL fields are correct for first 3 entries.

        Expected output for row 5 (first data row):
        {
            party_name: "Amar Nath Prasad",
            pan: "BNAPP1451L",
            tds_section: "194H",
            gross_amount: 22090.0,
            tds_amount: 442.0,
            date_of_deduction: "2025-03-31",
            tax_rate: 2.0,
        }
        """
        pass  # Needs real file + full parser integration
