"""PAN validation and vendor-name normalization."""

import re

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def is_valid_pan(pan: str | None) -> bool:
    """Structural validation only. Format: AAAAA9999A."""
    if not pan:
        return False
    return bool(PAN_REGEX.match(pan.strip().upper()))


def normalize_name(name: str | None) -> str:
    """Normalize vendor name for comparison (strip suffixes, whitespace)."""
    if not name:
        return ""
    n = name.lower().strip()
    for suffix in [
        "pvt. ltd.", "pvt ltd", "private limited",
        "ltd.", "ltd", "llp", "lp", "inc.", "inc", "co.", "company",
    ]:
        n = n.replace(suffix, "")
    n = re.sub(r"\(\d+\)", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n
