"""
Column Fingerprinter — builds a rich profile per column.

Looks at the DATA inside each column, not just the header name.
This is what lets us disambiguate "Amt. Paid/ Crdt/Drawn Date"
(looks like amount by name, but contains dates by data).

Hard fingerprints (PAN, TAN, Section) are bulletproof identifiers —
if 80% of values match the pattern, the column IS that field regardless
of what the header says.

Cross-column relationship detection finds mathematical relationships
between numeric columns (gross - tds = net) to disambiguate amounts.

Usage:
    from app.ingestion.fingerprinter import fingerprint_columns, detect_cross_column_relationships
    fingerprints = fingerprint_columns(df)
    relationships = detect_cross_column_relationships(df, fingerprints)
"""

import re

import pandas as pd
import numpy as np


# ═══ Hard Fingerprint Patterns ═══
# These are bulletproof — if values match, the column IS this field.

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
TAN_REGEX = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
SECTION_REGEX = re.compile(r"^(19[2-9][A-Z]?|20[0-9][A-Z]?|194[A-Z](\([a-z]\))?|206[A-Z]?)$")
BSR_REGEX = re.compile(r"^\d{7}$")
CHALLAN_REGEX = re.compile(r"^\d{5,6}$")
FY_REGEX = re.compile(r"^\d{4}-\d{2}$")  # 2024-25
QUARTER_REGEX = re.compile(r"^Q[1-4]$", re.IGNORECASE)

# Max rows to scan for pattern detection (cap for performance)
MAX_SCAN_ROWS = 500


def fingerprint_columns(df: pd.DataFrame) -> list[dict]:
    """Build fingerprint for every column in the DataFrame."""
    columns = list(df.columns)
    fingerprints = []

    for idx, col_name in enumerate(columns):
        series = df[col_name]
        scan_series = series.head(MAX_SCAN_ROWS)
        non_null = scan_series.dropna()

        fp = {
            # Identity
            "source_name": col_name,
            "col_index": idx,
            "matching_name": _strip_pandas_suffix(col_name),

            # Neighbor context
            "left_neighbor": columns[idx - 1] if idx > 0 else None,
            "right_neighbor": columns[idx + 1] if idx < len(columns) - 1 else None,

            # Data type
            "dtype_inferred": _infer_dtype(scan_series, non_null),

            # Samples
            "sample_values": _get_samples(non_null, 3),

            # Completeness
            "null_pct": round(scan_series.isna().mean(), 2) if len(scan_series) > 0 else 1.0,

            # Numeric stats
            "mean": None,
            "min": None,
            "max": None,

            # Pattern flags — soft (heuristic)
            "looks_like_date": False,
            "looks_like_percentage": False,

            # Hard fingerprints — bulletproof identifiers
            "looks_like_pan": False,
            "looks_like_tan": False,
            "looks_like_section": False,
            "looks_like_bsr": False,
            "looks_like_fy": False,
            "looks_like_quarter": False,

            # Hard fingerprint: if set, this overrides all other matching
            "hard_match": None,  # e.g., "pan", "tds_section", "date_of_deduction"
        }

        # Numeric stats
        if fp["dtype_inferred"] == "float" and len(non_null) > 0:
            numeric_vals = pd.to_numeric(non_null, errors="coerce").dropna()
            if len(numeric_vals) > 0:
                fp["mean"] = round(float(numeric_vals.mean()), 2)
                fp["min"] = round(float(numeric_vals.min()), 2)
                fp["max"] = round(float(numeric_vals.max()), 2)

        # Pattern detection
        if len(non_null) > 0:
            fp["looks_like_date"] = _check_date_pattern(non_null)
            fp["looks_like_percentage"] = _check_percentage_pattern(fp)

            # Hard fingerprints — these override header matching
            fp["looks_like_pan"] = _check_regex_pattern(non_null, PAN_REGEX, threshold=0.5)
            fp["looks_like_tan"] = _check_regex_pattern(non_null, TAN_REGEX, threshold=0.5)
            fp["looks_like_section"] = _check_regex_pattern(non_null, SECTION_REGEX, threshold=0.7)
            fp["looks_like_bsr"] = _check_regex_pattern(non_null, BSR_REGEX, threshold=0.7)
            fp["looks_like_fy"] = _check_regex_pattern(non_null, FY_REGEX, threshold=0.7)
            fp["looks_like_quarter"] = _check_regex_pattern(non_null, QUARTER_REGEX, threshold=0.7)

            # Set hard_match for bulletproof identifiers
            if fp["looks_like_pan"]:
                fp["hard_match"] = "pan"
            elif fp["looks_like_tan"]:
                fp["hard_match"] = "tan"
            elif fp["looks_like_section"]:
                fp["hard_match"] = "tds_section"
            elif fp["looks_like_date"]:
                fp["hard_match"] = "date"  # generic — cascade will pick specific field
            elif fp["looks_like_fy"]:
                fp["hard_match"] = "financial_year"
            elif fp["looks_like_quarter"]:
                fp["hard_match"] = "quarter"

        fingerprints.append(fp)

    return fingerprints


