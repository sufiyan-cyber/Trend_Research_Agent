"""Flash triage: 'notable?' gate before any deep analysis (cost guardrail)."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import load_prompt
from app.llm import call_structured
from app.schemas import ScanItem, TriageBatch, Usage

logger = logging.getLogger("trend_agent")

BATCH_SIZE = 10


async def triage_items(items: list[ScanItem]) -> tuple[list[ScanItem], list[Usage]]:
    """Return (notable survivors, usages). Items failing triage never reach the deep model."""
    survivors: list[ScanItem] = []
    usages: list[Usage] = []
    system = SystemMessage(content=load_prompt("triage_v1.md"))

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        listing = "\n".join(
            f"{i}. [{it.source_name}] {it.title} — {it.summary[:200]}" for i, it in enumerate(batch)
        )
        result, usage = await call_structured(
            TriageBatch,
            [system, HumanMessage(content=f"Items to triage:\n\n{listing}")],
            node="triage",
        )
        usages.append(usage)
        for d in result.decisions:
            if d.notable and 0 <= d.index < len(batch):
                survivors.append(batch[d.index])
    logger.info("triage: %d of %d items notable", len(survivors), len(items))
    return survivors, usages
