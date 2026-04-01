"""
Learning Agent — learns from human review decisions, extracts reusable patterns.

Flow:
1. Human makes a decision (below_threshold, ignore, exempt, section_override)
2. Decision stored in resolution_feedback table
3. LLM extracts a reusable pattern from the decision
4. Pattern stored in resolved_pattern table with pgvector embedding
5. On next run, similar patterns auto-applied (Pass 0 before Matcher)

Uses pgvector for similarity search — "this vendor looks like one we resolved before."

Usage:
    from app.agents.learning_agent import LearningAgent
    agent = LearningAgent(run_id, company_id, firm_id, fy, db, events, llm)
    agent.record_decision("Xpress Cargo", "below_threshold", {"section": "194C", "amount": 1500})
    similar = agent.find_similar_patterns({"vendor": "VRL Logistics", "section": "194C"})
    rules = agent.get_learned_rules()
"""

import json
import hashlib

from app.agents.base import AgentBase
from app.services.llm_prompts import LEARNING_PATTERN_SYSTEM, LEARNING_PATTERN_PROMPT


class LearningAgent(AgentBase):
    agent_name = "Learning Agent"

    def record_decision(self, vendor: str, decision_type: str,
                        params: dict | None = None, reason: str = "") -> dict:
        """Record a human review decision and extract a pattern.

        Args:
            vendor: Vendor name
            decision_type: below_threshold, ignore, exempt, section_override, manual_match
            params: Additional context (section, amount, threshold, etc.)
            reason: Human's stated reason

        Returns: {feedback_id, pattern_id (if extracted)}
        """
        self.events.agent_start(self.agent_name, f"Recording decision: {vendor} → {decision_type}")

        params = params or {}

        # Step 1: Store the decision in resolution_feedback
        feedback = self.db.feedback.create(
            feedback_type=decision_type,
            user_input=f"{vendor}: {decision_type}. {reason}",
            ca_firm_id=self.firm_id,
            llm_interpretation=None,
            rule_extracted=None,
            reuse_scope="this_firm",
        )
        self.events.detail(self.agent_name, f"Decision stored: {feedback.id[:8]}...")

        # Step 2: LLM extracts a reusable pattern
        pattern_id = None
        if self.llm and self.llm.available:
            pattern_id = self._extract_pattern(vendor, decision_type, params, reason)

        self.events.agent_done(self.agent_name, "Decision recorded")

        return {
            "feedback_id": feedback.id,
            "pattern_id": pattern_id,
        }

    def _extract_pattern(self, vendor: str, decision_type: str,
                         params: dict, reason: str) -> str | None:
        """Ask LLM to extract a reusable pattern from the decision."""
        prompt = LEARNING_PATTERN_PROMPT.format(
            vendor_name=vendor,
            decision_type=decision_type,
            section=params.get("section", "unknown"),
            amount=f"{params.get('amount', 0):,.0f}" if params.get('amount') else "unknown",
            reason=reason or "No reason provided",
        )

        result = self.llm.complete_json(prompt, system=LEARNING_PATTERN_SYSTEM,
                                         agent_name=self.agent_name)

        if not result:
            self.events.detail(self.agent_name, "LLM could not extract pattern")
            return None

        # Store pattern in resolved_pattern table
        input_snapshot = {
            "vendor": vendor,
            "decision_type": decision_type,
            "section": params.get("section"),
            "amount": params.get("amount"),
        }

        resolution_snapshot = {
            "pattern_type": result.get("pattern_type", decision_type),
            "description": result.get("description", ""),
            "conditions": result.get("conditions", {}),
            "action": result.get("action", decision_type),
            "similar_vendors_hint": result.get("similar_vendors_hint", ""),
        }

        pattern = self.db.patterns.create(
            pattern_type=result.get("pattern_type", decision_type),
            input_snapshot=input_snapshot,
            resolution_snapshot=resolution_snapshot,
            ca_firm_id=self.firm_id,
        )

        # Generate and store embedding for similarity search
        self._store_embedding(pattern.id, input_snapshot, resolution_snapshot)

        self.events.emit(self.agent_name,
            f"Pattern extracted: {result.get('description', 'unknown')[:80]}",
            "llm_insight")

        return pattern.id

    def _store_embedding(self, pattern_id: str, input_snapshot: dict,
                         resolution_snapshot: dict):
        """Generate a text representation and store as pgvector embedding.

        For now, we create a hash-based pseudo-embedding (no real embedding model).
        When Anthropic API is available, replace with real embeddings.
        """
        # Build text representation for embedding
        text = json.dumps({
            "input": input_snapshot,
            "resolution": resolution_snapshot,
        }, sort_keys=True)

        # For now: generate a deterministic pseudo-embedding from text hash
        # This allows exact-match retrieval but not true semantic similarity
        # TODO: Replace with real embeddings (OpenAI ada-002 or Anthropic) in Phase 2
        embedding = self._text_to_pseudo_embedding(text)

        try:
            # Store embedding via raw SQL (supabase-py doesn't handle vector type well)
            self.db._client.table("resolved_pattern").update({
                "embedding": embedding
            }).eq("id", pattern_id).execute()
        except Exception as e:
            self.events.detail(self.agent_name, f"Embedding storage skipped: {str(e)[:50]}")

    def _text_to_pseudo_embedding(self, text: str) -> list[float]:
        """Create a pseudo-embedding from text hash. NOT real semantic similarity.

        This is a placeholder. Real embeddings require an embedding model API call.
        This allows the pgvector infrastructure to work while we wait for API key.
        """
        # Hash the text to get deterministic bytes
        h = hashlib.sha512(text.encode()).digest()
        # Expand to 1536 dimensions (pgvector expects this for the index)
        import struct
        embedding = []
        for i in range(1536):
            byte_idx = i % len(h)
            val = (h[byte_idx] - 128) / 128.0  # normalize to [-1, 1]
            embedding.append(round(val, 6))
        return embedding

    def find_similar_patterns(self, input_data: dict, limit: int = 5,
                              threshold: float = 0.7) -> list[dict]:
        """Find patterns similar to the given input using pgvector similarity search.

        Args:
            input_data: dict with vendor, section, amount etc.
            limit: max number of results
            threshold: minimum similarity score (0-1)

        Returns: list of {pattern, similarity_score}
        """
        text = json.dumps(input_data, sort_keys=True)
        embedding = self._text_to_pseudo_embedding(text)

        try:
            # Call the match_patterns RPC function we created in Supabase
            result = self.db._client.rpc("match_patterns", {
                "query_embedding": embedding,
                "match_threshold": threshold,
                "match_count": limit,
                "filter_firm_id": self.firm_id,
            }).execute()

            patterns = []
            for row in result.data:
                patterns.append({
                    "id": row["id"],
                    "pattern_type": row["pattern_type"],
                    "input_snapshot": row["input_snapshot"],
                    "resolution_snapshot": row["resolution_snapshot"],
                    "similarity": row["similarity"],
                    "usage_count": row["usage_count"],
                })
            return patterns

        except Exception as e:
            self.events.detail(self.agent_name, f"Similarity search failed: {str(e)[:50]}")
            return []

    def get_learned_rules(self) -> list[dict]:
        """Get all active patterns for this firm. Used as Pass 0 before Matcher."""
        try:
            patterns = self.db._client.table("resolved_pattern").select("*").or_(
                f"ca_firm_id.eq.{self.firm_id},ca_firm_id.is.null"
            ).execute()

            rules = []
            for p in patterns.data:
                resolution = p.get("resolution_snapshot", {})
                if isinstance(resolution, str):
                    resolution = json.loads(resolution)
                rules.append({
                    "id": p["id"],
                    "pattern_type": p["pattern_type"],
                    "conditions": resolution.get("conditions", {}),
                    "action": resolution.get("action", ""),
                    "description": resolution.get("description", ""),
                    "usage_count": p.get("usage_count", 0),
                })
            return rules

        except Exception:
            return []

    def apply_learned_rules(self, tds_entries: list[dict],
                            ledger_entries: list[dict]) -> dict:
        """Apply learned rules as Pass 0 before Matcher runs.

        Returns: {applied_count, below_threshold_count, ignored_count, rules_used}
        """
        rules = self.get_learned_rules()
        if not rules:
            return {"applied_count": 0, "below_threshold_count": 0,
                    "ignored_count": 0, "rules_used": []}

        self.events.detail(self.agent_name, f"Applying {len(rules)} learned rules...")

        applied = 0
        below_threshold = 0
        ignored = 0
        rules_used = []

        for rule in rules:
            conditions = rule.get("conditions", {})
            action = rule.get("action", "")
            vendor_keywords = conditions.get("vendor_keywords", [])
            section = conditions.get("section", "")

            if action == "below_threshold":
                # Mark matching ledger entries as below threshold
                for entry in ledger_entries:
                    party = (entry.get("party_name") or "").lower()
                    if any(kw.lower() in party for kw in vendor_keywords):
                        entry["_below_threshold"] = True
                        entry["_rule_id"] = rule["id"]
                        below_threshold += 1
                        applied += 1

            elif action == "ignore":
                # Mark matching entries to be skipped
                for entry in ledger_entries:
                    party = (entry.get("party_name") or "").lower()
                    if any(kw.lower() in party for kw in vendor_keywords):
                        entry["_ignored"] = True
                        entry["_rule_id"] = rule["id"]
                        ignored += 1
                        applied += 1

            if applied > 0:
                rules_used.append(rule["id"])

        if applied:
            self.events.detail(self.agent_name,
                f"Rules applied: {below_threshold} below-threshold, {ignored} ignored")

        return {
            "applied_count": applied,
            "below_threshold_count": below_threshold,
            "ignored_count": ignored,
            "rules_used": rules_used,
        }