def detect_cross_column_relationships(df: pd.DataFrame, fingerprints: list[dict]) -> list[dict]:
    """Detect mathematical relationships between numeric columns.

    Finds patterns like:
    - Column A - Column B = Column C (gross - tds = net)
    - Column A * rate = Column B (amount * tds_rate = tds_amount)

    Returns list of discovered relationships:
    [{"type": "subtraction", "a": col_idx, "b": col_idx, "result": col_idx, "confidence": 0.95}]
    """
    # Get numeric columns only
    numeric_fps = [fp for fp in fingerprints if fp["dtype_inferred"] == "float" and fp["mean"] is not None]

    if len(numeric_fps) < 2:
        return []

    relationships = []
    sample_df = df.head(min(50, len(df)))

    # Check all pairs for subtraction relationship: A - B ≈ C
    for i, fp_a in enumerate(numeric_fps):
        col_a = fp_a["source_name"]
        vals_a = pd.to_numeric(sample_df[col_a], errors="coerce")

        for j, fp_b in enumerate(numeric_fps):
            if j == i:
                continue
            col_b = fp_b["source_name"]
            vals_b = pd.to_numeric(sample_df[col_b], errors="coerce")

            diff = vals_a - vals_b

            # Check if this diff matches any other numeric column
            for k, fp_c in enumerate(numeric_fps):
                if k == i or k == j:
                    continue
                col_c = fp_c["source_name"]
                vals_c = pd.to_numeric(sample_df[col_c], errors="coerce")

                # Compare diff to column C (allow 0.1% tolerance)
                valid = diff.notna() & vals_c.notna() & (vals_c != 0)
                if valid.sum() < 5:
                    continue

                ratio = (diff[valid] / vals_c[valid]).abs()
                close_count = ((ratio - 1.0).abs() < 0.001).sum()
                match_pct = close_count / valid.sum()

                if match_pct >= 0.9:
                    relationships.append({
                        "type": "subtraction",
                        "formula": f"{col_a} - {col_b} = {col_c}",
                        "a_idx": fp_a["col_index"],
                        "b_idx": fp_b["col_index"],
                        "result_idx": fp_c["col_index"],
                        "confidence": round(match_pct, 2),
                        "interpretation": _interpret_subtraction(fp_a, fp_b, fp_c),
                    })

    # Check for rate relationship: A * rate_col ≈ B
    pct_fps = [fp for fp in numeric_fps if fp.get("looks_like_percentage")]
    for fp_rate in pct_fps:
        col_rate = fp_rate["source_name"]
        vals_rate = pd.to_numeric(sample_df[col_rate], errors="coerce") / 100.0  # convert % to decimal

        for fp_base in numeric_fps:
            if fp_base["col_index"] == fp_rate["col_index"]:
                continue
            col_base = fp_base["source_name"]
            vals_base = pd.to_numeric(sample_df[col_base], errors="coerce")

            product = vals_base * vals_rate

            for fp_result in numeric_fps:
                if fp_result["col_index"] in (fp_rate["col_index"], fp_base["col_index"]):
                    continue
                col_result = fp_result["source_name"]
                vals_result = pd.to_numeric(sample_df[col_result], errors="coerce")

                valid = product.notna() & vals_result.notna() & (vals_result != 0)
                if valid.sum() < 5:
                    continue

                ratio = (product[valid] / vals_result[valid]).abs()
                close_count = ((ratio - 1.0).abs() < 0.01).sum()
                match_pct = close_count / valid.sum()

                if match_pct >= 0.8:
                    relationships.append({
                        "type": "rate_product",
                        "formula": f"{col_base} × {col_rate}% = {col_result}",
                        "base_idx": fp_base["col_index"],
                        "rate_idx": fp_rate["col_index"],
                        "result_idx": fp_result["col_index"],
                        "confidence": round(match_pct, 2),
                        "interpretation": f"'{col_result}' is likely TDS amount ({col_rate}% of {col_base})",
                    })

    return relationships


