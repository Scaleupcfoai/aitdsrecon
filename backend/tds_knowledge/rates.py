"""TDS rate table — sourced from CA's TDS Master Data, FY 2025-26.

Section -> entity_type -> rate (percent).
Entity types resolved from PAN 4th character via entity_type_from_pan():
  C = company       -> 'company'
  P, H = individual / HUF -> 'individual_huf'
  F = firm          -> 'firm' (mapped to individual_huf for most sections)

Section 206AA penal rate when PAN missing/invalid: 20%
(except sections noted otherwise in CA file).
"""

from __future__ import annotations

# Section -> {entity_type -> rate_pct, "default": fallback}
TDS_RATES: dict[str, dict[str, float]] = {
    # ── Frequently-used sections ──
    "192":      {"individual_huf": 0.0,  "company": 0.0,  "default": 0.0,
                 "_note": "slab-based — out of scope for this calculator"},
    "194A":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},
    "194C":     {"individual_huf": 1.0,  "company": 2.0,  "default": 2.0},
    "194H":     {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},
    "194I(a)":  {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # plant/machinery
    "194I(b)":  {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # building/land/furniture
    "194J(a)":  {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # technical / call centre
    "194J(b)":  {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # professional / royalty
    "194Q":     {"individual_huf": 0.1,  "company": 0.1,  "default": 0.1},
    "194T":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # partner remuneration

    # ── Less common but fully supported ──
    "193":      {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # interest on securities
    "194":      {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # dividend
    "194B":     {"individual_huf": 30.0, "company": 30.0, "default": 30.0},  # lottery
    "194BA":    {"individual_huf": 30.0, "company": 30.0, "default": 30.0},  # online games
    "194BB":    {"individual_huf": 30.0, "company": 30.0, "default": 30.0},  # horse race
    "194D":     {"individual_huf": 5.0,  "company": 10.0, "default": 5.0},   # insurance commission
    "194DA":    {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # life insurance maturity
    "194E":     {"individual_huf": 20.0, "company": 20.0, "default": 20.0},  # NR sportsmen
    "194EE":    {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # NSS withdrawals
    "194G":     {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # lottery commission
    "194-IA":   {"individual_huf": 1.0,  "company": 1.0,  "default": 1.0},   # immovable property
    "194-IB":   {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # rent by ind/HUF (not under audit)
    "194-IC":   {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # JDA
    "194K":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # MF dividend
    "194LA":    {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # land acquisition
    "194M":     {"individual_huf": 2.0,  "company": 2.0,  "default": 2.0},   # contractor by ind/HUF
    "194O":     {"individual_huf": 0.1,  "company": 0.1,  "default": 0.1},   # e-commerce
    "194R":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},  # perquisites
    "194S":     {"individual_huf": 1.0,  "company": 1.0,  "default": 1.0},   # VDA

    # ── Non-resident payments ──
    # 195 / 196A-D rates are indicative; final rate often follows DTAA. We
    # surface as needs_user_review when these hit so the deductor confirms.
    "195":      {"individual_huf": 20.0, "company": 20.0, "default": 20.0,
                 "_note": "use DTAA rate if lower; surcharge + cess apply"},
    "196A":     {"individual_huf": 20.0, "company": 20.0, "default": 20.0},
    "196B":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},
    "196C":     {"individual_huf": 10.0, "company": 10.0, "default": 10.0},
    "196D":     {"individual_huf": 20.0, "company": 20.0, "default": 20.0},
}

# Section 206AA — penal rate when PAN missing/invalid.
# Rate = max(applicable section rate, SECTION_206AA_RATE).
# Exceptions: 194O / 194Q / 194-IA cap at 5% per CA file column.
SECTION_206AA_RATE = 20.0
SECTION_206AA_CAPPED = {
    "194O": 5.0,
    "194Q": 5.0,
    "194-IA": 5.0,
}


def entity_type_from_pan(pan: str) -> str:
    """Derive entity type from PAN 4th character.

    C = Company, P = Individual, H = HUF, F = Firm, T = Trust, A = AOP, B = BOI, L = Local Authority, J = Artificial Juridical.
    """
    if not pan or len(pan) < 4:
        return "unknown"
    fourth = pan[3].upper()
    if fourth == "C":
        return "company"
    if fourth in ("P", "H"):
        return "individual_huf"
    if fourth == "F":
        return "firm"
    return "unknown"


def expected_rate(section: str, pan: str) -> float | None:
    """Expected TDS rate for section + PAN. Returns None if section unknown."""
    rates = TDS_RATES.get(section)
    if not rates:
        return None
    etype = entity_type_from_pan(pan)
    if etype == "firm":
        etype = "individual_huf"
    return rates.get(etype, rates.get("default"))


def section_206aa_rate(section: str) -> float:
    """Return the penal rate to use under 206AA (PAN missing) for a given section."""
    return SECTION_206AA_CAPPED.get(section, SECTION_206AA_RATE)
