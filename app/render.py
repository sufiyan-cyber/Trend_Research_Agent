"""Render reports as clean markdown."""

from app.schemas import CampaignReport, CampaignReportV1, Critique, EmotionProfile, Scorecard, TriggerPlay

_SEVERITY_MARK = {"high": "🔴 HIGH", "medium": "🟠 MEDIUM", "low": "🟡 LOW"}
_FIT_MARK = {"strong": "✅ STRONG", "stretch": "🟡 STRETCH", "avoid": "⛔ AVOID"}

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


def _scorecard_markdown(sc: Scorecard | None) -> str:
    """Scores as a table — the markdown twin of the report's charts.

    Every chart in the UI has to be readable without the chart; this is that
    fallback, and it is also what lands in an exported brief.
    """
    if sc is None:
        return ""
    rows = "\n".join(
        f"| {d.label} | {d.score} | {'computed' if d.computed else 'judged'} | {d.rationale or '—'} |"
        for d in sc.dimensions
    )
    out = [
        f"## Scorecard — {sc.relevance_to_us}% relevant to us\n",
        f"**Risk index:** {sc.risk_index}/100",
        "",
        "| Dimension | Score | Source | Notes |",
        "|---|---:|---|---|",
        rows,
    ]
    if sc.scoring_note:
        out.append(f"\n*{sc.scoring_note}*")
    return "\n".join(out)


def _critique_markdown(cr: Critique | None) -> str:
    """The negative section. Rendered ahead of the specialist detail on purpose —
    it is meant to be read, not buried under an appendix."""
    if cr is None:
        return ""
    out = ["## The Case Against\n"]
    for w in cr.weaknesses:
        out.append(f"**{_SEVERITY_MARK.get(w.severity, w.severity.upper())} — {w.issue}**")
        out.append(f"- *Evidence:* {w.evidence}")
        out.append(f"- *Mitigation:* {w.mitigation}\n")
    out.append(f"**Why it might not have worked:** {cr.why_it_might_not_work}\n")
    out.append(f"**Risk if we copy it:** {cr.risk_if_we_copy_it}\n")
    out.append(f"**Brand safety:** {cr.brand_safety_flag}\n")
    out.append(f"**Survivorship check:** {cr.survivorship_check}\n")
    out.append(f"**What we could not verify:** {cr.what_we_could_not_verify}\n")
    out.append(f"**Confidence in the positive read above:** {cr.confidence_in_positive_read}")
    return "\n".join(out)


def _emotion_markdown(em: EmotionProfile | None, playbook: list[TriggerPlay]) -> str:
    """The trigger and how to pull it per bucket — the transfer half of the analysis."""
    if em is None and not playbook:
        return ""
    out = []
    if em is not None:
        out.append(f"## Emotional Trigger: {em.primary or em.raw} ({em.valence})\n")
        if em.trigger_element:
            out.append(f"**Fired by:** {em.trigger_element}")
        if em.raw and em.raw.lower() != em.primary:
            out.append(f"*(specialist wrote: \"{em.raw}\")*")
    if playbook:
        out.append("### How to pull this trigger in our buckets\n")
        for p in playbook:
            out.append(f"**{_FIT_MARK.get(p.fit, p.fit.upper())} — {p.bucket_name}**")
            out.append(f"- {p.how_to_fire}")
            if p.example_hook:
                out.append(f"- *Hook:* \"{p.example_hook}\"")
            if p.caution:
                out.append(f"- ⚠️ *Caution:* {p.caution}")
            out.append("")
    return "\n".join(out).rstrip()


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

    parts.extend(
        block
        for block in (
            _emotion_markdown(getattr(report, "emotion", None), getattr(report, "trigger_playbook", [])),
            _scorecard_markdown(getattr(report, "scorecard", None)),
            _critique_markdown(getattr(report, "critique", None)),
        )
        if block
    )

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
