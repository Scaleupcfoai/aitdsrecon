"""
Agentic Orchestrator — LLM-driven reconciliation with observe-think-act loop.

Unlike the old pipeline orchestrator (step1→step2→step3), this orchestrator
is a genuine agent: an LLM in a loop with tools. The LLM decides what to do
next based on what it observes. It can retry, change strategy, investigate
failures, and ask the user for help — just like a junior accountant would.

The pipeline code (parser, matcher, checker, reporter) becomes tools that
the orchestrator calls. The LLM controls the flow.

Pattern: identical to ChatAgent (chat_agent.py) — tool-use loop with Groq.

Usage:
    from app.pipeline.orchestrator import run_reconciliation
    result = run_reconciliation(
        company_id="abc", firm_id="def", financial_year="2024-25",
        form26_path="form26.xlsx", tally_path="tally.xlsx",
        db=repo, on_event=callback,
    )
"""

import json
import time
import traceback
from datetime import datetime

from groq import Groq

from app.config import settings
from app.db.repository import Repository
from app.pipeline.events import EventEmitter
from app.services.llm_client import LLMClient
from app.services.llm_prompts import ORCHESTRATOR_SYSTEM_PROMPT, ORCHESTRATOR_TOOLS
from app.knowledge import get_llm_context

from app.agents.parser_agent import ParserAgent
from app.agents.matcher_agent import MatcherAgent
from app.agents.tds_checker_agent import TdsCheckerAgent
from app.agents.reporter_agent import ReporterAgent
from app.agents.learning_agent import LearningAgent


# ═══════════════════════════════════════════════════════════
# Agentic Orchestrator — LLM in a tool-use loop
# ═══════════════════════════════════════════════════════════

