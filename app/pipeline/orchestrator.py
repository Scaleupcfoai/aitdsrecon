"""
State Machine Orchestrator — LLM-powered decision making at quality gates.

Replaces the linear pipeline with a state machine:
- Each step runs a tool (deterministic Python code)
- After each step, quality gates check the output
- Deterministic gates catch obvious data issues (nulls, zeros, empty)
- LLM gates evaluate whether results are reasonable
- Human gates pause for user input when needed
- The orchestrator decides what to do at each gate: proceed, retry, escalate

States:
    INIT → PARSING → PARSED_REVIEW → MATCHING → MATCH_REVIEW →
    CHECKING → CHECK_REVIEW → REPORTING → COMPLETE

At each _REVIEW state, the orchestrator:
1. Runs deterministic quality checks (fast, free)
2. If checks pass → asks LLM "is this reasonable?" (cheap with Gemini Flash)
3. If LLM flags issues → investigates with inspect_data
4. Based on findings → proceed, retry, or ask human

Usage:
    from app.pipeline.orchestrator import run_reconciliation
    result = run_reconciliation(
        company_id="abc-123", firm_id="def-456", financial_year="2024-25",
        form26_path="form26.xlsx", tally_path="tally.xlsx",
        db=repo, on_event=callback,
    )
"""

import json
import time
import traceback
import uuid

from app.db.repository import Repository
from app.pipeline.events import EventEmitter
from app.services.llm_client import LLMClient
from app.agents.parser_agent import ParserAgent
from app.agents.matcher_agent import MatcherAgent
from app.agents.tds_checker_agent import TdsCheckerAgent
from app.agents.reporter_agent import ReporterAgent
from app.agents.learning_agent import LearningAgent
from app.knowledge import get_llm_context


# ═══════════════════════════════════════════════════════════
# Workflow State — explicit, typed, persisted
# ═══════════════════════════════════════════════════════════

class WorkflowState:
    """Explicit state object that flows through the state machine.

    Every piece of data the orchestrator needs to make decisions
    lives here — not in conversation history, not in global variables.
    """

    def __init__(self, run_id: str, company_id: str, firm_id: str, financial_year: str):
        self.run_id = run_id
        self.company_id = company_id
        self.firm_id = firm_id
        self.financial_year = financial_year

        # Current position in state machine
        self.current_state = "INIT"

        # Tool outputs (populated as pipeline progresses)
        self.column_mappings = None       # from column mapper
        self.parse_result = None          # from parser
        self.match_result = None          # from matcher
        self.checker_result = None        # from checker
        self.report_result = None         # from reporter

        # Quality gate findings
        self.quality_issues = []          # [{gate, severity, message}]

        # LLM diagnosis (when quality gate flags something)
        self.diagnosis = None             # LLM's analysis of what's wrong

        # Raw data references (for LLM inspection)
        self.raw_matches = []             # matcher's raw match list

        # Errors
        self.errors = []

    def to_summary(self) -> str:
        """Compact summary for LLM context — what's happened so far."""
        lines = [f"State: {self.current_state}"]
        if self.parse_result:
            lines.append(f"Parsed: {self.parse_result.get('tds_count', 0)} TDS + {self.parse_result.get('ledger_count', 0)} ledger entries")
        if self.match_result:
            total = self.match_result.get("total_form26", 0)
            matched = self.match_result.get("matched", 0)
            lines.append(f"Matched: {matched}/{total} ({round(matched/total*100) if total else 0}%)")
        if self.checker_result:
            findings = self.checker_result.get("findings", [])
            errors = sum(1 for f in findings if f.get("severity") == "error")
            lines.append(f"Findings: {len(findings)} total, {errors} errors")
        if self.quality_issues:
            lines.append(f"Quality issues: {len(self.quality_issues)}")
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
        return " | ".join(lines)


# ═══════════════════════════════════════════════════════════
# State Machine Orchestrator
# ═══════════════════════════════════════════════════════════

