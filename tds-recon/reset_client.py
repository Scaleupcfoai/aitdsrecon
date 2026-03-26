"""
Reset client data for a new engagement.

Clears vendor-specific learned rules, parsed data, and results
while retaining the rule type patterns (below_threshold, ignore, etc.).

Usage:
    python reset_client.py              # Clear all client data
    python reset_client.py --keep-rules # Keep rule types, clear vendor names
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
PARSED_DIR = BASE / "data" / "parsed"
RESULTS_DIR = BASE / "data" / "results"
RULES_DIR = BASE / "data" / "rules"
UPLOADS_DIR = BASE / "data" / "uploads"


def reset(keep_rules=False):
    """Reset all client-specific data."""

    # 1. Clear parsed data
    for f in PARSED_DIR.glob("*.json"):
        f.unlink()
        print(f"  Deleted: {f}")

    # 2. Clear results
    for f in RESULTS_DIR.glob("*"):
        f.unlink()
        print(f"  Deleted: {f}")

    # 3. Clear uploads
    for f in UPLOADS_DIR.glob("*"):
        f.unlink()
        print(f"  Deleted: {f}")

    # 4. Handle learned rules
    rules_file = RULES_DIR / "learned_rules.json"
    if rules_file.exists():
        if keep_rules:
            # Retain rule patterns but strip vendor-specific details
            with open(rules_file) as f:
                db = json.load(f)

            # Summarize what we had for reference
            rules = db.get("rules", [])
            from collections import Counter
            type_counts = Counter(r["rule_type"] for r in rules)
            print(f"\n  Previous rules: {len(rules)} total")
            for t, c in type_counts.items():
                print(f"    {t}: {c}")

            # Extract thresholds and patterns (not vendor names)
            patterns = {
                "rule_types_seen": list(type_counts.keys()),
                "threshold_values": list(set(
                    r["params"].get("threshold") for r in rules
                    if r["params"].get("threshold")
                )),
                "sections_seen": list(set(
                    r["params"].get("section") for r in rules
                    if r["params"].get("section")
                )),
                "note": "Patterns from previous client — apply similar logic to new vendors",
            }

            # Reset rules but keep pattern reference
            db["rules"] = []
            db["patterns_from_previous"] = patterns
            with open(rules_file, "w") as f:
                json.dump(db, f, indent=2)
            print(f"  Rules cleared, patterns retained: {rules_file}")
        else:
            rules_file.unlink()
            print(f"  Deleted: {rules_file}")

    print("\nClient data reset complete. Ready for new client files.")


if __name__ == "__main__":
    keep = "--keep-rules" in sys.argv
    print("=" * 50)
    print("TDS RECON — CLIENT DATA RESET")
    print("=" * 50)
    if keep:
        print("Mode: Keep rule patterns, clear vendor data\n")
    else:
        print("Mode: Full reset\n")
    reset(keep_rules=keep)
