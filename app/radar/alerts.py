"""Rising-trend alerts. A pattern crosses 'rising' -> immediate ping.

Alerts land in data/radar/alerts.json and the server log; set ALERT_WEBHOOK
in .env to also POST each alert as JSON (e.g. a Slack/Discord webhook).
Same play alerts at most once per 7 days to avoid noise.
"""

import json
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from app.config import ALERT_WEBHOOK, DATA_DIR
from app.schemas import Alert, utcnow

logger = logging.getLogger("trend_agent")

ALERTS_PATH = DATA_DIR / "radar" / "alerts.json"
DEDUPE_DAYS = 7


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def list_alerts() -> list[Alert]:
    return [Alert.model_validate(a) for a in _load(ALERTS_PATH)]


async def maybe_alert(report_id: str, play: str, verdict: str, angle_hint: str = "") -> Alert | None:
    """Record an alert for a rising pattern unless we already pinged recently."""
    if verdict != "rising":
        return None
    existing = _load(ALERTS_PATH)
    cutoff = (utcnow() - timedelta(days=DEDUPE_DAYS)).isoformat()
    if any(a.get("play") == play and a.get("created_at", "") >= cutoff for a in existing):
        return None

    alert = Alert(
        alert_id=uuid.uuid4().hex[:10],
        created_at=utcnow().isoformat(),
        report_id=report_id,
        play=play,
        verdict=verdict,
        message=f"RISING: '{play}' is picking up. See report {report_id}."
        + (f" Suggested angle: {angle_hint}" if angle_hint else ""),
    )
    existing.append(alert.model_dump())
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.warning("TREND ALERT %s", alert.message)

    if ALERT_WEBHOOK:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(ALERT_WEBHOOK, json={"text": alert.message, **alert.model_dump()})
        except Exception as e:
            logger.warning("alert webhook failed: %s", e)
    return alert