class StateMachineOrchestrator:
    """Orchestrator that runs tools in sequence with quality gates.

    Unlike the old linear pipeline, this orchestrator:
    - Checks output quality after each step
    - Uses LLM to evaluate results at decision points
    - Can stop and ask the user for input
    - Can retry tools with different parameters
    - Streams its reasoning to the frontend via SSE
    """

    def __init__(
        self,
        company_id: str, firm_id: str, financial_year: str,
        form26_path: str, tally_path: str,
        db: Repository, events: EventEmitter, llm: LLMClient,
        run_id: str,
    ):
        self.form26_path = form26_path
        self.tally_path = tally_path
        self.db = db
        self.events = events
        self.llm = llm

        self.state = WorkflowState(run_id, company_id, firm_id, financial_year)

        # Shared context for tools
        self._ctx = {
            "run_id": run_id,
            "company_id": company_id,
            "firm_id": firm_id,
            "financial_year": financial_year,
            "db": db,
            "events": events,
            "llm": llm,
        }

    def run(self) -> dict:
        """Execute the state machine until COMPLETE or error."""
        start = time.time()

        self.events.emit("Orchestrator", "Starting reconciliation...", "agent_start")

        # State machine loop
        transitions = {
            "INIT":           self._step_init,
            "PARSING":        self._step_parse,
            "PARSED_REVIEW":  self._gate_parsed,
            "MATCHING":       self._step_match,
            "MATCH_REVIEW":   self._gate_matched,
            "CHECKING":       self._step_check,
            "CHECK_REVIEW":   self._gate_checked,
            "REPORTING":      self._step_report,
            "COMPLETE":       None,
            "FAILED":         None,
        }

        max_steps = 20  # Safety: prevent infinite loops
        for step_num in range(max_steps):
            current = self.state.current_state

            if current in ("COMPLETE", "FAILED"):
                break

            handler = transitions.get(current)
            if not handler:
                self.events.error("Orchestrator", f"Unknown state: {current}")
                self.state.current_state = "FAILED"
                break

            try:
                next_state = handler()
                self.state.current_state = next_state
                self.events.detail("Orchestrator", f"→ {next_state}")
            except Exception as e:
                error_msg = f"Error in {current}: {str(e)}"
                self.events.error("Orchestrator", error_msg)
                self.state.errors.append({"state": current, "error": error_msg,
                                          "traceback": traceback.format_exc()})
                self.state.current_state = "FAILED"

        # Finalize
        elapsed = time.time() - start
        final_status = "completed" if self.state.current_state == "COMPLETE" else "review"
        self.db.runs.update_status(self.state.run_id, final_status, processing_status="done")

        summary = self.state.report_result or self.state.match_result or {}

        if self.state.errors:
            self.events.warning("Orchestrator", f"Completed with {len(self.state.errors)} issue(s) in {elapsed:.1f}s")
        else:
            self.events.emit("Orchestrator", f"Complete in {elapsed:.1f}s", "success")

        self.events.agent_done("Orchestrator", "Done")

        return {
            "run_id": self.state.run_id,
            "events": self.events.get_events(),
            "summary": summary,
            "elapsed_s": round(elapsed, 2),
            "errors": self.state.errors,
        }

    # ─── State: INIT ─────────────────────────────────────────

    def _step_init(self) -> str:
        """Initialize: apply learned rules, validate files exist."""
        # Apply learned rules (Pass 0)
        try:
            learning = LearningAgent(**self._ctx)
            result = learning.apply_learned_rules([], [])
            if result.get("applied_count", 0) > 0:
                self.events.detail("Orchestrator", f"Applied {result['applied_count']} learned rules")
        except Exception as e:
            self.events.warning("Orchestrator", f"Could not load learned rules: {str(e)[:80]}")

        return "PARSING"

    # ─── State: PARSING ──────────────────────────────────────

    def _step_parse(self) -> str:
        """Run the parser tool on uploaded files."""
        self.db.runs.update_status(self.state.run_id, "processing", processing_status="parsing")

        parser = ParserAgent(**self._ctx)
        self.state.parse_result = parser.run(self.form26_path, self.tally_path)

        return "PARSED_REVIEW"

    # ─── Gate: PARSED_REVIEW ─────────────────────────────────

    def _gate_parsed(self) -> str:
        """Quality gate after parsing. Check data quality, ask LLM if suspicious."""
        result = self.state.parse_result
        if not result:
            self.state.errors.append({"gate": "parsed", "error": "Parser returned no result"})
            return "FAILED"

        tds_count = result.get("tds_count", 0)
        ledger_count = result.get("ledger_count", 0)

        # ── Deterministic checks (is the data valid?) ──

        if tds_count == 0:
            self.state.quality_issues.append({
                "gate": "parsed", "severity": "critical",
                "message": "0 TDS entries parsed — Form 26 file may be empty or column mapping failed"
            })
            self.events.error("Orchestrator", "0 TDS entries parsed — cannot proceed")
            return self._escalate_to_human("No Form 26 entries were extracted. The file may be empty or the columns couldn't be identified. Please check the file and column mappings.")

        if ledger_count == 0:
            self.state.quality_issues.append({
                "gate": "parsed", "severity": "critical",
                "message": "0 ledger entries parsed — Tally file may be empty or column mapping failed"
            })
            self.events.error("Orchestrator", "0 ledger entries parsed — cannot proceed")
            return self._escalate_to_human("No Tally entries were extracted. The file may be empty or the columns couldn't be identified.")

        # Check for null critical fields
        tds_entries = self.db.entries.get_tds_by_run(self.state.run_id)
        null_names = sum(1 for e in tds_entries if not e.party_name or e.party_name == "None")
        null_amounts = sum(1 for e in tds_entries if not e.gross_amount or float(e.gross_amount) == 0)
        null_dates = sum(1 for e in tds_entries if not e.date_of_deduction)

        if null_names > len(tds_entries) * 0.3:
            self.state.quality_issues.append({
                "gate": "parsed", "severity": "high",
                "message": f"{null_names}/{len(tds_entries)} TDS entries have missing party names"
            })

        if null_amounts > len(tds_entries) * 0.3:
            self.state.quality_issues.append({
                "gate": "parsed", "severity": "high",
                "message": f"{null_amounts}/{len(tds_entries)} TDS entries have zero/missing amounts"
            })

        # ── If deterministic checks found issues → LLM investigates ──

        if self.state.quality_issues:
            self.events.emit("Orchestrator", "Data quality issues detected — investigating...", "llm_insight")
            return self._llm_investigate_parse_quality()

        # ── No issues → LLM quick sanity check (cheap, fast) ──

        if self.llm.available:
            self.events.detail("Orchestrator", "Checking parsed data quality...")
            assessment = self.llm.complete(
                f"Parser extracted {tds_count} Form 26 entries and {ledger_count} Tally entries "
                f"for FY {self.state.financial_year}. "
                f"Null names: {null_names}/{tds_count}. Null amounts: {null_amounts}/{tds_count}. "
                f"Null dates: {null_dates}/{tds_count}. "
                f"Does this look reasonable? Reply in 1 sentence.",
                system="You are a CA reviewing data quality. Be concise.",
                agent_name="Orchestrator",
                include_knowledge=False,
            )
            if assessment:
                self.events.emit("Orchestrator", assessment, "llm_insight")

        return "MATCHING"

    def _llm_investigate_parse_quality(self) -> str:
        """LLM investigates WHY parsed data has quality issues."""
        # Get sample entries for LLM to inspect
        tds_entries = self.db.entries.get_tds_by_run(self.state.run_id)[:5]
        ledger_entries = self.db.entries.get_ledger_by_run(self.state.run_id)[:5]

        tds_sample = "\n".join(
            f"  name={e.party_name!r}, amount={e.gross_amount}, tds={e.tds_amount}, "
            f"date={e.date_of_deduction}, section={e.tds_section}"
            for e in tds_entries
        )
        ledger_sample = "\n".join(
            f"  name={e.party_name!r}, amount={e.amount}, gst={e.gst_amount}, "
            f"date={e.invoice_date}, type={e.expense_type}"
            for e in ledger_entries
        )

        issues_text = "\n".join(f"- {q['message']}" for q in self.state.quality_issues)

        if self.llm.available:
            diagnosis = self.llm.complete(
                f"The parser produced data with these quality issues:\n{issues_text}\n\n"
                f"Sample Form 26 entries:\n{tds_sample}\n\n"
                f"Sample Tally entries:\n{ledger_sample}\n\n"
                f"What is likely wrong? Is this a column mapping issue, file format issue, "
                f"or something else? What should the user check? Be specific and concise.",
                system="You are a CA reviewing parsed TDS data. Diagnose data quality issues.",
                agent_name="Orchestrator",
            )
            if diagnosis:
                self.state.diagnosis = diagnosis
                self.events.emit("Orchestrator", diagnosis, "llm_insight")

        # Escalate to human with LLM's diagnosis
        return self._escalate_to_human(
            f"Data quality issues found after parsing.\n\n"
            f"{self.state.diagnosis or issues_text}\n\n"
            f"Would you like to proceed with matching anyway, or re-check the column mappings?"
        )

    # ─── State: MATCHING ─────────────────────────────────────

    def _step_match(self) -> str:
        """Run the matcher tool."""
        self.db.runs.update_status(self.state.run_id, "processing", processing_status="matching")

        matcher = MatcherAgent(**self._ctx)
        self.state.match_result = matcher.run()
        self.state.raw_matches = getattr(matcher, '_last_matches', [])

        return "MATCH_REVIEW"

    # ─── Gate: MATCH_REVIEW ──────────────────────────────────

    def _gate_matched(self) -> str:
        """Quality gate after matching. LLM evaluates whether results make sense."""
        result = self.state.match_result
        if not result:
            return "CHECKING"  # Proceed with empty results

        total = result.get("total_form26", 0)
        matched = result.get("matched", 0)
        unmatched = result.get("unmatched", 0)
        match_rate = round((matched / total * 100) if total > 0 else 0, 1)

        self.events.detail("Orchestrator", f"Match result: {matched}/{total} ({match_rate}%)")

        # ── LLM evaluates: is this result reasonable? ──
        # No deterministic threshold — the LLM decides based on context

        if total > 0 and self.llm.available:
            # Get sample data for LLM to inspect
            tds_entries = self.db.entries.get_tds_by_run(self.state.run_id)[:5]
            ledger_entries = self.db.entries.get_ledger_by_run(self.state.run_id)[:5]

            tds_sample = json.dumps([
                {"name": e.party_name, "amount": float(e.gross_amount or 0),
                 "section": e.tds_section, "date": str(e.date_of_deduction)}
                for e in tds_entries
            ], indent=2)

            ledger_sample = json.dumps([
                {"name": e.party_name, "amount": float(e.amount or 0),
                 "gst": float(e.gst_amount or 0), "type": e.expense_type}
                for e in ledger_entries
            ], indent=2)

            by_pass = result.get("by_pass", {})

            self.events.emit("Orchestrator", "Evaluating match results...", "llm_insight")

            assessment = self.llm.complete_json(
                f"TDS Reconciliation match results:\n"
                f"- Total Form 26 entries: {total}\n"
                f"- Matched: {matched} ({match_rate}%)\n"
                f"- Unmatched: {unmatched}\n"
                f"- By pass: {json.dumps(by_pass)}\n\n"
                f"Sample unmatched Form 26 entries:\n{tds_sample}\n\n"
                f"Sample Tally entries:\n{ledger_sample}\n\n"
                f"As a CA, evaluate:\n"
                f"1. Is this match rate reasonable or does something look wrong?\n"
                f"2. If wrong, what pattern do you see in the sample data? (GST mismatch, name format, date issue?)\n"
                f"3. Should we proceed to compliance checks, retry with different params, or ask the user?\n\n"
                f"Respond in JSON: {{\"assessment\": \"healthy|suspicious|critical\", "
                f"\"reasoning\": \"...\", \"action\": \"proceed|investigate|ask_user\", "
                f"\"details\": \"...\"}}",
                system="You are a senior CA reviewing TDS reconciliation results. Be specific about what you see in the data.",
                agent_name="Orchestrator",
            )

            if assessment:
                action = assessment.get("action", "proceed")
                reasoning = assessment.get("reasoning", "")
                details = assessment.get("details", "")

                self.events.emit("Orchestrator", reasoning, "llm_insight")

                if action == "investigate":
                    self.events.emit("Orchestrator", f"Investigating: {details}", "llm_insight")
                    # LLM wants to look deeper — let it inspect more data
                    # For now, escalate to human with the investigation findings
                    return self._escalate_to_human(
                        f"Match results: {matched}/{total} ({match_rate}%)\n\n"
                        f"Assessment: {reasoning}\n\n{details}\n\n"
                        f"Should I proceed to compliance checks, or would you like to adjust something?"
                    )
                elif action == "ask_user":
                    return self._escalate_to_human(
                        f"Match results: {matched}/{total} ({match_rate}%)\n\n"
                        f"{reasoning}\n\n"
                        f"How would you like to proceed?"
                    )
                # action == "proceed" → fall through

        # If unmatched > 0, still ask user (existing behavior)
        if unmatched > 0:
            return self._escalate_to_human(
                f"{unmatched} entries could not be matched. How should I proceed?",
                options=[
                    {"id": "proceed", "label": "Proceed to compliance checks",
                     "description": "Continue with matched entries, flag unmatched for review"},
                    {"id": "flag_review", "label": "Flag all for manual review",
                     "description": "Stop here and review unmatched entries manually"},
                ]
            )

        return "CHECKING"

    # ─── State: CHECKING ─────────────────────────────────────

    def _step_check(self) -> str:
        """Run TDS compliance checks."""
        self.db.runs.update_status(self.state.run_id, "processing", processing_status="checking")

        checker = TdsCheckerAgent(**self._ctx)

        tds_entries = self.db.entries.get_tds_by_run(self.state.run_id)
        ledger_entries = self.db.entries.get_ledger_by_run(self.state.run_id)

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

        self.state.checker_result = checker.run(
            matches=self.state.raw_matches,
            form26_entries=form26_for_checker,
            tally_entries=tally_for_checker,
        )

        return "CHECK_REVIEW"

    # ─── Gate: CHECK_REVIEW ──────────────────────────────────

    def _gate_checked(self) -> str:
        """Quality gate after compliance checks."""
        result = self.state.checker_result
        if not result:
            return "REPORTING"

        findings = result.get("findings", [])
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")

        self.events.detail("Orchestrator", f"Compliance: {errors} errors, {warnings} warnings")

        # If high-severity findings, show them prominently
        if errors > 0:
            top_errors = [f for f in findings if f.get("severity") == "error"][:3]
            for f in top_errors:
                self.events.emit("Orchestrator",
                    f"⚠ {f.get('check', '?')}: {f.get('vendor', '?')} — {f.get('message', '')[:100]}",
                    "warning")

        return "REPORTING"

    # ─── State: REPORTING ────────────────────────────────────

    def _step_report(self) -> str:
        """Generate reports."""
        self.db.runs.update_status(self.state.run_id, "processing", processing_status="reporting")

        reporter = ReporterAgent(**self._ctx)
        self.state.report_result = reporter.run(
            match_summary=self.state.match_result or {},
            checker_summary=self.state.checker_result or {},
            matches=self.state.raw_matches,
            findings=self.state.checker_result.get("findings", []) if self.state.checker_result else [],
            output_dir="data/reports",
        )

        return "COMPLETE"

    # ─── Helper: Escalate to Human ───────────────────────────

    def _escalate_to_human(self, message: str, options: list[dict] | None = None) -> str:
        """Ask the user a question and wait for their response.

        Returns the NEXT state based on user's answer.
        """
        q_id = f"q_{uuid.uuid4().hex[:8]}"

        default_options = options or [
            {"id": "proceed", "label": "Proceed anyway",
             "description": "Continue to the next step"},
            {"id": "stop", "label": "Stop and review",
             "description": "Stop the pipeline here for manual review"},
        ]

        answer = self.events.question(
            agent="Orchestrator",
            message=message,
            question_id=q_id,
            options=default_options,
            allow_text_input=True,
            multi_select=False,
        )

        if answer:
            selected = answer.get("selected", [])
            text = answer.get("text_input", "")

            if "stop" in selected or "flag_review" in selected:
                self.events.detail("Orchestrator", "User requested stop for review")
                return "COMPLETE"  # End gracefully

            if text and self.llm.available:
                # User gave free-text feedback — let LLM interpret it
                self.events.detail("Orchestrator", f"User feedback: {text[:80]}...")

            self.events.detail("Orchestrator", "User confirmed — proceeding")
        else:
            self.events.warning("Orchestrator", "No user response — proceeding with defaults")

        # Determine next state based on current state
        proceed_map = {
            "PARSED_REVIEW": "MATCHING",
            "MATCH_REVIEW": "CHECKING",
            "CHECK_REVIEW": "REPORTING",
        }
        return proceed_map.get(self.state.current_state, "COMPLETE")


# ═══════════════════════════════════════════════════════════
# Public API — same interface as before
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
) -> dict:
    """Run the full TDS reconciliation with the state machine orchestrator.

    Same interface as the old pipeline — drop-in replacement.
    """
    run = db.runs.create(company_id, financial_year)
    run_id = run.id

    events = EventEmitter(run_id=run_id, callback=on_event)
    llm = LLMClient(events=events)

    events.emit("Pipeline", f"Starting reconciliation (run: {run_id[:8]}...)", "info")
    if llm.available:
        events.emit("Pipeline", f"LLM available ({llm._provider}) — will evaluate results at each step", "info")
    else:
        events.emit("Pipeline", "LLM not available — running with deterministic checks only", "warning")

    orchestrator = StateMachineOrchestrator(
        company_id=company_id, firm_id=firm_id,
        financial_year=financial_year,
        form26_path=form26_path, tally_path=tally_path,
        db=db, events=events, llm=llm, run_id=run_id,
    )

    return orchestrator.run()
