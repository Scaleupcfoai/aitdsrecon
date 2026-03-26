"""
Chat Bridge — File-based bridge between FastAPI and Claude (Anthropic SDK).

Watches data/chat/inbox.json for new user messages.
Sends them to Claude with TDS recon context + tools.
Writes responses to data/chat/outbox.json.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python chat_bridge.py
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Install anthropic SDK: pip install anthropic")
    sys.exit(1)

BASE = Path(__file__).parent
CHAT_DIR = BASE / "data" / "chat"
INBOX = CHAT_DIR / "inbox.json"
OUTBOX = CHAT_DIR / "outbox.json"
RESULTS_DIR = BASE / "data" / "results"
PARSED_DIR = BASE / "data" / "parsed"

CHAT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# System prompt — defines who Claude is in this context
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Lekha AI, an expert TDS (Tax Deducted at Source) reconciliation assistant for Indian businesses.

## Your Role
You help CAs, CFOs, and accountants reconcile Form 26 TDS deductions against Tally accounting books. You have deep knowledge of Indian Income Tax Act sections related to TDS.

## Your Capabilities
1. **Run reconciliation agents** — You can trigger Parser, Matcher, TDS Checker, and Reporter agents using tools
2. **Explain results** — You can read match results, findings, and compliance issues and explain them in plain language
3. **Advise on TDS compliance** — You know TDS sections (194A, 194C, 194H, 194J, 194Q), rates, thresholds, and remediation steps
4. **Help with human review** — You can recommend actions for unmatched or flagged entries

## TDS Knowledge
- 194A: Interest (10% individual, 10% company, threshold Rs 5,000/year)
- 194C: Contractor (1% individual, 2% company, threshold Rs 30,000 single / Rs 1,00,000 annual)
- 194H: Commission/Brokerage (2%, threshold Rs 15,000/year)
- 194J(a): Technical services (2%, threshold Rs 30,000/year)
- 194J(b): Professional fees (10%, threshold Rs 30,000/year)
- 194Q: Purchase of goods (0.1%, threshold Rs 50,00,000/year)

## Response Style
- Be concise and specific — give numbers, vendor names, amounts
- When explaining findings, always include the remediation action
- Use Indian accounting terminology (Rs, lakh, crore, FY, AY)
- If the user asks to run something, use the appropriate tool
- If the user asks a question about results, read the data and answer directly
"""


