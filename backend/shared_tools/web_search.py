"""Web search tool — used only by the orchestrator (a1).

When GEMINI_API_KEY is set, calls Gemini 2.5 Flash with Google Search grounding
to get a grounded answer + citations. When unset, returns a deterministic mock
so the pipeline still runs locally.
"""

from __future__ import annotations

import os
from typing import Any


async def web_search(query: str) -> dict[str, Any]:
    if not os.getenv("GEMINI_API_KEY"):
        return _mock(query)
    try:
        return await _grounded(query)
    except Exception as e:  # noqa: BLE001 — network / SDK hiccups shouldn't kill the session
        return {
            "query": query,
            "summary": f"Web search failed ({type(e).__name__}). Proceeding without web context.",
            "sources": [],
            "mock": True,
            "error": str(e)[:200],
        }


async def _grounded(query: str) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f"Research this query concisely for an Indian tax/TDS assistant. "
            f"Give a 2-3 sentence summary and a recommendation if applicable.\n\nQuery: {query}"
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        ),
    )
    sources: list[dict[str, Any]] = []
    candidate = (response.candidates or [None])[0]
    if candidate and candidate.grounding_metadata:
        for chunk in candidate.grounding_metadata.grounding_chunks or []:
            web = getattr(chunk, "web", None)
            if web:
                sources.append({"title": web.title, "url": web.uri})
    return {
        "query": query,
        "summary": response.text or "",
        "sources": sources[:5],
        "mock": False,
    }


def _mock(query: str) -> dict[str, Any]:
    q = (query or "").lower()
    # Minimal canned knowledge so a1 can form research_note strings during mock runs.
    if "advertisement" in q or "facebook" in q or "google ads" in q or "platform ad" in q:
        summary = (
            "Digital platform advertising (Meta, Google) is commonly treated as 194C (works contract) at 2%. "
            "Some CAs classify creative/agency fees as 194J(b) at 10%. Direct platform spend leans 194C."
        )
    elif "software" in q or "saas" in q:
        summary = (
            "Software licence fees typically fall under 194J(b) as royalty/technical services at 10%. "
            "Bespoke software development contracts may fall under 194C at 2%."
        )
    elif "206aa" in q or "missing pan" in q:
        summary = (
            "Section 206AA: without valid PAN, TDS rate = higher of applicable rate or 20%. "
            "Applies across all sections."
        )
    elif "igm" in q or "shipping" in q or "port" in q:
        summary = (
            "Port/shipping handling fees to private operators usually fall under 194C at 2%. "
            "Fees paid to government ports may be exempt."
        )
    else:
        summary = (
            "Mock web_search. Real results require GEMINI_API_KEY. Treat as unverified; ask the user to confirm."
        )
    return {
        "query": query,
        "summary": summary,
        "sources": [{"title": "mock", "url": "about:blank"}],
        "mock": True,
    }
