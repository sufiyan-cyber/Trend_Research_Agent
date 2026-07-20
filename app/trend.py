"""Live market signal via Gemini Google Search grounding.

Citations come from grounding metadata (real URLs the search surfaced),
never from model text — the model can't invent sources here.
"""

import logging

from langchain_core.messages import HumanMessage

from app.llm import call_text
from app.schemas import Citation, Usage

logger = logging.getLogger("trend_agent")


def _message_text(raw) -> str:
    text = getattr(raw, "text", "")
    if callable(text):
        text = text()
    if text:
        return text
    content = getattr(raw, "content", "")
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def _citations_from(raw) -> list[Citation]:
    meta = getattr(raw, "response_metadata", {}) or {}
    grounding = meta.get("grounding_metadata") or {}
    out = []
    for chunk in grounding.get("grounding_chunks") or []:
        web = (chunk or {}).get("web") or {}
        if web.get("uri"):
            out.append(Citation(title=web.get("title", ""), url=web["uri"]))
    return out


async def market_signal(topic: str) -> tuple[str, list[Citation], Usage]:
    """Ask the live web: is this marketing pattern new / rising / peaked / fading?"""
    prompt = (
        "Search the web for current discussion of this marketing pattern and report "
        "what the market says RIGHT NOW.\n\n"
        f"Pattern: {topic}\n\n"
        "Cover: (1) who is using it and recent examples, (2) is usage/discussion "
        "growing, saturated, or declining — with any dated evidence, (3) signs of "
        "audience fatigue or platform pushback. Be concrete and cite what you find. "
        "If the web says little about it, say exactly that."
    )
    raw, usage = await call_text(
        [HumanMessage(content=prompt)],
        node="trend_search",
        tools=[{"google_search": {}}],
    )
    citations = _citations_from(raw)
    logger.info("trend search: %d citations", len(citations))
    return _message_text(raw), citations, usage
