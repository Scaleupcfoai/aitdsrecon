"""
Chat Agent — 100% LLM brain with tools to query data and trigger agents.

This is what the user talks to. It:
- Answers tax questions using the verified knowledge base
- Runs the reconciliation pipeline when asked
- Queries match results and explains them in plain language
- Queries compliance findings and recommends actions
- Submits review decisions on behalf of the user
- Shows its reasoning step by step (like Claude Code)

The agentic loop: user message → LLM decides what to do → calls tools if needed
→ feeds tool results back to LLM → LLM responds to user.

Usage:
    from app.agents.chat_agent import ChatAgent
    agent = ChatAgent(db=repo, llm=llm, firm_id="abc", company_id="def")
    response = agent.chat("Why is Anderson flagged?")
    # or streaming:
    for chunk in agent.chat_stream("Run reconciliation"):
        print(chunk)
"""

import json
from typing import Generator

from app.config import settings
from app.db.repository import Repository
from app.services.llm_prompts import CHAT_SYSTEM_PROMPT, CHAT_TOOLS
from app.knowledge import get_llm_context
from app.pipeline.events import EventEmitter


class ChatAgent:
    """The user-facing AI agent. 100% LLM with tools.

    Does NOT extend AgentBase — it has its own lifecycle (not part of pipeline).
    """

    def __init__(
        self,
        db: Repository,
        firm_id: str,
        company_id: str,
        events: EventEmitter | None = None,
        run_id: str | None = None,
    ):
        self.db = db
        self.firm_id = firm_id
        self.company_id = company_id
        self.events = events or EventEmitter(run_id="chat")
        self.run_id = run_id  # most recent reconciliation run
        self.conversation_history = []
        self._client = None
        self._provider = None

        # Try Gemini first, fall back to Groq
        if settings.gemini_api_key:
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
            self._provider = "gemini"
        elif settings.groq_api_key:
            from groq import Groq
            self._client = Groq(api_key=settings.groq_api_key)
            self._provider = "groq"

    @property
    def available(self) -> bool:
        return self._client is not None

    def _build_system_prompt(self) -> str:
        """Build system prompt with knowledge base injected."""
        knowledge = get_llm_context()
        has_run = bool(self.run_id)
        return (
            f"{CHAT_SYSTEM_PROMPT}\n\n"
            f"IMPORTANT: Use ONLY the following verified TDS rules. "
            f"Do NOT use your training data for rates, thresholds, or penalties.\n\n"
            f"{knowledge}\n\n"
            f"Current context:\n"
            f"- Firm ID: {self.firm_id}\n"
            f"- Company ID: {self.company_id}\n"
            f"- Latest run ID: {self.run_id or 'No run yet'}\n\n"
            f"TOOL USAGE RULES:\n"
            f"- Call ONE tool at a time. Wait for its result before deciding next step.\n"
            f"- {'Reconciliation data IS available. You can query results, findings, and matches.' if has_run else 'No reconciliation has been run yet. Do NOT call get_results_summary, get_match_details, get_findings, or explain_finding — they will fail. Instead, tell the user to run reconciliation first.'}\n"
            f"- If the user asks a general TDS question, answer directly from the knowledge base — no tools needed.\n"
            f"- Only call run_reconciliation if the user explicitly asks to run/start the pipeline.\n"
        )

    def chat(self, message: str) -> str:
        """Send a message and get a complete response (non-streaming).

        Handles the agentic loop: LLM may call tools, we execute them,
        feed results back, until LLM gives a final text response.
        """
        if not self._client:
            return "Chat is not available. Please configure the LLM API key."

        self.conversation_history.append({"role": "user", "content": message})
        self.events.emit("Chat Agent", f"User: {message[:80]}...", "info")

        if self._provider == "gemini":
            return self._chat_gemini()
        else:
            return self._chat_groq()

    def _chat_gemini(self) -> str:
        """Gemini chat — simple prompt-response (no tool calling for now)."""
        from google.genai import types

        # Build full prompt with conversation context
        conv_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in self.conversation_history if m.get("content")
        )

        config = types.GenerateContentConfig(
            system_instruction=self._build_system_prompt(),
            temperature=0.2,
            max_output_tokens=2000,
        )

        response = self._client.models.generate_content(
            model=settings.llm_model,
            contents=conv_text,
            config=config,
        )

        final_text = response.text or ""
        self.conversation_history.append({"role": "assistant", "content": final_text})
        self.events.emit("Chat Agent", f"Response: {final_text[:100]}...", "info")
        return final_text

    def _chat_groq(self) -> str:
        """Groq chat with tool-use loop (legacy)."""
        from groq import Groq

        while True:
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    *self.conversation_history,
                ],
                tools=CHAT_TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=2000,
            )

            choice = response.choices[0]
            message_obj = choice.message

            if message_obj.tool_calls:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": message_obj.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in message_obj.tool_calls
                    ],
                })

                for tool_call in message_obj.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                    self.events.emit("Chat Agent", f"Calling tool: {tool_name}", "llm_call",
                                     {"tool": tool_name, "args": tool_args})
                    tool_result = self._execute_tool(tool_name, tool_args)
                    self.events.emit("Chat Agent", f"Tool result: {str(tool_result)[:100]}...", "llm_response")

                    self.conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result, default=str),
                    })
                continue

            final_text = message_obj.content or ""
            self.conversation_history.append({"role": "assistant", "content": final_text})
            self.events.emit("Chat Agent", f"Response: {final_text[:100]}...", "info")
            return final_text

    def chat_stream(self, message: str) -> Generator[str, None, None]:
        """Send a message and stream the response token by token."""
        if not self._client:
            yield "Chat is not available. Please configure the LLM API key."
            return

        self.conversation_history.append({"role": "user", "content": message})

        if self._provider == "gemini":
            # Gemini: simple prompt-response, yield in chunks
            from google.genai import types

            conv_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in self.conversation_history if m.get("content")
            )

            config = types.GenerateContentConfig(
                system_instruction=self._build_system_prompt(),
                temperature=0.2,
                max_output_tokens=2000,
            )

            response = self._client.models.generate_content(
                model=settings.llm_model,
                contents=conv_text,
                config=config,
            )

            final_text = response.text or ""
            self.conversation_history.append({"role": "assistant", "content": final_text})

            # Yield in chunks
            words = final_text.split(" ")
            chunk = ""
            for word in words:
                chunk += word + " "
                if len(chunk) > 30:
                    yield chunk
                    chunk = ""
            if chunk:
                yield chunk
            return

        # Groq: tool-use loop (legacy)
        max_loops = 3
        for loop_idx in range(max_loops):
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    *self.conversation_history,
                ],
                tools=CHAT_TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=2000,
            )

            choice = response.choices[0]
            message_obj = choice.message

            if not message_obj.tool_calls:
                final_text = message_obj.content or ""
                self.conversation_history.append({"role": "assistant", "content": final_text})
                words = final_text.split(" ")
                chunk = ""
                for word in words:
                    chunk += word + " "
                    if len(chunk) > 30:
                        yield chunk
                        chunk = ""
                if chunk:
                    yield chunk
                return

            self.conversation_history.append({
                "role": "assistant",
                "content": message_obj.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in message_obj.tool_calls
                ],
            })

            for tool_call in message_obj.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                yield f"\n🔧 *{tool_name}*...\n"
                tool_result = self._execute_tool(tool_name, tool_args)
                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, default=str),
                })

        yield "\n(Max tool calls reached)"

    def _execute_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return the result."""

        if tool_name == "run_reconciliation":
            return self._tool_run_reconciliation()

        elif tool_name == "get_results_summary":
            return self._tool_get_results_summary()

        elif tool_name == "get_match_details":
            return self._tool_get_match_details(args.get("section"))

        elif tool_name == "get_findings":
            return self._tool_get_findings()

        elif tool_name == "submit_review_decision":
            return self._tool_submit_review(
                args.get("vendor", ""),
                args.get("decision", ""),
                args.get("reason", ""),
            )

        elif tool_name == "explain_finding":
            return self._tool_explain_finding(args.get("vendor", ""))

        return {"error": f"Unknown tool: {tool_name}"}

    # ═══ Tool implementations ═══

    def _tool_run_reconciliation(self) -> dict:
        """Trigger the full reconciliation pipeline."""
        # This will be wired to the orchestrator in Day 8
        return {
            "status": "pipeline_not_wired_yet",
            "message": "Pipeline execution will be available after orchestrator integration (Day 8).",
        }

    def _tool_get_results_summary(self) -> dict:
        """Get the reconciliation summary from DB."""
        if not self.run_id:
            return {"error": "No reconciliation run found. Run the pipeline first."}

        summaries = self.db.summaries.get_by_run(self.run_id)
        if not summaries:
            return {"error": "No summary found for this run."}

        # Find the executive summary
        for s in summaries:
            if s.group_key == "executive_summary":
                return {
                    "summary": s.llm_summary,
                    "entry_count": s.entry_count,
                    "total_amount": s.total_amount,
                    "status": s.status,
                }

        return {"summaries": [{"section": s.section, "group_key": s.group_key,
                               "entry_count": s.entry_count} for s in summaries]}

    def _tool_get_match_details(self, section: str | None = None) -> dict:
        """Get match results from DB."""
        if not self.run_id:
            return {"error": "No reconciliation run found."}

        matches = self.db.matches.get_by_run(self.run_id)
        if section:
            # Filter by section (check tds_entry)
            filtered = []
            for m in matches:
                if m.tds_entry_id:
                    tds_entries = self.db.entries.get_tds_by_run(self.run_id)
                    tds_map = {e.id: e for e in tds_entries}
                    tds = tds_map.get(m.tds_entry_id)
                    if tds and tds.tds_section == section:
                        filtered.append(m)
            matches = filtered

        return {
            "count": len(matches),
            "matches": [
                {
                    "match_type": m.match_type,
                    "confidence": m.confidence,
                    "amount": m.amount,
                    "status": m.status,
                }
                for m in matches[:20]  # limit to 20 for context window
            ],
        }

    def _tool_get_findings(self) -> dict:
        """Get compliance findings from DB."""
        if not self.run_id:
            return {"error": "No reconciliation run found."}

        # Read discrepancy_action table
        # For now, get all match results with pending_review status
        matches = self.db.matches.get_by_run(self.run_id)
        pending = [m for m in matches if m.status == "pending_review"]

        # Also get discrepancy actions
        findings = []
        for m in matches:
            actions = self.db.discrepancies.get_by_match(m.id)
            for a in actions:
                findings.append({
                    "stage": a.stage,
                    "action_status": a.action_status,
                    "llm_reasoning": a.llm_reasoning,
                    "proposed_action": a.proposed_action,
                })

        return {
            "total_findings": len(findings),
            "pending_review": len(pending),
            "findings": findings[:10],  # limit for context
        }

    def _tool_submit_review(self, vendor: str, decision: str, reason: str) -> dict:
        """Submit a review decision via Learning Agent."""
        from app.agents.learning_agent import LearningAgent
        from app.services.llm_client import LLMClient

        llm = LLMClient(events=self.events)
        learning = LearningAgent(
            run_id=self.run_id or "",
            company_id=self.company_id,
            firm_id=self.firm_id,
            financial_year="2024-25",  # TODO: get from run
            db=self.db,
            events=self.events,
            llm=llm,
        )

        result = learning.record_decision(
            vendor=vendor,
            decision_type=decision,
            params={"vendor_name": vendor},
            reason=reason,
        )

        return {
            "status": "recorded",
            "vendor": vendor,
            "decision": decision,
            "feedback_id": result.get("feedback_id"),
            "pattern_extracted": result.get("pattern_id") is not None,
        }

    def _tool_explain_finding(self, vendor: str) -> dict:
        """Explain a specific finding for a vendor."""
        if not self.run_id:
            return {"error": "No reconciliation run found."}

        # Search for matches involving this vendor
        matches = self.db.matches.get_by_run(self.run_id)
        tds_entries = self.db.entries.get_tds_by_run(self.run_id)
        tds_map = {e.id: e for e in tds_entries}

        vendor_matches = []
        for m in matches:
            tds = tds_map.get(m.tds_entry_id)
            if tds and vendor.lower() in (tds.party_name or "").lower():
                actions = self.db.discrepancies.get_by_match(m.id)
                vendor_matches.append({
                    "vendor": tds.party_name,
                    "section": tds.tds_section,
                    "amount": float(tds.gross_amount or 0),
                    "tds": float(tds.tds_amount or 0),
                    "match_type": m.match_type,
                    "confidence": m.confidence,
                    "status": m.status,
                    "findings": [
                        {"stage": a.stage, "reasoning": a.llm_reasoning,
                         "action": a.proposed_action}
                        for a in actions
                    ],
                })

        if not vendor_matches:
            return {"error": f"No data found for vendor '{vendor}'."}

        return {"vendor": vendor, "details": vendor_matches}

    def reset_history(self):
        """Clear conversation history."""
        self.conversation_history = []
