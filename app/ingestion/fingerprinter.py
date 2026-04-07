"""
Column Fingerprinter — builds a rich profile per column.

Looks at the DATA inside each column, not just the header name.
This is what lets us disambiguate "Amt. Paid/ Crdt/Drawn Date"
(looks like amount by name, but contains dates by data).

Usage:
    from app.ingestion.fingerprinter import fingerprint_columns
    fingerprints = fingerprint_columns(df)
"""

import re

import pandas as pd
import numpy as np


# PAN pattern: 5 letters, 4 digits, 1 letter
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Max rows to scan for pattern detection (cap for performance)
MAX_SCAN_ROWS = 500


def fingerprint_columns(df: pd.DataFrame) -> list[dict]:
    """Build fingerprint for every column in the DataFrame.

    Args:
        df: Cleaned DataFrame from Excel Loader

    Returns:
        List of fingerprint dicts, one per column.
    """
    columns = list(df.columns)
    fingerprints = []

    for idx, col_name in enumerate(columns):
        series = df[col_name]
        # Cap scan for large files
        scan_series = series.head(MAX_SCAN_ROWS)
        non_null = scan_series.dropna()

        fp = {
            # Identity
            "source_name": col_name,
            "col_index": idx,

            # Handle pandas duplicate suffix (.1, .2)
            "matching_name": _strip_pandas_suffix(col_name),

            # Neighbor context
            "left_neighbor": columns[idx - 1] if idx > 0 else None,
            "right_neighbor": columns[idx + 1] if idx < len(columns) - 1 else None,

            # Data type
            "dtype_inferred": _infer_dtype(scan_series, non_null),

            # Samples (for LLM context and human review)
            "sample_values": _get_samples(non_null, 3),

            # Completeness
            "null_pct": round(scan_series.isna().mean(), 2) if len(scan_series) > 0 else 1.0,

            # Numeric stats
            "mean": None,
            "min": None,
            "max": None,

            # Pattern flags
            "looks_like_date": False,
            "looks_like_pan": False,
            "looks_like_percentage": False,
        }

        # Numeric stats (only if numeric)
        if fp["dtype_inferred"] == "float" and len(non_null) > 0:
            numeric_vals = pd.to_numeric(non_null, errors="coerce").dropna()
            if len(numeric_vals) > 0:
                fp["mean"] = round(float(numeric_vals.mean()), 2)
                fp["min"] = round(float(numeric_vals.min()), 2)
                fp["max"] = round(float(numeric_vals.max()), 2)

        # Pattern detection
        if len(non_null) > 0:
            fp["looks_like_date"] = _check_date_pattern(non_null)
            fp["looks_like_pan"] = _check_pan_pattern(non_null)
            fp["looks_like_percentage"] = _check_percentage_pattern(fp)

        fingerprints.append(fp)

    return fingerprints


def _strip_pandas_suffix(col_name: str) -> str:
    """Strip pandas duplicate column suffix: 'Amount.1' → 'Amount'."""
    return re.sub(r"\.\d+$", "", col_name)


def _infer_dtype(series: pd.Series, non_null: pd.Series) -> str:
    """Infer practical dtype: string, float, date, bool.

    pandas might store dates as 'object' (strings).
    We check the actual values to override.
    """
    if len(non_null) == 0:
        return "string"

    # Check pandas native dtype first
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_numeric_dtype(series):
        return "float"

    # pandas says 'object' — check if values are actually dates or numbers
    if _check_date_pattern(non_null):
        return "date"

    # Check if values are mostly numeric strings
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
    """Check if >80% of values parse as dates."""
    if len(non_null) == 0:
        return False

    sample = non_null.head(20)
    date_count = 0

    for val in sample:
        if pd.isna(val):
            continue
        # Already a datetime
        if isinstance(val, (pd.Timestamp,)):
            date_count += 1
            continue
        # Try parsing string as date
        try:
            parsed = pd.to_datetime(val, errors="raise", dayfirst=True)
            if parsed is not pd.NaT:
                date_count += 1
        except (ValueError, TypeError, OverflowError):
            pass

    return len(sample) > 0 and date_count / len(sample) >= 0.8


def _check_pan_pattern(non_null: pd.Series) -> bool:
    """Check if >50% of values match PAN format: AAAAA0000A."""
    if len(non_null) == 0:
        return False

    sample = non_null.head(20)
    pan_count = sum(1 for val in sample if PAN_REGEX.match(str(val).strip()))
    return pan_count / len(sample) >= 0.5


def _check_percentage_pattern(fp: dict) -> bool:
    """Check if column looks like percentages: mean 0-100, max ≤ 100."""
    if fp["dtype_inferred"] != "float":
        return False
    if fp["mean"] is None or fp["max"] is None:
        return False
    return 0 <= fp["mean"] <= 100 and fp["max"] <= 100 and fp["min"] is not None and fp["min"] >= 0


def _get_samples(non_null: pd.Series, n: int) -> list:
    """Get first N non-null values as serializable list."""
    samples = []
    for val in non_null.head(n):
        if isinstance(val, (pd.Timestamp,)):
            samples.append(str(val.date()))
        elif isinstance(val, (np.integer,)):
            samples.append(int(val))
        elif isinstance(val, (np.floating,)):
            samples.append(round(float(val), 2))
        else:
            samples.append(str(val)[:50])  # cap length for display
    return samples