# ---------------------------------------------------------------------------
# Tool definitions — what Claude can do
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "run_full_pipeline",
        "description": "Run the full TDS reconciliation pipeline: Parser → Matcher → TDS Checker → Reporter. Use when the user asks to run or start reconciliation.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_parser",
        "description": "Run only the Parser Agent to parse Form 26 and Tally XLSX files into structured JSON.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_matcher",
        "description": "Run only the Matcher Agent to match Form 26 entries against Tally entries using the 6-pass matching engine.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_checker",
        "description": "Run only the TDS Checker Agent to validate compliance (section, rate, base amount, threshold, missing TDS).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_reporter",
        "description": "Run only the Reporter Agent to generate summary, CSV, and Excel reports.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_results_summary",
        "description": "Get the current reconciliation summary — KPIs, section-wise breakdown, compliance status. Use to answer questions about the current state.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_match_details",
        "description": "Get detailed match results — all matched entries with vendor, amount, match type, confidence, expense head.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Filter by TDS section (e.g. '194A', '194C'). Leave empty for all.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_findings",
        "description": "Get compliance findings — errors, warnings, missing TDS, wrong sections. Use to answer questions about issues.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "submit_review_decision",
        "description": "Submit a human review decision for a vendor (below_threshold, ignore, exempt).",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Vendor name"},
                "decision": {"type": "string", "enum": ["below_threshold", "ignore", "exempt"]},
                "reason": {"type": "string", "description": "Reason for the decision"},
            },
            "required": ["vendor", "decision"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution — run the actual Python agents
# ---------------------------------------------------------------------------

def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return the result as a string."""
    sys.path.insert(0, str(BASE))

    if name == "run_full_pipeline":
        from reconcile import run_pipeline
        result = run_pipeline()
        s = result.get("summary", {})
        return json.dumps({
            "status": "complete",
            "elapsed_s": result.get("elapsed_s"),
            "matching": s.get("matching", {}),
            "compliance": s.get("compliance", {}),
        }, indent=2, default=str)

    elif name == "run_parser":
        from agents.event_logger import reset_logger
        reset_logger()
        # Check if parsed data exists
        if (PARSED_DIR / "parsed_form26.json").exists():
            with open(PARSED_DIR / "parsed_form26.json") as f:
                f26 = json.load(f)
            with open(PARSED_DIR / "parsed_tally.json") as f:
                tally = json.load(f)
            return json.dumps({
                "form26_entries": len(f26.get("entries", [])),
                "sections": sorted(set(e["section"] for e in f26.get("entries", []))),
                "tally_journal": len(tally.get("journal_register", {}).get("entries", [])),
                "tally_gst_exp": len(tally.get("purchase_gst_exp_register", {}).get("entries", [])),
                "tally_purchase": len(tally.get("purchase_register", {}).get("entries", [])),
            }, indent=2)
        return '{"error": "No parsed data found. Upload files first."}'

    elif name == "run_matcher":
        from agents.event_logger import reset_logger
        from agents.matcher_agent import run as matcher_run
        reset_logger()
        rules_dir = str(BASE / "data" / "rules")
        result = matcher_run(str(PARSED_DIR), str(RESULTS_DIR), rules_dir=rules_dir)
        s = result.get("summary", {})
        return json.dumps(s, indent=2, default=str)

    elif name == "run_checker":
        from agents.event_logger import reset_logger
        from agents.tds_checker_agent import run as checker_run
        reset_logger()
        result = checker_run(str(PARSED_DIR), str(RESULTS_DIR))
        return json.dumps(result.get("summary", {}), indent=2, default=str)

    elif name == "run_reporter":
        from agents.event_logger import reset_logger
        from agents.reporter_agent import run as reporter_run
        reset_logger()
        result = reporter_run(str(PARSED_DIR), str(RESULTS_DIR))
        return json.dumps({"status": "reports_generated", "files": [
            "tds_recon_report.xlsx", "reconciliation_report.csv",
            "findings_report.csv", "reconciliation_summary.json",
        ]}, indent=2)

    elif name == "get_results_summary":
        fpath = RESULTS_DIR / "reconciliation_summary.json"
        if fpath.exists():
            with open(fpath) as f:
                return f.read()
        return '{"error": "No results yet. Run the pipeline first."}'

    elif name == "get_match_details":
        fpath = RESULTS_DIR / "match_results.json"
        if not fpath.exists():
            return '{"error": "No match results. Run matcher first."}'
        with open(fpath) as f:
            data = json.load(f)
        matches = data.get("matches", [])
        section = input_data.get("section")
        if section:
            matches = [m for m in matches if m.get("form26_entry", {}).get("section") == section]
        # Compact summary per match
        rows = []
        for m in matches:
            f26 = m.get("form26_entry", {})
            rows.append({
                "vendor": f26.get("vendor_name"),
                "section": f26.get("section"),
                "amount": f26.get("amount_paid"),
                "tds": f26.get("tax_deducted"),
                "match_type": m.get("pass_name"),
                "confidence": m.get("confidence"),
            })
        return json.dumps({"count": len(rows), "matches": rows}, indent=2, default=str)

    elif name == "get_findings":
        fpath = RESULTS_DIR / "checker_results.json"
        if not fpath.exists():
            return '{"error": "No checker results. Run checker first."}'
        with open(fpath) as f:
            data = json.load(f)
        findings = data.get("findings", [])
        compact = [{
            "severity": f.get("severity"),
            "check": f.get("check"),
            "vendor": f.get("vendor"),
            "section": f.get("form26_section", f.get("expected_section")),
            "amount": f.get("aggregate_amount", f.get("form26_amount")),
            "message": f.get("message"),
        } for f in findings]
        return json.dumps({"count": len(compact), "findings": compact}, indent=2, default=str)

    elif name == "submit_review_decision":
        from agents.learning_agent import apply_corrections
        decisions = [{
            "vendor": input_data["vendor"],
            "decision": input_data["decision"],
            "params": {"vendor_name": input_data["vendor"]},
            "reason": input_data.get("reason", ""),
        }]
        result = apply_corrections(str(BASE / "data" / "rules"), str(RESULTS_DIR), decisions)
        return json.dumps({"status": "applied", "decisions": 1}, indent=2)

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Conversation state
# ---------------------------------------------------------------------------

conversation_history = []


def chat(user_message: str) -> str:
    """Send a message to Claude and return the response, handling tool calls."""
    client = anthropic.Anthropic()

    conversation_history.append({"role": "user", "content": user_message})

    # Agentic loop — keep going until Claude gives a final text response
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=conversation_history,
        )

        # Collect the full response
        assistant_content = response.content
        conversation_history.append({"role": "assistant", "content": assistant_content})

        # Check if there are tool calls
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses:
            # No tool calls — extract text and return
            text_parts = [b.text for b in assistant_content if hasattr(b, "text")]
            return "\n".join(text_parts)

        # Execute tool calls and add results
        tool_results = []
        for tool_use in tool_uses:
            print(f"  [Tool] {tool_use.name}({json.dumps(tool_use.input)})")
            result = execute_tool(tool_use.name, tool_use.input)
            print(f"  [Result] {result[:200]}...")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        conversation_history.append({"role": "user", "content": tool_results})
        # Loop back — Claude will process tool results and either call more tools or respond


# ---------------------------------------------------------------------------
# Main loop — watch inbox, write outbox
# ---------------------------------------------------------------------------

def main():
    print("=" * 50)
    print("TDS RECON CHAT BRIDGE")
    print("=" * 50)
    print(f"Watching: {INBOX}")
    print(f"Writing:  {OUTBOX}")
    print("Waiting for messages...\n")

    last_processed_id = None

    while True:
        try:
            if INBOX.exists():
                with open(INBOX) as f:
                    msg = json.load(f)

                msg_id = msg.get("id")
                if msg_id and msg_id != last_processed_id:
                    user_text = msg.get("message", "")
                    print(f"\n[User] {user_text}")

                    # Write "processing" status
                    with open(OUTBOX, "w") as f:
                        json.dump({"id": msg_id, "status": "processing", "response": ""}, f)

                    # Get Claude's response
                    response = chat(user_text)
                    print(f"[Claude] {response[:200]}...")

                    # Write response
                    with open(OUTBOX, "w") as f:
                        json.dump({
                            "id": msg_id,
                            "status": "done",
                            "response": response,
                        }, f, indent=2, default=str)

                    last_processed_id = msg_id

        except json.JSONDecodeError:
            pass  # File being written
        except Exception as e:
            print(f"[Error] {e}")
            if INBOX.exists():
                try:
                    with open(INBOX) as f:
                        msg = json.load(f)
                    with open(OUTBOX, "w") as f:
                        json.dump({
                            "id": msg.get("id"),
                            "status": "error",
                            "response": f"Error: {str(e)}",
                        }, f)
                except:
                    pass

        time.sleep(0.5)  # Poll every 500ms


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY environment variable first:")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    main()