class AgenticOrchestrator:
    """The brain of the reconciliation pipeline.

    This is NOT a script. It's an LLM agent that:
    1. Observes — reads tool results, entry data, match statistics
    2. Thinks — reasons about whether results make sense
    3. Acts — calls tools (parse, match, check, report, inspect, ask user)
    4. Loops — until the reconciliation is done or needs human help

    The LLM decides the control flow at runtime, not the developer at compile time.
    """

    MAX_LOOPS = 20  # Safety: prevent runaway

    def __init__(
        self,
        company_id: str,
        firm_id: str,
        financial_year: str,
        form26_path: str,
        tally_path: str,
        db: Repository,
        events: EventEmitter,
        llm: LLMClient,
        run_id: str,
        column_mappings: dict | None = None,
    ):
        self.company_id = company_id
        self.firm_id = firm_id
        self.financial_year = financial_year
        self.form26_path = form26_path
        self.tally_path = tally_path
        self.db = db
        self.events = events
        self.llm = llm
        self.run_id = run_id
        self.column_mappings = column_mappings

        # Shared context for sub-agents (parser, matcher, etc.)
        self._ctx = {
            "run_id": run_id,
            "company_id": company_id,
            "firm_id": firm_id,
            "financial_year": financial_year,
            "db": db,
            "events": events,
            "llm": llm,
        }

        # State — the LLM sees this in every prompt
        self._state = {
            "step": "not_started",
            "parse_result": None,
            "match_result": None,
            "checker_result": None,
            "report_result": None,
            "errors": [],
            "retry_count": 0,
        }

        # Groq client for orchestrator's own reasoning
        self._client = None
        if settings.groq_api_key:
            self._client = Groq(api_key=settings.groq_api_key)

        # Kept across calls for retry/inspection
        self._matcher = None
        self._raw_matches = []

    def run(self) -> dict:
        """Run the agentic orchestrator loop.

        If LLM is available: full agentic loop (LLM decides what to do).
        If LLM is unavailable: fallback to deterministic pipeline.
        """
        start = time.time()

        if not self._client:
            self.events.warning("Orchestrator", "LLM not available — running deterministic pipeline")
            return self._fallback_pipeline(start)

        self.events.emit("Orchestrator", "Starting agentic reconciliation...", "agent_start")
        self.events.emit(
            "Orchestrator",
            "I'll parse the files, match entries, check compliance, and generate reports. "
            "I'll investigate if anything looks wrong.",
            "llm_insight",
        )

        # The agentic loop — LLM in control
        conversation = []

        for loop_idx in range(self.MAX_LOOPS):
            try:
                response = self._client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": self._build_system_prompt()},
                        *conversation,
                    ],
                    tools=ORCHESTRATOR_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2000,
                )

                choice = response.choices[0]
                message_obj = choice.message

                if message_obj.tool_calls:
                    # LLM wants to use tools — execute them
                    conversation.append({
                        "role": "assistant",
                        "content": message_obj.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in message_obj.tool_calls
                        ],
                    })

                    # Show the LLM's reasoning to the user (if it said something)
                    if message_obj.content and message_obj.content.strip():
                        self.events.emit("Orchestrator", message_obj.content, "llm_insight")

                    for tool_call in message_obj.tool_calls:
                        tool_name = tool_call.function.name
                        raw_args = tool_call.function.arguments
                        tool_args = json.loads(raw_args) if raw_args else {}

                        tool_result = self._execute_tool(tool_name, tool_args)

                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(tool_result, default=str),
                        })

                    continue  # Loop back — LLM will observe tool results

                else:
                    # No tool calls — LLM is done
                    final_message = message_obj.content or "Reconciliation complete."
                    self.events.emit("Orchestrator", final_message, "llm_insight")
                    break

            except Exception as e:
                error_msg = f"Orchestrator loop error: {str(e)}"
                self.events.error("Orchestrator", error_msg)
                self._state["errors"].append({"loop": loop_idx, "error": error_msg})

                # Rate limit → fall back to deterministic pipeline
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    self.events.warning(
                        "Orchestrator",
                        "Rate limited — switching to deterministic pipeline",
                    )
                    time.sleep(3)
                    return self._fallback_pipeline(start)

                break

        elapsed = time.time() - start
        summary = self._state.get("report_result") or self._state.get("match_result") or {}
        errors = self._state.get("errors", [])
        final_status = "completed" if not errors else "review"
        self.db.runs.update_status(self.run_id, final_status, processing_status="done")

        if errors:
            self.events.warning("Orchestrator", f"Completed with {len(errors)} issue(s) in {elapsed:.1f}s")
        else:
            self.events.emit("Orchestrator", f"Complete in {elapsed:.1f}s", "success")

        self.events.agent_done("Orchestrator", "Done")

        return {
            "run_id": self.run_id,
            "events": self.events.get_events(),
            "summary": summary,
            "elapsed_s": round(elapsed, 2),
            "errors": errors,
        }

    # ═══════════════════════════════════════════════════════════
    # System Prompt — the orchestrator's knowledge and workflow
    # ═══════════════════════════════════════════════════════════

    def _build_system_prompt(self) -> str:
        """Build the system prompt with knowledge, workflow, and current state."""
        knowledge = get_llm_context()
        state_json = json.dumps(self._state, default=str, indent=2)

        return ORCHESTRATOR_SYSTEM_PROMPT.format(
            knowledge=knowledge,
            state=state_json,
            run_id=self.run_id,
            company_id=self.company_id,
            financial_year=self.financial_year,
        )

    # ═══════════════════════════════════════════════════════════
    # Tool Execution — the orchestrator's hands
    # ═══════════════════════════════════════════════════════════

    def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return the result. Updates internal state."""
        self.events.detail("Orchestrator", f"→ {tool_name}")

        try:
            handler = {
                "parse_files": self._tool_parse_files,
                "run_matcher": self._tool_run_matcher,
                "inspect_data": self._tool_inspect_data,
                "check_compliance": self._tool_check_compliance,
                "generate_report": self._tool_generate_report,
                "ask_user": self._tool_ask_user,
                "apply_learned_rules": self._tool_apply_learned_rules,
            }.get(tool_name)

            if not handler:
                return {"error": f"Unknown tool: {tool_name}"}

            return handler(args)

        except Exception as e:
            error = f"{tool_name} failed: {str(e)}"
            self.events.error("Orchestrator", error)
            self._state["errors"].append({
                "tool": tool_name,
                "error": error,
                "traceback": traceback.format_exc(),
            })
            return {"error": error}

    # ─── Tool: Parse Files ───────────────────────────────────

    def _tool_parse_files(self, args: dict) -> dict:
        """Parse Form 26 and Tally files into database entries."""
        self.db.runs.update_status(self.run_id, "processing", processing_status="parsing")

        parser = ParserAgent(**self._ctx)
        result = parser.run(self.form26_path, self.tally_path)

        self._state["step"] = "parsed"
        self._state["parse_result"] = result

        tds_count = result.get("tds_count", 0)
        ledger_count = result.get("ledger_count", 0)

        return {
            "status": "success",
            "tds_entries_parsed": tds_count,
            "ledger_entries_parsed": ledger_count,
            "company_detected": result.get("company_name", "unknown"),
            "sections_found": result.get("sections", []),
        }

    # ─── Tool: Run Matcher ───────────────────────────────────

    def _tool_run_matcher(self, args: dict) -> dict:
        """Run the 6-pass matching engine."""
        self.db.runs.update_status(self.run_id, "processing", processing_status="matching")

        self._matcher = MatcherAgent(**self._ctx)
        result = self._matcher.run()

        self._raw_matches = getattr(self._matcher, '_last_matches', [])
        self._state["step"] = "matched"
        self._state["match_result"] = result
        self._state["retry_count"] = self._state.get("retry_count", 0)

        total = result.get("total_form26", 0)
        matched = result.get("matched", 0)
        unmatched = result.get("unmatched", 0)
        match_rate = round((matched / total * 100) if total > 0 else 0, 1)

        return {
            "status": "success",
            "total_form26": total,
            "matched": matched,
            "unmatched": unmatched,
            "match_rate_pct": match_rate,
            "below_threshold": result.get("below_threshold", 0),
            "by_pass": result.get("by_pass", {}),
        }

    # ─── Tool: Inspect Data ──────────────────────────────────

    def _tool_inspect_data(self, args: dict) -> dict:
        """Inspect actual entry data — the orchestrator's eyes.

        This is how the LLM looks at the raw data to diagnose problems,
        just like an accountant pulling up both files to compare.

        Args (from LLM):
            source: 'form26' | 'tally' | 'both'
            sample_size: number of entries to return (default 5)
            focus: 'amounts' | 'names' | 'dates' | 'all'
        """
        source = args.get("source", "both")
        sample_size = min(args.get("sample_size", 5), 10)
        focus = args.get("focus", "all")

        result = {}

        if source in ("form26", "both"):
            tds_entries = self.db.entries.get_tds_by_run(self.run_id)
            result["form26_total_count"] = len(tds_entries)
            f26_data = []
            for e in tds_entries[:sample_size]:
                entry = {"party_name": e.party_name, "section": e.tds_section}
                if focus in ("amounts", "all"):
                    entry["gross_amount"] = float(e.gross_amount or 0)
                    entry["tds_amount"] = float(e.tds_amount or 0)
                if focus in ("dates", "all"):
                    entry["date"] = e.date_of_deduction
                if focus in ("names", "all"):
                    entry["pan"] = e.pan
                f26_data.append(entry)
            result["form26_entries"] = f26_data

        if source in ("tally", "both"):
            ledger_entries = self.db.entries.get_ledger_by_run(self.run_id)
            result["tally_total_count"] = len(ledger_entries)
            tally_data = []
            for e in ledger_entries[:sample_size]:
                entry = {"party_name": e.party_name, "expense_type": e.expense_type}
                if focus in ("amounts", "all"):
                    entry["amount"] = float(e.amount)
                    entry["gst_amount"] = float(e.gst_amount or 0)
                if focus in ("dates", "all"):
                    entry["invoice_date"] = e.invoice_date
                if focus in ("names", "all"):
                    entry["invoice_number"] = e.invoice_number
                tally_data.append(entry)
            result["tally_entries"] = tally_data

        return result

    # ─── Tool: Check Compliance ──────────────────────────────

    def _tool_check_compliance(self, args: dict) -> dict:
        """Run TDS compliance checks on matched entries."""
        self.db.runs.update_status(self.run_id, "processing", processing_status="checking")

        checker = TdsCheckerAgent(**self._ctx)

        tds_entries = self.db.entries.get_tds_by_run(self.run_id)
        ledger_entries = self.db.entries.get_ledger_by_run(self.run_id)

        form26_for_checker = [{
            "vendor_name": e.party_name, "section": e.tds_section,
            "amount_paid": float(e.gross_amount or 0), "pan": e.pan or "",
        } for e in tds_entries]

        tally_for_checker = [{
            "party_name": e.party_name, "amount": float(e.amount),
            "date": e.invoice_date or "", "voucher_no": e.invoice_number or "",
            "expense_type": e.expense_type,
            "raw_data": e.raw_data if isinstance(e.raw_data, dict) else {},
        } for e in ledger_entries]

        result = checker.run(
            matches=self._raw_matches,
            form26_entries=form26_for_checker,
            tally_entries=tally_for_checker,
        )

        self._state["step"] = "checked"
        self._state["checker_result"] = result

        findings = result.get("findings", [])
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")

        return {
            "status": "success",
            "total_findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "exposure": result.get("summary", {}).get("exposure", 0),
            "sample_findings": [
                {
                    "check": f.get("check"),
                    "severity": f.get("severity"),
                    "vendor": f.get("vendor"),
                    "message": f.get("message", "")[:150],
                }
                for f in findings[:5]
            ],
        }

    # ─── Tool: Generate Report ───────────────────────────────

    def _tool_generate_report(self, args: dict) -> dict:
        """Generate reconciliation reports (JSON, CSV, Excel)."""
        self.db.runs.update_status(self.run_id, "processing", processing_status="reporting")

        reporter = ReporterAgent(**self._ctx)
        summary = reporter.run(
            match_summary=self._state.get("match_result") or {},
            checker_summary=self._state.get("checker_result") or {},
            matches=self._raw_matches,
            findings=self._state.get("checker_result", {}).get("findings", []),
            output_dir="data/reports",
        )

        self._state["step"] = "reported"
        self._state["report_result"] = summary

        return {
            "status": "success",
            "match_rate_pct": summary.get("matching", {}).get("match_rate_pct", 0),
            "total_resolved": summary.get("matching", {}).get("total_resolved", 0),
            "reports_generated": [
                "reconciliation_summary.json",
                "reconciliation_report.csv",
                "findings_report.csv",
                "tds_recon_report.xlsx",
            ],
        }

    # ─── Tool: Ask User ─────────────────────────────────────

    def _tool_ask_user(self, args: dict) -> dict:
        """Ask the user a question and wait for their response.

        The LLM decides WHEN and WHAT to ask — not hardcoded.
        """
        import uuid

        question = args.get("question", "How should I proceed?")
        options = args.get("options", [])
        q_id = f"q_{uuid.uuid4().hex[:8]}"

        formatted_options = [
            {
                "id": opt.get("id", f"opt_{i}"),
                "label": opt.get("label", opt.get("id", "")),
                "description": opt.get("description", ""),
            }
            for i, opt in enumerate(options)
        ]

        answer = self.events.question(
            agent="Orchestrator",
            message=question,
            question_id=q_id,
            options=formatted_options,
            allow_text_input=args.get("allow_text", True),
            multi_select=False,
        )

        if answer:
            return {
                "status": "answered",
                "selected": answer.get("selected", []),
                "text_input": answer.get("text_input"),
            }
        return {"status": "timeout", "note": "User did not respond within 60 seconds."}

    # ─── Tool: Apply Learned Rules ───────────────────────────

    def _tool_apply_learned_rules(self, args: dict) -> dict:
        """Apply previously learned rules (Pass 0) before matching."""
        learning = LearningAgent(**self._ctx)
        result = learning.apply_learned_rules([], [])
        applied = result.get("applied_count", 0)
        return {
            "status": "success",
            "rules_applied": applied,
        }

    # ═══════════════════════════════════════════════════════════
    # Fallback: deterministic pipeline (when LLM unavailable)
    # ═══════════════════════════════════════════════════════════

    def _fallback_pipeline(self, start: float) -> dict:
        """Run the old-style deterministic pipeline as fallback."""
        errors = []

        try:
            self._tool_parse_files({})
        except Exception as e:
            errors.append({"agent": "Parser", "error": str(e)})
            return self._build_fallback_result(start, errors)

        try:
            self._tool_run_matcher({})
        except Exception as e:
            errors.append({"agent": "Matcher", "error": str(e)})

        try:
            self._tool_check_compliance({})
        except Exception as e:
            errors.append({"agent": "Checker", "error": str(e)})

        try:
            self._tool_generate_report({})
        except Exception as e:
            errors.append({"agent": "Reporter", "error": str(e)})

        return self._build_fallback_result(start, errors)

    def _build_fallback_result(self, start: float, errors: list) -> dict:
        elapsed = time.time() - start
        summary = self._state.get("report_result") or {}
        final_status = "completed" if not errors else "review"
        self.db.runs.update_status(self.run_id, final_status, processing_status="done")

        return {
            "run_id": self.run_id,
            "events": self.events.get_events(),
            "summary": summary,
            "elapsed_s": round(elapsed, 2),
            "errors": errors,
        }


# ═══════════════════════════════════════════════════════════
# Public API — same interface as before (drop-in replacement)
# ═══════════════════════════════════════════════════════════

def run_reconciliation(
    company_id: str,
    firm_id: str,
    financial_year: str,
    form26_path: str,
    tally_path: str,
    db: Repository,
    on_event=None,
    output_dir: str = "data/reports",
    column_mappings: dict | None = None,
) -> dict:
    """Run the full TDS reconciliation with the agentic orchestrator.

    Same interface as the old pipeline — drop-in replacement.
    """
    run = db.runs.create(company_id, financial_year)
    run_id = run.id

    events = EventEmitter(run_id=run_id, callback=on_event)
    llm = LLMClient(events=events)

    events.emit("Pipeline", f"Starting reconciliation (run: {run_id[:8]}...)", "info")

    orchestrator = AgenticOrchestrator(
        company_id=company_id,
        firm_id=firm_id,
        financial_year=financial_year,
        form26_path=form26_path,
        tally_path=tally_path,
        db=db,
        events=events,
        llm=llm,
        run_id=run_id,
        column_mappings=column_mappings,
    )

    return orchestrator.run()
