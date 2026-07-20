"""Trend lifecycle tracking: every verdict observation builds a timeline.

'We flagged this 3 weeks before it peaked' becomes a provable claim —
early_call_days is computed from recorded timestamps, not vibes.
"""

import json
import logging
from pathlib import Path

from app.config import DATA_DIR
from app.schemas import TrendEvent, TrendTimeline, utcnow

logger = logging.getLogger("trend_agent")

TRENDS_PATH = DATA_DIR / "trends.json"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def record_event(play: str, verdict: str, report_id: str) -> None:
    events = _load(TRENDS_PATH)
    events.append(TrendEvent(at=utcnow().isoformat(), play=play, verdict=verdict, report_id=report_id).model_dump())
    TRENDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRENDS_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def timelines() -> list[TrendTimeline]:
    by_play: dict[str, list[TrendEvent]] = {}
    for raw in _load(TRENDS_PATH):
        e = TrendEvent.model_validate(raw)
        by_play.setdefault(e.play, []).append(e)

    out = []
    for play, events in by_play.items():
        events.sort(key=lambda e: e.at)
        first_rising = next((e.at for e in events if e.verdict == "rising"), None)
        first_peaked = next((e.at for e in events if e.verdict == "peaked"), None)
        early_days = None
        if first_rising and first_peaked and first_peaked > first_rising:
            from datetime import datetime

            delta = datetime.fromisoformat(first_peaked) - datetime.fromisoformat(first_rising)
            early_days = delta.days
        out.append(
            TrendTimeline(
                play=play,
                current_verdict=events[-1].verdict,
                first_seen=events[0].at,
                last_seen=events[-1].at,
                observations=len(events),
                first_rising_at=first_rising,
                first_peaked_at=first_peaked,
                early_call_days=early_days,
                events=events,
            )
        )
    out.sort(key=lambda t: t.last_seen, reverse=True)
    return out


def timeline_for(play: str) -> TrendTimeline | None:
    return next((t for t in timelines() if t.play.lower() == play.lower()), None)
