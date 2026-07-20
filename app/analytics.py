"""Aggregations behind the dashboard charts.

Everything here is computed from stored reports and the lifecycle log — no
model calls, so the dashboard is free to render and cannot hallucinate a
number. Each series ships with the counts the chart draws *and* the labels its
table-view twin needs, so no value is reachable only by hovering a chart.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.schemas import utcnow

VERDICTS = ["new", "rising", "peaked", "fading"]


def _week_start(iso: str) -> str:
    """Monday of the week containing `iso`, as YYYY-MM-DD."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (d - timedelta(days=d.weekday())).date().isoformat()


def verdict_mix_by_week(events: list[dict], weeks: int = 8) -> dict:
    """Stacked series: how many observations landed in each lifecycle stage per week.

    This is the 'market trend' view — whether the plays we are seeing are
    mostly emerging or mostly burning out.
    """
    cutoff = (utcnow() - timedelta(weeks=weeks)).isoformat()
    buckets: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        at = e.get("at", "")
        if at >= cutoff:
            buckets[_week_start(at)][e.get("verdict", "")] += 1

    # Emit an unbroken week axis; gaps in a time series must read as zero,
    # not as the line skipping over them.
    labels: list[str] = []
    cur = datetime.fromisoformat(_week_start(utcnow().isoformat()))
    for _ in range(weeks):
        labels.append(cur.date().isoformat())
        cur -= timedelta(weeks=1)
    labels.reverse()

    return {
        "labels": labels,
        "series": [{"key": v, "values": [buckets[w][v] for w in labels]} for v in VERDICTS],
        "total": sum(sum(c.values()) for c in buckets.values()),
    }


def plays_leaderboard(payloads: list[dict], top: int = 8) -> dict:
    """Which plays we have analyzed most, with their current verdict mix."""
    counts = Counter(p.get("primary_play") or "(unnamed)" for p in payloads)
    top_plays = counts.most_common(top)

    # Latest verdict per play, by created_at.
    latest: dict[str, tuple[str, str]] = {}  # play -> (created_at, verdict)
    for p in payloads:
        play = p.get("primary_play") or "(unnamed)"
        at = p.get("created_at", "")
        if at >= latest.get(play, ("", ""))[0]:
            latest[play] = (at, p.get("trend_verdict") or "")
    verdicts = {play: v for play, (_, v) in latest.items()}

    return {
        "items": [
            {"label": play, "value": n, "verdict": verdicts.get(play, "")}
            for play, n in top_plays
        ],
        "other": max(0, len(counts) - len(top_plays)),
    }


def relevance_distribution(reports: list[dict]) -> dict:
    """Histogram of relevance scores in 20-point bands, plus the running mean.

    Answers 'is the radar bringing us things we can actually use?' — a pipeline
    whose scores cluster under 40 is a pipeline pointed at the wrong sources.
    """
    bands = ["0-19", "20-39", "40-59", "60-79", "80-100"]
    hist = Counter()
    scores: list[int] = []
    for r in reports:
        sc = (r.get("report") or {}).get("scorecard")
        if not sc:
            continue
        s = sc.get("relevance_to_us")
        if s is None:
            continue
        scores.append(s)
        hist[bands[min(4, s // 20)]] += 1
    return {
        "labels": bands,
        "values": [hist[b] for b in bands],
        "scored_reports": len(scores),
        "mean": round(sum(scores) / len(scores)) if scores else None,
    }


def risk_profile(reports: list[dict]) -> dict:
    """Severity mix across every weakness the critic has ever raised.

    A corpus with no `high` findings anywhere is evidence the critic has gone
    soft, not evidence the campaigns are flawless — worth being able to see.
    """
    sev = Counter()
    critiqued = 0
    risk_scores: list[int] = []
    for r in reports:
        rep = r.get("report") or {}
        cr = rep.get("critique")
        if not cr:
            continue
        critiqued += 1
        for w in cr.get("weaknesses") or []:
            sev[w.get("severity", "")] += 1
        sc = rep.get("scorecard") or {}
        if sc.get("risk_index") is not None:
            risk_scores.append(sc["risk_index"])
    return {
        "labels": ["high", "medium", "low"],
        "values": [sev["high"], sev["medium"], sev["low"]],
        "critiqued_reports": critiqued,
        "total_weaknesses": sum(sev.values()),
        "mean_risk_index": round(sum(risk_scores) / len(risk_scores)) if risk_scores else None,
    }


def emotion_mix(payloads: list[dict], top: int = 6) -> dict:
    """Which emotional triggers dominate the campaigns we see."""
    counts = Counter((p.get("emotion") or "(none)").lower() for p in payloads)
    items = counts.most_common(top)
    tail = sum(n for _, n in counts.most_common()[top:])
    out = [{"label": e, "value": n} for e, n in items]
    if tail:
        out.append({"label": "other", "value": tail})
    return {"items": out}


def build_analytics(reports: list[dict], payloads: list[dict], events: list[dict]) -> dict:
    return {
        "verdict_mix": verdict_mix_by_week(events),
        "plays": plays_leaderboard(payloads),
        "relevance": relevance_distribution(reports),
        "risk": risk_profile(reports),
        "emotions": emotion_mix(payloads),
        "reports_total": len(reports),
    }
