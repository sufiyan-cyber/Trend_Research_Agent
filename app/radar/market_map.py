"""Market map v1: profiles of tracked players, built from our own analyses.

Mechanical aggregation (plays, emotions, palettes, counts) is code; only the
short profile prose is LLM-written, one batched call per refresh.
"""

import json
import logging
from collections import Counter

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import DATA_DIR, brand_prompt
from app.llm import call_structured
from app.memory import get_memory
from app.radar.sources import load_players
from app.schemas import MarketMapModel, utcnow

logger = logging.getLogger("trend_agent")

MARKET_MAP_PATH = DATA_DIR / "radar" / "market_map.json"


def _aggregate() -> list[dict]:
    """Match every memory payload against player aliases; aggregate per player."""
    payloads = get_memory().all_payloads()
    out = []
    for player in load_players().players:
        aliases = [a.lower() for a in ([player.name] + player.aliases)]
        hits = [
            p for p in payloads
            if any(a in (p.get("summary", "") + " " + p.get("input_text", "")).lower() for a in aliases)
        ]
        if not hits:
            continue
        out.append(
            {
                "player_id": player.id,
                "name": player.name,
                "campaigns": len(hits),
                "last_seen": max(p.get("created_at", "") for p in hits),
                "top_plays": [p for p, _ in Counter(h.get("primary_play", "?") for h in hits).most_common(3)],
                "emotions": [e for e, _ in Counter(h.get("emotion", "?") for h in hits).most_common(3)],
                "palette_families": sorted({h.get("palette_family", "unknown") for h in hits}),
                "sample_summaries": [h.get("summary", "")[:250] for h in hits[:3]],
            }
        )
    return out


async def refresh_market_map() -> dict:
    """Rebuild the map; store to data/radar/market_map.json; return it."""
    aggregates = _aggregate()
    profiles: dict[str, dict] = {}
    usages = []
    if aggregates:
        briefing = "Aggregated analysis data per player:\n\n" + json.dumps(aggregates, ensure_ascii=False, indent=2)
        result, usage = await call_structured(
            MarketMapModel,
            [SystemMessage(content=brand_prompt("market_map_v1.md")), HumanMessage(content=briefing)],
            node="market_map",
        )
        usages = [usage.model_dump()]
        profiles = {p.player_id: p.model_dump() for p in result.profiles}

    record = {
        "generated_at": utcnow().isoformat(),
        "players": [{**agg, **profiles.get(agg["player_id"], {})} for agg in aggregates],
        "tracked_but_unseen": [
            p.name for p in load_players().players if p.id not in {a["player_id"] for a in aggregates}
        ],
        "usages": usages,
    }
    MARKET_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKET_MAP_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("market map refreshed: %d active players", len(aggregates))
    return record


def current_market_map() -> dict | None:
    if not MARKET_MAP_PATH.exists():
        return None
    return json.loads(MARKET_MAP_PATH.read_text(encoding="utf-8"))
