"""Ask-the-agent: natural-language questions over everything the agent knows."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import brand_prompt
from app.lifecycle import timelines
from app.llm import call_structured
from app.memory import get_memory
from app.schemas import AskAnswer, Usage

logger = logging.getLogger("trend_agent")


def _lifecycle_block() -> str:
    lines = [
        f"- {t.play}: {t.current_verdict} (first seen {t.first_seen[:10]}, {t.observations} observations"
        + (f", flagged rising {t.early_call_days} days before peak" if t.early_call_days else "")
        + ")"
        for t in timelines()[:10]
    ]
    return "\n".join(lines) or "(no lifecycle data yet)"


def _market_block() -> str:
    from app.radar.market_map import current_market_map

    record = current_market_map()
    if not record:
        return "(no market map yet)"
    return "\n".join(
        f"- {p['name']}: {p.get('profile', '')} plays={p.get('top_plays', [])} last_seen={p.get('last_seen', '')[:10]}"
        for p in record.get("players", [])
    )


def _digest_block() -> str:
    from app.radar.digest import latest_digest

    record = latest_digest()
    if not record:
        return "(no digest yet)"
    d = record["digest"]
    return f"[{record['generated_at'][:10]}] {d['headline']} — {d['week_summary']}"


async def ask(question: str) -> tuple[AskAnswer, Usage]:
    memory = get_memory()
    # No similarity threshold here: hand the model the top-k and let it judge
    # relevance — the prompt requires citing only what actually supports.
    neighbors = await memory.find_similar(question, k=6, min_score=-1.0)
    memory_block = "\n".join(
        f"- {n.report_id} ({n.analyzed_at[:10]}, {n.primary_play}): {n.summary}" for n in neighbors
    ) or "(nothing relevant in memory)"
    outcomes = memory.outcome_summary()
    outcome_block = "\n".join(
        f"- {o['play']}: {o['proven_campaigns']} proven campaign(s), e.g. {', '.join(o['examples'])}"
        for o in outcomes
    ) or "(no recorded outcomes yet)"

    context = (
        f"## Relevant past analyses\n{memory_block}\n\n"
        f"## Trend lifecycles\n{_lifecycle_block()}\n\n"
        f"## Market map\n{_market_block()}\n\n"
        f"## Latest digest\n{_digest_block()}\n\n"
        f"## What has actually worked for us (recorded outcomes)\n{outcome_block}\n\n"
        f"## Question\n{question}"
    )
    answer, usage = await call_structured(
        AskAnswer,
        [SystemMessage(content=brand_prompt("ask_v1.md")), HumanMessage(content=context)],
        node="ask",
    )
    logger.info("ask answered (confidence=%s, %d sources)", answer.confidence, len(answer.sources))
    return answer, usage
