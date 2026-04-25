"""
GST Reconciliation Agents — 3 agents for Lekha AI
=================================================
Agent 1: GST Output Recon — GSTR-1 vs Sales Register (books)
Agent 2: GST ITC Recon — GSTR-2B vs Purchase GST Exp Register (books)
Agent 3: GST Liability Recon — GSTR-1 vs GSTR-3B

All 3 agents follow the same pattern as the TDS recon pipeline:
  Parse → Match → Check → Report
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agents.gst_parser_agent import parse_all_gst


def _fmt(val):
    """Indian number format."""
    if val is None:
        return "—"
    return f"₹{abs(val):,.0f}"


# ---------------------------------------------------------------------------
# Agent 1: GST Output Recon (GSTR-1 vs Sales Register)
# ---------------------------------------------------------------------------

def run_gst_output_recon(gst_data: dict, event_callback=None) -> dict:
    """Compare GSTR-1 filed sales with Sales Register (Tally books).

    Monthly comparison:
    - GSTR-1 taxable value vs Sales Register total sales
    - GSTR-1 tax (IGST+CGST+SGST) vs expected tax on sales
    """
    def emit(msg, type="detail"):
        if event_callback:
            event_callback("GST Output Agent", msg, type)
        print(f"  [{type}] {msg}")

    gstr1 = gst_data.get("gstr1", {})
    sales = gst_data.get("sales", {})

    if not gstr1 or not sales:
        return {"error": "Missing GSTR-1 or Sales Register data"}

    emit("Comparing GSTR-1 filed values with Sales Register...")

    findings = []
    monthly_comparison = {}

    # Map month names: Sales Register uses "April", GSTR-1 uses "Apr"
    month_map = {"April": "Apr", "May": "May", "June": "Jun",
                 "July": "Jul", "August": "Aug", "September": "Sep",
                 "October": "Oct", "November": "Nov", "December": "Dec",
                 "January": "Jan", "February": "Feb", "March": "Mar"}

    for sales_month, sales_data in sales.get("monthly", {}).items():
        gstr1_month = month_map.get(sales_month, sales_month)
        gstr1_data = gstr1.get("monthly", {}).get(gstr1_month, {})

        books_sales = sales_data.get("total_sales", 0)
        filed_taxable = gstr1_data.get("taxable_value", 0)
        filed_tax = (gstr1_data.get("igst", 0) + gstr1_data.get("cgst", 0) +
                     gstr1_data.get("sgst", 0))

        variance = books_sales - filed_taxable
        pct_variance = (variance / books_sales * 100) if books_sales > 0 else 0

        month_result = {
            "month": sales_month,
            "books_sales": books_sales,
            "gstr1_taxable": filed_taxable,
            "gstr1_tax": filed_tax,
            "variance": round(variance, 2),
            "variance_pct": round(pct_variance, 2),
            "status": "matched" if abs(pct_variance) < 1 else ("minor" if abs(pct_variance) < 5 else "mismatch"),
        }
        monthly_comparison[sales_month] = month_result

        if abs(variance) > 100:
            severity = "error" if abs(pct_variance) >= 5 else "warning"
            findings.append({
                "check": "gst_output_variance",
                "severity": severity,
                "month": sales_month,
                "books_sales": books_sales,
                "gstr1_taxable": filed_taxable,
                "variance": round(variance, 2),
                "variance_pct": round(pct_variance, 2),
                "message": (f"{sales_month}: Books sales {_fmt(books_sales)} vs "
                            f"GSTR-1 taxable {_fmt(filed_taxable)} — "
                            f"variance {_fmt(variance)} ({pct_variance:.1f}%)"),
            })

        status = "✓" if abs(pct_variance) < 1 else f"⚠ {pct_variance:.1f}% variance"
        emit(f"{sales_month}: Books {_fmt(books_sales)} vs GSTR-1 {_fmt(filed_taxable)} — {status}")

    total_books = sum(m["books_sales"] for m in monthly_comparison.values())
    total_filed = sum(m["gstr1_taxable"] for m in monthly_comparison.values())
    total_variance = total_books - total_filed

    summary = {
        "total_books_sales": round(total_books, 2),
        "total_gstr1_taxable": round(total_filed, 2),
        "total_variance": round(total_variance, 2),
        "months_compared": len(monthly_comparison),
        "months_matched": sum(1 for m in monthly_comparison.values() if m["status"] == "matched"),
        "findings_count": len(findings),
    }

    if findings:
        emit(f"{len(findings)} month(s) with variance", "warning")
    else:
        emit("All months reconciled", "success")

    return {
        "agent": "gst_output",
        "summary": summary,
        "monthly": monthly_comparison,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Agent 2: GST ITC Recon (GSTR-2B vs Purchase Books)
# ---------------------------------------------------------------------------

def run_gst_itc_recon(gst_data: dict, tally_gst_exp: list = None, event_callback=None) -> dict:
    """Compare GSTR-2B vendor invoices with Purchase GST Exp Register.

    Invoice-level matching:
    - Match by vendor GSTIN + invoice amount
    - Flag: ITC in 2B but not in books (missed claim)
    - Flag: ITC in books but not in 2B (ineligible)
    """
    def emit(msg, type="detail"):
        if event_callback:
            event_callback("GST ITC Agent", msg, type)
        print(f"  [{type}] {msg}")

    gstr2b = gst_data.get("gstr2b", {})
    invoices_2b = gstr2b.get("invoices", [])

    if not invoices_2b:
        return {"error": "Missing GSTR-2B data"}

    emit(f"Matching {len(invoices_2b)} GSTR-2B invoices against books...")

    # Group 2B invoices by vendor name (normalized)
    def normalize(name):
        if not name:
            return ""
        return name.lower().strip()

    findings = []
    matched = []
    in_2b_not_books = []
    in_books_not_2b = []

    # Build lookup from 2B
    vendor_2b = defaultdict(list)
    for inv in invoices_2b:
        key = normalize(inv["vendor_name"])
        vendor_2b[key].append(inv)

    # Load Purchase Register entries too — ITC comes from both expenses and goods
    tally_purchase = []
    parsed_tally_path = Path(__file__).parent.parent / "data" / "parsed" / "parsed_tally.json"
    if parsed_tally_path.exists():
        with open(parsed_tally_path) as f:
            tally = json.load(f)
        tally_purchase = tally.get("purchase_register", {}).get("entries", [])
        if not tally_gst_exp:
            tally_gst_exp = tally.get("purchase_gst_exp_register", {}).get("entries", [])

    # Combine all books entries for matching
    all_books = []
    if tally_gst_exp:
        for e in tally_gst_exp:
            all_books.append({
                "particulars": e.get("particulars", ""),
                "gross_total": e.get("gross_total", 0),
                "base_amount": e.get("base_amount", 0),
                "total_gst": e.get("total_gst", 0),
                "source": "gst_exp",
            })
    for e in tally_purchase:
        all_books.append({
            "particulars": e.get("particulars", ""),
            "gross_total": e.get("gross_total", 0),
            "base_amount": e.get("purchase_value", 0) or e.get("gross_total", 0),
            "total_gst": e.get("total_gst", 0),
            "source": "purchase",
        })

    if all_books:
        emit(f"Cross-referencing with {len(all_books)} books entries (GST Exp + Purchase Register)...")

        # Build lookup from books
        vendor_books = defaultdict(list)
        for entry in all_books:
            key = normalize(entry.get("particulars", ""))
            vendor_books[key].append(entry)

        # Match strategy: vendor name (normalized) + amount tolerance
        # GSTR-2B has abbreviated names, Tally has full names
        # Also try: amount-only matching within same month as fallback

        used_books = set()  # track matched books entries

        for inv in invoices_2b:
            inv_vendor = normalize(inv["vendor_name"])
            inv_amount = inv["taxable_value"]
            inv_date = inv.get("invoice_date")
            inv_month = inv_date.strftime("%Y-%m") if inv_date else ""
            inv_matched = False

            # Strategy 1: vendor name match + amount tolerance
            for bk_vendor, entries in vendor_books.items():
                # Fuzzy name: 2B name contained in books name or vice versa
                name_match = (inv_vendor in bk_vendor or bk_vendor in inv_vendor or
                              inv_vendor[:4] == bk_vendor[:4])  # First 4 chars
                if not name_match:
                    continue

                for idx, be in enumerate(entries):
                    be_key = f"{bk_vendor}|{idx}"
                    if be_key in used_books:
                        continue
                    be_base = be.get("base_amount", 0) or 0
                    be_gross = be.get("gross_total", 0) or 0
                    # Try matching taxable_value vs base, or invoice_value vs gross
                    diff_base = abs(inv_amount - be_base)
                    diff_gross = abs(inv.get("invoice_value", 0) - be_gross)
                    best_diff = min(diff_base, diff_gross)
                    be_amount = be_base if diff_base <= diff_gross else be_gross
                    if best_diff < max(2, inv_amount * 0.05):  # 5% tolerance
                        matched.append({
                            "vendor_2b": inv["vendor_name"],
                            "vendor_books": be.get("particulars", ""),
                            "gstin": inv["gstin"],
                            "invoice_no": inv["invoice_no"],
                            "amount_2b": inv_amount,
                            "amount_books": be_amount,
                            "itc_2b": inv["igst"] + inv["cgst"] + inv["sgst"],
                            "itc_books": be.get("total_gst", 0),
                            "match_type": "vendor_name",
                        })
                        used_books.add(be_key)
                        inv_matched = True
                        break
                if inv_matched:
                    break

            # Strategy 2: amount-only match (same month, exact amount)
            if not inv_matched and inv_amount > 100:
                for bk_vendor, entries in vendor_books.items():
                    for idx, be in enumerate(entries):
                        be_key = f"{bk_vendor}|{idx}"
                        if be_key in used_books:
                            continue
                        be_base = be.get("base_amount", 0) or 0
                        be_gross = be.get("gross_total", 0) or 0
                        be_amount = be_base
                        if abs(inv_amount - be_base) < 2 or abs(inv.get("invoice_value", 0) - be_gross) < 2:
                            matched.append({
                                "vendor_2b": inv["vendor_name"],
                                "vendor_books": be.get("particulars", ""),
                                "gstin": inv["gstin"],
                                "invoice_no": inv["invoice_no"],
                                "amount_2b": inv_amount,
                                "amount_books": be_amount,
                                "itc_2b": inv["igst"] + inv["cgst"] + inv["sgst"],
                                "itc_books": be.get("total_gst", 0),
                                "match_type": "amount_exact",
                            })
                            used_books.add(be_key)
                            inv_matched = True
                            break
                    if inv_matched:
                        break

            if not inv_matched:
                in_2b_not_books.append(inv)
    else:
        # No books data — all 2B entries are unmatched against books
        in_2b_not_books = invoices_2b

    # Summary stats
    total_itc_2b = sum(i["igst"] + i["cgst"] + i["sgst"] for i in invoices_2b)
    matched_itc = sum(m["itc_2b"] for m in matched)
    unmatched_itc = sum(i["igst"] + i["cgst"] + i["sgst"] for i in in_2b_not_books)

    emit(f"Matched: {len(matched)} invoices ({_fmt(matched_itc)} ITC)")
    if in_2b_not_books:
        emit(f"In GSTR-2B but not in books: {len(in_2b_not_books)} ({_fmt(unmatched_itc)})", "warning")
        # Group unmatched by vendor
        unmatched_vendors = defaultdict(lambda: {"count": 0, "amount": 0})
        for inv in in_2b_not_books:
            v = inv["vendor_name"]
            unmatched_vendors[v]["count"] += 1
            unmatched_vendors[v]["amount"] += inv["taxable_value"]

        for v, data in sorted(unmatched_vendors.items(), key=lambda x: -x[1]["amount"])[:5]:
            findings.append({
                "check": "itc_in_2b_not_books",
                "severity": "warning",
                "vendor": v,
                "count": data["count"],
                "amount": round(data["amount"], 2),
                "message": f"{v}: {data['count']} invoices ({_fmt(data['amount'])}) in GSTR-2B but not matched in books",
            })

    # Compare with GSTR-3B ITC claimed
    gstr3b = gst_data.get("gstr3b", {})
    itc_claimed = gstr3b.get("itc", {})
    if itc_claimed:
        emit("Comparing ITC available (2B) vs ITC claimed (3B)...")
        for month, claimed in itc_claimed.items():
            claimed_total = claimed["igst"] + claimed["cgst"] + claimed["sgst"]
            # Compare with 2B summary if available
            summary_2b = gstr2b.get("summary", {}).get("b2b_invoices", {})
            month_lower = month.lower()
            available_2b = summary_2b.get(month_lower, {})
            if available_2b:
                available_total = available_2b.get("igst", 0) + available_2b.get("cgst", 0) + available_2b.get("sgst", 0)
                diff = claimed_total - available_total
                if abs(diff) > 100:
                    findings.append({
                        "check": "itc_claimed_vs_available",
                        "severity": "warning" if diff > 0 else "info",
                        "month": month,
                        "itc_available_2b": round(available_total, 2),
                        "itc_claimed_3b": round(claimed_total, 2),
                        "excess_claim": round(diff, 2),
                        "message": (f"{month}: ITC claimed {_fmt(claimed_total)} vs "
                                    f"ITC available (2B) {_fmt(available_total)} — "
                                    f"{'excess claim' if diff > 0 else 'under-claimed'} {_fmt(abs(diff))}"),
                    })
                    emit(f"{month}: {'Excess' if diff > 0 else 'Under'} ITC claim of {_fmt(abs(diff))}", "warning")

    summary = {
        "total_2b_invoices": len(invoices_2b),
        "matched": len(matched),
        "in_2b_not_books": len(in_2b_not_books),
        "total_itc_2b": round(total_itc_2b, 2),
        "matched_itc": round(matched_itc, 2),
        "unmatched_itc": round(unmatched_itc, 2),
        "match_rate": round(len(matched) / max(len(invoices_2b), 1) * 100, 1),
        "findings_count": len(findings),
    }

    return {
        "agent": "gst_itc",
        "summary": summary,
        "matched": matched,
        "in_2b_not_books": in_2b_not_books[:20],  # Limit for JSON size
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Agent 3: GST Liability Recon (GSTR-1 vs GSTR-3B)
# ---------------------------------------------------------------------------

def run_gst_liability_recon(gst_data: dict, event_callback=None) -> dict:
    """Compare GSTR-1 tax liability declared with GSTR-3B tax paid.

    Monthly comparison:
    - GSTR-1 total tax (outward) vs GSTR-3B total tax (paid)
    - Flag underpayment or overpayment
    """
    def emit(msg, type="detail"):
        if event_callback:
            event_callback("GST Liability Agent", msg, type)
        print(f"  [{type}] {msg}")

    gstr1 = gst_data.get("gstr1", {})
    gstr3b = gst_data.get("gstr3b", {})

    if not gstr1 or not gstr3b:
        return {"error": "Missing GSTR-1 or GSTR-3B data"}

    emit("Comparing GSTR-1 liability with GSTR-3B payments...")

    findings = []
    monthly_comparison = {}

    # For each month in GSTR-3B outward
    for month, g3b_out in gstr3b.get("outward", {}).items():
        g1_data = gstr1.get("monthly", {}).get(month, {})

        g1_tax = g1_data.get("igst", 0) + g1_data.get("cgst", 0) + g1_data.get("sgst", 0)
        g3b_tax = g3b_out.get("igst", 0) + g3b_out.get("cgst", 0) + g3b_out.get("sgst", 0)

        g1_taxable = g1_data.get("taxable_value", 0)
        g3b_taxable = g3b_out.get("taxable_value", 0)

        tax_diff = g3b_tax - g1_tax
        taxable_diff = g3b_taxable - g1_taxable

        month_result = {
            "month": month,
            "gstr1_taxable": g1_taxable,
            "gstr3b_taxable": g3b_taxable,
            "taxable_diff": round(taxable_diff, 2),
            "gstr1_tax": round(g1_tax, 2),
            "gstr3b_tax": round(g3b_tax, 2),
            "tax_diff": round(tax_diff, 2),
            "gstr1_igst": g1_data.get("igst", 0),
            "gstr1_cgst": g1_data.get("cgst", 0),
            "gstr1_sgst": g1_data.get("sgst", 0),
            "gstr3b_igst": g3b_out.get("igst", 0),
            "gstr3b_cgst": g3b_out.get("cgst", 0),
            "gstr3b_sgst": g3b_out.get("sgst", 0),
            "status": "matched" if abs(tax_diff) < 100 else "mismatch",
        }
        monthly_comparison[month] = month_result

        if abs(tax_diff) >= 100 or abs(taxable_diff) >= 1000:
            severity = "error" if abs(tax_diff) >= 10000 else "warning"
            findings.append({
                "check": "gst_liability_mismatch",
                "severity": severity,
                "month": month,
                "gstr1_tax": round(g1_tax, 2),
                "gstr3b_tax": round(g3b_tax, 2),
                "tax_diff": round(tax_diff, 2),
                "taxable_diff": round(taxable_diff, 2),
                "message": (f"{month}: GSTR-1 tax {_fmt(g1_tax)} vs GSTR-3B tax {_fmt(g3b_tax)} — "
                            f"diff {_fmt(tax_diff)}. "
                            f"Taxable value diff: {_fmt(taxable_diff)}"),
            })

        status = "✓ matched" if abs(tax_diff) < 100 else f"diff {_fmt(tax_diff)}"
        emit(f"{month}: GSTR-1 tax {_fmt(g1_tax)} vs GSTR-3B {_fmt(g3b_tax)} — {status}")

    total_g1_tax = sum(m["gstr1_tax"] for m in monthly_comparison.values())
    total_g3b_tax = sum(m["gstr3b_tax"] for m in monthly_comparison.values())

    summary = {
        "total_gstr1_tax": round(total_g1_tax, 2),
        "total_gstr3b_tax": round(total_g3b_tax, 2),
        "total_diff": round(total_g3b_tax - total_g1_tax, 2),
        "months_compared": len(monthly_comparison),
        "months_matched": sum(1 for m in monthly_comparison.values() if m["status"] == "matched"),
        "findings_count": len(findings),
    }

    if findings:
        emit(f"{len(findings)} month(s) with liability mismatch", "warning")
    else:
        emit("All months reconciled — liability matches payments", "success")

    return {
        "agent": "gst_liability",
        "summary": summary,
        "monthly": monthly_comparison,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Run all 3 GST agents
# ---------------------------------------------------------------------------

def run_all_gst_recons(data_dir: str, output_dir: str, event_callback=None) -> dict:
    """Parse all GST data and run all 3 reconciliation agents."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Parse all sources
    gst_data = parse_all_gst(data_dir, str(output_dir))

    # Load Tally GST Exp entries for ITC matching
    tally_gst_exp = None
    parsed_tally_path = output_dir / "parsed_tally.json"
    if parsed_tally_path.exists():
        with open(parsed_tally_path) as f:
            tally = json.load(f)
        tally_gst_exp = tally.get("purchase_gst_exp_register", {}).get("entries", [])

    results = {}

    # Agent 1: GST Output
    print("\n" + "=" * 50)
    print("AGENT 1: GST Output Recon (GSTR-1 vs Sales)")
    print("=" * 50)
    results["gst_output"] = run_gst_output_recon(gst_data, event_callback)

    # Agent 2: GST ITC
    print("\n" + "=" * 50)
    print("AGENT 2: GST ITC Recon (GSTR-2B vs Books)")
    print("=" * 50)
    results["gst_itc"] = run_gst_itc_recon(gst_data, tally_gst_exp, event_callback)

    # Agent 3: GST Liability
    print("\n" + "=" * 50)
    print("AGENT 3: GST Liability Recon (GSTR-1 vs GSTR-3B)")
    print("=" * 50)
    results["gst_liability"] = run_gst_liability_recon(gst_data, event_callback)

    # Write results
    out_file = output_dir / "gst_recon_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[GST Recon] Wrote {out_file}")

    # Print summary
    print("\n" + "=" * 50)
    print("GST RECONCILIATION SUMMARY")
    print("=" * 50)
    for agent_name, result in results.items():
        s = result.get("summary", {})
        findings = result.get("findings", [])
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")
        print(f"\n  {agent_name}:")
        print(f"    Findings: {len(findings)} ({errors} errors, {warnings} warnings)")
        for k, v in s.items():
            if k != "findings_count":
                print(f"    {k}: {v}")

    return results


if __name__ == "__main__":
    base = Path(__file__).parent.parent.parent
    run_all_gst_recons(str(base / "data" / "hpc"), str(base / "tds-recon" / "data" / "results"))
