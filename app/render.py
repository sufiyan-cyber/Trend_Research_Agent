"""Render reports as clean markdown."""

from app.schemas import CampaignReport, CampaignReportV1, CampaignReportV2

_CORE_SECTIONS: list[tuple[str, str]] = [
    ("campaign_idea", "The Campaign Idea"),
    ("how_it_was_run", "How It Was Run"),
    ("hook", "The Hook"),
    ("emotional_trigger", "Emotional Trigger"),
    ("visual_notes", "Visual Notes"),
    ("why_it_worked", "Why It Worked"),
    ("takeaway_for_us", "Takeaway for Us"),
]


def core_to_markdown(core: CampaignReport) -> str:
    parts = ["# Campaign Deconstruction\n"]
    for field, heading in _CORE_SECTIONS:
        parts.append(f"## {heading}\n")
        parts.append(f"{getattr(core, field).strip()}\n")
    return "\n".join(parts)


def report_to_markdown(report: CampaignReportV1) -> str:
    parts = [core_to_markdown(report.core)]

    if report.core.seen_before:
        parts.append("## Seen Before\n")
        parts.append(report.core.seen_before)
        for n in report.neighbors:
            parts.append(f"- `{n.report_id}` ({n.analyzed_at[:10]}, similarity {n.similarity}) — {n.primary_play}")

    trend = getattr(report, "trend", None)
    if trend is not None:
        parts.append(f"## Trend Verdict: **{trend.verdict.upper()}** (confidence: {trend.confidence})\n")
        parts.append(trend.reasoning)
        parts.append(f"**Our memory:** {trend.memory_frequency}")
        parts.append(f"**Market signal:** {trend.market_signal}")
        if trend.citations:
            parts.append("**Sources:**")
            for c in trend.citations:
                parts.append(f"- [{c.title or c.url}]({c.url})")

    audience = getattr(report, "audience", None)
    if audience is not None:
        parts.append(f"## Audience Recommendation: {audience.bucket_name}\n")
        parts.append(f"**Angle:** {audience.angle}")
        parts.append(f"**Why this bucket:** {audience.fit_reasoning}")
        parts.append(f"**What to make:** {audience.content_suggestion}")

    s = report.strategy
    play = s.primary_play + (f" + {s.secondary_play}" if s.secondary_play else "")
    parts.append("\n---\n\n## Specialist Detail\n")
    parts.append(f"**Play:** {play}")
    parts.append(f"**Channel:** {s.channel_inference}")
    parts.append(f"**Timing:** {s.timing_logic}")
    parts.append(f"**CTA:** {s.cta_structure}")

    h = report.hook_copy
    parts.append(f"\n**Hook quote:** {h.hook_quote}")
    parts.append(f"**Mechanics:** {', '.join(h.mechanics) or '—'}")
    parts.append(f"**Emotion:** {h.dominant_emotion} — {h.trigger_element}")
    if h.credibility_devices:
        parts.append(f"**Credibility devices:** {', '.join(h.credibility_devices)}")

    v = report.visual
    parts.append(f"\n**Production signal:** {v.production_signal}")
    if report.palette:
        swatches = " · ".join(f"`{c.hex}` {c.coverage_pct}%" for c in report.palette)
        parts.append(f"**Extracted palette:** {swatches}")
        parts.append(f"**Palette read:** {v.palette_interpretation}")

    return "\n\n".join(parts) + "\n"
