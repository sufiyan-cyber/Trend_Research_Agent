"""Weekly Trend Digest: auto-generated from a week of memory.

The Monday-morning artifact: what's rising, what peaked, notable campaigns,
recommended plays for our buckets — nobody has to have done anything.
"""

import json
import logging
from collections import Counter
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import DATA_DIR, GEMINI_COMPOSER_MODEL, brand_prompt
from app.llm import call_structured
from app.memory import get_memory
from app.radar.alerts import list_alerts
from app.schemas import DigestModel, utcnow

logger = logging.getLogger("trend_agent")

DIGESTS_DIR = DATA_DIR / "radar" / "digests"


def digest_to_markdown(d: DigestModel, generated_at: str) -> str:
    parts = [f"# Weekly Trend Digest — {generated_at[:10]}\n", f"**{d.headline}**\n", d.week_summary]
    if d.rising:
        parts.append("\n## Rising\n")
        for t in d.rising:
            parts.append(
                f"### {t.pattern}\n{t.evidence}\n\n**Aim at:** {t.recommended_bucket}\n\n**Move:** {t.suggested_move}"
            )
    if d.watch:
        parts.append("\n## Watch / Avoid\n")
        for t in d.watch:
            parts.append(f"### {t.pattern}\n{t.evidence}\n\n**If we touch it:** {t.suggested_move}")
    if d.notable_campaigns:
        parts.append("\n## Notable campaigns\n")
        for n in d.notable_campaigns:
            ref = f" (`{n.reference}`)" if n.reference else ""
            parts.append(f"- **{n.title}**{ref} — {n.why_notable}")
    return "\n\n".join(parts) + "\n"


def _quiet_week() -> DigestModel:
    return DigestModel(
        headline="Quiet week — no new analyses in memory.",
        week_summary=(
            "No campaigns were analyzed in the last 7 days, so there is nothing "
            "evidence-based to report. Run the radar scan or submit campaigns to feed the digest."
        ),
        rising=[],
        watch=[],
        notable_campaigns=[],
    )


async def generate_digest() -> dict:
    """Build this week's digest from memory; store JSON + markdown; return the record."""
    payloads = get_memory().recent_payloads(days=7)
    generated_at = utcnow().isoformat()

    if not payloads:
        model = _quiet_week()
        usages = []
    else:
        plays = Counter(p.get("primary_play", "?") for p in payloads)
        verdicts = Counter(p.get("trend_verdict") or "n/a" for p in payloads)
        lines = "\n".join(
            f"- [{p.get('created_at', '')[:10]}] ({p.get('source', 'user')}) {p.get('report_id')}: "
            f"{p.get('primary_play')} | emotion={p.get('emotion')} | verdict={p.get('trend_verdict') or 'n/a'} | "
            f"{p.get('summary', '')[:220]}"
            for p in payloads[:60]
        )
        alerts = [a for a in list_alerts() if a.created_at >= (generated_at[:10])] or list_alerts()[-5:]
        alert_lines = "\n".join(f"- {a.created_at[:10]}: {a.message}" for a in alerts) or "(none)"
        briefing = (
            f"Week ending {generated_at[:10]}.\n\n"
            f"## Analyses this week ({len(payloads)})\n{lines}\n\n"
            f"## Play frequency this week\n{dict(plays)}\n\n"
            f"## Trend verdicts this week\n{dict(verdicts)}\n\n"
            f"## Recent rising-trend alerts\n{alert_lines}"
        )
        model, usage = await call_structured(
            DigestModel,
            [SystemMessage(content=brand_prompt("digest_v1.md")), HumanMessage(content=briefing)],
            node="digest",
            model=GEMINI_COMPOSER_MODEL,
        )
        usages = [usage.model_dump()]

    record = {
        "generated_at": generated_at,
        "week_items": len(payloads),
        "digest": model.model_dump(),
        "markdown": digest_to_markdown(model, generated_at),
        "usages": usages,
    }
    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    (DIGESTS_DIR / f"{generated_at[:10]}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("digest generated for %s (%d items)", generated_at[:10], len(payloads))
    return record


def latest_digest() -> dict | None:
    files = sorted(DIGESTS_DIR.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def list_digests() -> list[str]:
    return [f.stem for f in sorted(DIGESTS_DIR.glob("*.json"), reverse=True)]