def _interpret_subtraction(fp_a: dict, fp_b: dict, fp_c: dict) -> str:
    """Interpret a subtraction relationship for amount disambiguation."""
    a_mean = fp_a.get("mean", 0) or 0
    b_mean = fp_b.get("mean", 0) or 0
    c_mean = fp_c.get("mean", 0) or 0

    # If A is largest, B is smallest, C is in between: A=gross, B=tds, C=net
    if a_mean > c_mean > b_mean:
        return (f"'{fp_a['source_name']}' is likely gross_amount, "
                f"'{fp_b['source_name']}' is likely tds_amount, "
                f"'{fp_c['source_name']}' is likely net_payable")

    # If A is largest, C is small: A=gross, C=net after large deduction
    if a_mean > b_mean and b_mean > 0:
        return (f"'{fp_a['source_name']}' - '{fp_b['source_name']}' = '{fp_c['source_name']}' "
                f"(means: {a_mean:.0f}, {b_mean:.0f}, {c_mean:.0f})")

    return f"{fp_a['source_name']} - {fp_b['source_name']} = {fp_c['source_name']}"


# ═══ Pattern Checkers ═══

def _strip_pandas_suffix(col_name: str) -> str:
    return re.sub(r"\.\d+$", "", col_name)


def _check_regex_pattern(non_null: pd.Series, pattern: re.Pattern, threshold: float = 0.5) -> bool:
    """Check if >threshold of values match a regex pattern."""
    if len(non_null) == 0:
        return False
    sample = non_null.head(20)
    match_count = sum(1 for val in sample if pattern.match(str(val).strip()))
    return len(sample) > 0 and match_count / len(sample) >= threshold


def _infer_dtype(series: pd.Series, non_null: pd.Series) -> str:
    if len(non_null) == 0:
        return "string"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_numeric_dtype(series):
        return "float"
    if _check_date_pattern(non_null):
        return "date"

    numeric_count = 0
    for val in non_null.head(20):
        try:
            str_val = str(val).replace(",", "").replace(" ", "")
            if str_val and str_val not in ("", "None", "nan"):
                float(str_val)
                numeric_count += 1
        except (ValueError, TypeError):
            pass

    sample_size = min(20, len(non_null))
    if sample_size > 0 and numeric_count / sample_size > 0.8:
        return "float"

    return "string"


def _check_date_pattern(non_null: pd.Series) -> bool:
    """Check if >80% of values parse as dates.

    Rejects raw numbers (22090 would parse as a date but isn't one).
    Only accepts: Timestamp objects, strings with date separators (/, -, :).
    """
    if len(non_null) == 0:
        return False
    sample = non_null.head(20)
    date_count = 0
    for val in sample:
        if pd.isna(val):
            continue
        # Already a datetime/Timestamp — definitely a date
        if isinstance(val, (pd.Timestamp,)):
            date_count += 1
            continue
        # Raw numbers are NOT dates (22090.0, 181380, etc.)
        if isinstance(val, (int, float)):
            continue
        # String: must contain date separator to be considered
        str_val = str(val).strip()
        if not str_val:
            continue
        has_separator = any(c in str_val for c in "/-:")
        if not has_separator:
            continue
        try:
            parsed = pd.to_datetime(str_val, errors="raise", dayfirst=True)
            if parsed is not pd.NaT:
                date_count += 1
        except (ValueError, TypeError, OverflowError):
            pass
    return len(sample) > 0 and date_count / len(sample) >= 0.8


def _check_percentage_pattern(fp: dict) -> bool:
    if fp["dtype_inferred"] != "float":
        return False
    if fp["mean"] is None or fp["max"] is None:
        return False
    return 0 <= fp["mean"] <= 100 and fp["max"] <= 100 and fp["min"] is not None and fp["min"] >= 0


def _get_samples(non_null: pd.Series, n: int) -> list:
    samples = []
    for val in non_null.head(n):
        if isinstance(val, (pd.Timestamp,)):
            samples.append(str(val.date()))
        elif isinstance(val, (np.integer,)):
            samples.append(int(val))
        elif isinstance(val, (np.floating,)):
            samples.append(round(float(val), 2))
        else:
            samples.append(str(val)[:50])
    return samples
