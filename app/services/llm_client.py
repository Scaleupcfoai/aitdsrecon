"""
Unified LLM Client — single interface for all agents to call LLMs.

Currently uses Groq (free tier). Swap to Anthropic by changing provider in config.
Every LLM call emits an SSE event so the UI shows LLM "thinking" in real-time.

Usage:
    from app.services.llm_client import LLMClient
    llm = LLMClient(events=emitter)
    response = llm.complete(
        prompt="Is this vendor the same as...",
        system="You are a TDS reconciliation expert.",
        agent_name="Matcher Agent",
    )
"""

import json
import time
from typing import Generator

from groq import Groq

from app.config import settings
from app.pipeline.events import EventEmitter


class LLMClient:
    """Unified LLM client. All agents use this for LLM calls.

    Features:
    - Emits SSE events on every call (UI shows LLM thinking)
    - Graceful fallback (returns None if LLM unavailable)
    - JSON mode support (for structured responses)
    - Retry on rate limit (1 retry after 2s wait)
    """

    def __init__(self, events: EventEmitter | None = None):
        self.events = events
        self._client = None
        if settings.groq_api_key:
            self._client = Groq(api_key=settings.groq_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete(
        self,
        prompt: str,
        system: str = "",
        agent_name: str = "LLM",
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_knowledge: bool = True,
    ) -> str | None:
        """Send a prompt to the LLM and return the response text.

        Args:
            prompt: The user message / question
            system: System prompt (role definition)
            agent_name: Which agent is calling (for SSE events)
            json_mode: If True, request JSON output format
            temperature: Override default (0.1)
            max_tokens: Override default (2000)
            include_knowledge: If True, inject TDS knowledge base into system prompt

        Returns:
            Response text, or None if LLM unavailable/failed
        """
        if not self._client:
            return None

        # Inject knowledge base into system prompt
        if include_knowledge and system:
            from app.knowledge import get_llm_context
            knowledge_ctx = get_llm_context()
            system = (
                f"{system}\n\n"
                f"IMPORTANT: Use ONLY the following verified TDS rules for any tax-related "
                f"answers. Do NOT rely on your training data for rates, thresholds, or penalties. "
                f"If the answer is not in the rules below, say 'I don't have verified data for this.'\n\n"
                f"{knowledge_ctx}"
            )

        temp = temperature if temperature is not None else settings.llm_temperature
        tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

        # Emit SSE event: LLM call starting
        prompt_preview = prompt[:150] + "..." if len(prompt) > 150 else prompt
        if self.events:
            self.events.emit(
                agent_name,
                f"Asking LLM: {prompt_preview}",
                "llm_call",
                {"model": settings.llm_model, "prompt_length": len(prompt)},
            )

        start = time.time()

        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            kwargs = {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": temp,
                "max_tokens": tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = self._client.chat.completions.create(**kwargs)
            result = response.choices[0].message.content

            elapsed_ms = int((time.time() - start) * 1000)
            tokens_used = getattr(response.usage, 'total_tokens', 0) if response.usage else 0

            # Emit SSE event: LLM response received
            result_preview = result[:200] + "..." if len(result) > 200 else result
            if self.events:
                self.events.emit(
                    agent_name,
                    f"LLM responded ({elapsed_ms}ms, {tokens_used} tokens)",
                    "llm_response",
                    {"response_preview": result_preview, "elapsed_ms": elapsed_ms, "tokens": tokens_used},
                )

            return result

        except Exception as e:
            error_msg = str(e)

            # Retry once on rate limit
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                if self.events:
                    self.events.emit(agent_name, "Rate limited, retrying in 2s...", "warning")
                time.sleep(2)
                try:
                    response = self._client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content
                except Exception as retry_err:
                    error_msg = str(retry_err)

            # Emit error event
            if self.events:
                self.events.emit(
                    agent_name,
                    f"LLM call failed: {error_msg[:100]}",
                    "warning",
                )

            return None  # graceful fallback — agent uses deterministic result

    def complete_json(
        self,
        prompt: str,
        system: str = "",
        agent_name: str = "LLM",
        include_knowledge: bool = True,
    ) -> dict | None:
        """Send a prompt and parse the response as JSON.

        Returns parsed dict, or None if failed.
        """
        result = self.complete(prompt, system, agent_name, json_mode=True, include_knowledge=include_knowledge)
        if result is None:
            return None
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # Try to extract JSON from the response (sometimes LLM wraps in markdown)
            try:
                start = result.index("{")
                end = result.rindex("}") + 1
                return json.loads(result[start:end])
            except (ValueError, json.JSONDecodeError):
                if self.events:
                    self.events.emit(agent_name, "LLM returned invalid JSON, falling back", "warning")
                return None
