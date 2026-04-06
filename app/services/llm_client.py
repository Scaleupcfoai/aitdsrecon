"""
Unified LLM Client — single interface for all agents to call LLMs.

Currently uses Google Gemini (gemini-2.5-flash). Falls back to Groq if configured.
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

from app.config import settings
from app.pipeline.events import EventEmitter


class LLMClient:
    """Unified LLM client. All agents use this for LLM calls.

    Features:
    - Supports Gemini (primary) and Groq (fallback)
    - Emits SSE events on every call (UI shows LLM thinking)
    - Graceful fallback (returns None if LLM unavailable)
    - JSON mode support (for structured responses)
    - Retry on rate limit (1 retry after 2s wait)
    """

    def __init__(self, events: EventEmitter | None = None):
        self.events = events
        self._gemini_client = None
        self._groq_client = None
        self._provider = None

        # Try Gemini first (primary)
        if settings.gemini_api_key:
            from google import genai
            self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
            self._provider = "gemini"
        # Fall back to Groq
        elif settings.groq_api_key:
            from groq import Groq
            self._groq_client = Groq(api_key=settings.groq_api_key)
            self._provider = "groq"

    @property
    def available(self) -> bool:
        return self._provider is not None

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
        """Send a prompt to the LLM and return the response text."""
        if not self.available:
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
            if self._provider == "gemini":
                result = self._call_gemini(prompt, system, temp, tokens, json_mode)
            else:
                result = self._call_groq(prompt, system, temp, tokens, json_mode)

            elapsed_ms = int((time.time() - start) * 1000)

            # Emit SSE event: LLM response received
            result_preview = result[:200] + "..." if len(result) > 200 else result
            if self.events:
                self.events.emit(
                    agent_name,
                    f"LLM responded ({elapsed_ms}ms, {self._provider})",
                    "llm_response",
                    {"response_preview": result_preview, "elapsed_ms": elapsed_ms},
                )

            return result

        except Exception as e:
            error_msg = str(e)

            # Retry once on rate limit
            if "rate_limit" in error_msg.lower() or "429" in error_msg or "resource_exhausted" in error_msg.lower():
                if self.events:
                    self.events.emit(agent_name, "Rate limited, retrying in 2s...", "warning")
                time.sleep(2)
                try:
                    if self._provider == "gemini":
                        return self._call_gemini(prompt, system, temp, tokens, json_mode)
                    else:
                        return self._call_groq(prompt, system, temp, tokens, json_mode)
                except Exception as retry_err:
                    error_msg = str(retry_err)

            # Emit error event
            if self.events:
                self.events.emit(
                    agent_name,
                    f"LLM call failed: {error_msg[:100]}",
                    "warning",
                )

            return None

    def _call_gemini(self, prompt: str, system: str, temp: float, max_tokens: int, json_mode: bool) -> str:
        """Call Google Gemini API."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system if system else None,
            temperature=temp,
            max_output_tokens=max_tokens,
        )
        if json_mode:
            config.response_mime_type = "application/json"

        response = self._gemini_client.models.generate_content(
            model=settings.llm_model,
            contents=prompt,
            config=config,
        )
        return response.text

    def _call_groq(self, prompt: str, system: str, temp: float, max_tokens: int, json_mode: bool) -> str:
        """Call Groq API (fallback)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._groq_client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def complete_json(
        self,
        prompt: str,
        system: str = "",
        agent_name: str = "LLM",
        include_knowledge: bool = True,
    ) -> dict | None:
        """Send a prompt and parse the response as JSON.

        Handles: empty response, non-JSON, markdown-wrapped JSON,
        JSON arrays (takes first element), string confidence values.
        """
        result = self.complete(prompt, system, agent_name, json_mode=True, include_knowledge=include_knowledge)
        if not result or not result.strip():
            return None
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else None
            if isinstance(parsed, dict):
                for key in ("confidence",):
                    if key in parsed and isinstance(parsed[key], str):
                        try:
                            parsed[key] = float(parsed[key])
                        except ValueError:
                            parsed[key] = 0.0
            return parsed
        except json.JSONDecodeError:
            # Try to extract JSON from markdown-wrapped response
            try:
                start = result.index("{")
                end = result.rindex("}") + 1
                parsed = json.loads(result[start:end])
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, json.JSONDecodeError):
                pass
            try:
                start = result.index("[")
                end = result.rindex("]") + 1
                parsed = json.loads(result[start:end])
                if isinstance(parsed, list) and parsed:
                    return parsed[0] if isinstance(parsed[0], dict) else None
            except (ValueError, json.JSONDecodeError):
                pass
            if self.events:
                self.events.emit(agent_name, f"LLM returned invalid JSON: {result[:50]}...", "warning")
            return None
