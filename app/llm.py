"""Single funnel for Gemini calls.

Every node calls through here, which gives one place for: usage accounting,
schema-enforced output, and test monkeypatching.
"""

import logging
from typing import TypeVar

from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.config import GEMINI_MODEL, get_api_key
from app.schemas import Usage

logger = logging.getLogger("trend_agent")

T = TypeVar("T", bound=BaseModel)


def _usage_from_raw(raw, model: str, node: str) -> Usage:
    meta = getattr(raw, "usage_metadata", None) or {}
    usage = Usage(
        model=model,
        node=node,
        input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"),
        total_tokens=meta.get("total_tokens"),
    )
    logger.info(
        "llm call node=%s model=%s in=%s out=%s total=%s",
        node, model, usage.input_tokens, usage.output_tokens, usage.total_tokens,
    )
    return usage


async def call_structured(
    schema: type[T],
    messages: list[BaseMessage],
    *,
    node: str,
    model: str = GEMINI_MODEL,
    temperature: float = 0.4,
) -> tuple[T, Usage]:
    """One schema-enforced Gemini call. Raises ValueError on invalid output."""
    llm = ChatGoogleGenerativeAI(model=model, google_api_key=get_api_key(), temperature=temperature)
    structured = llm.with_structured_output(schema, include_raw=True)
    result = await structured.ainvoke(messages)
    if result.get("parsing_error") or result.get("parsed") is None:
        raise ValueError(f"{node}: model output failed schema validation: {result.get('parsing_error')}")
    return result["parsed"], _usage_from_raw(result["raw"], model, node)


async def call_text(
    messages: list[BaseMessage],
    *,
    node: str,
    model: str = GEMINI_MODEL,
    temperature: float = 0.4,
    tools: list | None = None,
) -> tuple[object, Usage]:
    """Free-text Gemini call (used later for grounded search); returns (AIMessage, Usage)."""
    llm = ChatGoogleGenerativeAI(model=model, google_api_key=get_api_key(), temperature=temperature)
    if tools:
        llm = llm.bind_tools(tools)
    raw = await llm.ainvoke(messages)
    return raw, _usage_from_raw(raw, model, node)
