"""Scorecard assembly: the numbers behind the report's charts.

Design rule: **anything derivable is derived, not asked.** Four of the nine
dimensions are computed here from data the pipeline already holds — the bucket
registry, the trend verdict, memory similarity, and the submitted material —
so the headline relevance number cannot be moved by a model in a generous mood.
The remaining five come from the critic (see prompts/critique_v1.md), which is
the adversarial node precisely so the judged half is not inflated either.

Computed dimensions carry `computed=True` and the UI marks them, because
"this number was calculated" and "this number was judged" are different claims
and the reader is entitled to know which is which.
"""

from app.schemas import (
    AudienceFit,
    Critique,
    JudgedScores,
    Neighbor,
    ScoreDimension,
    Scorecard,
    StrategyAnalysis,
    TrendVerdict,
)

# Timing: how well the pattern's lifecycle stage suits us *arriving now*.
# Rising is the sweet spot — the whole product thesis is catching a play before
# saturation. Peaked means we would be late; fading means we would be last.
_TIMING_BY_VERDICT = {
    "new": 78,      # unproven, but we would be early
    "rising": 95,   # the window the agent exists to find
    "peaked": 42,   # still works, reads derivative
    "fading": 18,   # arriving after the audience left
}

# Weights for the headline relevance blend. Fit-to-us dominates on purpose:
# a brilliant campaign we cannot use is not "relevant", it is interesting.
_RELEVANCE_WEIGHTS = {
    "audience_fit": 0.24,
    "brand_fit": 0.20,
    "channel_fit": 0.16,
    "timing_fit": 0.15,
    "replicability": 0.13,
    "hook_strength": 0.07,
    "originality": 0.05,
}

# Peak severity sets the base, so these sit well below 100: a single high-severity
# finding should read as "seriously exposed" (62), not max out the scale and leave
# no room to distinguish it from a campaign with three of them.
_SEVERITY_WEIGHT = {"high": 62, "medium": 34, "low": 14}


def _clamp(n: float) -> int:
    return max(0, min(100, round(n)))


def channel_fit(strategy: StrategyAnalysis, audience: AudienceFit | None, bucket_channels: list[str]) -> tuple[int, str]:
    """Do we have distribution where this campaign's format lives?

    Matched by substring against the channels our own buckets actually list —
    the inferred channel is free text ("Reels/Instagram (inference)"), so exact
    matching would miss almost everything.
    """
    inferred = strategy.channel_inference.lower()
    if not bucket_channels:
        return 50, "No channels registered for our buckets — cannot assess distribution fit."

    hits = sorted({c for c in bucket_channels if c.lower() in inferred})
    if hits:
        # Two+ shared channels means several of our audiences are reachable there.
        score = 88 if len(hits) > 1 else 76
        return score, f"Format implies {', '.join(hits)} — we already publish there."

    # A named channel we don't run is a worse fit than an unreadable inference.
    named = any(k in inferred for k in ("tiktok", "youtube", "twitter", "x.com", "billboard", "ooh", "tv", "print", "reddit", "snapchat"))
    if named:
        return 28, "The format's native channel is one we have no presence on — distribution would have to be built first."
    return 48, "Channel could not be pinned to one of our registered channels; treat the fit as unknown."


def timing_fit(trend: TrendVerdict | None) -> tuple[int, str]:
    if trend is None:
        return 50, "No trend verdict available."
    score = _TIMING_BY_VERDICT.get(trend.verdict, 50)
    # A low-confidence verdict shouldn't swing the headline number as hard as a
    # high-confidence one, so pull it toward neutral.
    if trend.confidence == "low":
        score = round(score * 0.6 + 50 * 0.4)
    elif trend.confidence == "medium":
        score = round(score * 0.8 + 50 * 0.2)
    return _clamp(score), f"Pattern is '{trend.verdict}' at {trend.confidence} confidence."


def novelty(neighbors: list[Neighbor]) -> tuple[int, str]:
    """How new is this to *us*? Inverse of the closest thing already in memory."""
    if not neighbors:
        return 100, "Nothing comparable in memory — first of its kind for us."
    closest = max(n.similarity for n in neighbors)
    # Recall threshold is 0.55, so similarities live in roughly 0.55-1.0.
    # Stretch that band across the scale instead of wasting the bottom half,
    # but cap at 95: having found *something* related must never score as novel
    # as having found nothing at all.
    score = _clamp((1.0 - closest) / 0.45 * 95)
    return score, f"Closest past analysis sits at {closest:.2f} similarity ({len(neighbors)} related report(s) in memory)."


def audience_fit_score(audience: AudienceFit | None) -> tuple[int, str]:
    """Confidence that the pattern reaches one of our buckets.

    A named secondary bucket means the play generalizes across our list rather
    than fitting one segment by luck.
    """
    if audience is None:
        return 50, "No audience fit computed."
    if audience.secondary_bucket_id:
        return 82, f"Carries to {audience.bucket_name}, with a viable second bucket."
    return 66, f"Carries to {audience.bucket_name} only — single-bucket fit."


def risk_index(critique: Critique | None) -> int:
    """Weighted severity of the critique, 0-100. Higher means more exposed.

    Severity-weighted rather than a raw count, so three `low` notes never
    outrank one `high` — and capped so a thorough critic can't push a sound
    campaign to 100 by listing six minor things.
    """
    if critique is None or not critique.weaknesses:
        return 0
    weights = [_SEVERITY_WEIGHT.get(w.severity, 40) for w in critique.weaknesses]
    peak = max(weights)
    # Peak severity sets the floor; the rest add pressure with diminishing weight.
    rest = sum(sorted(weights, reverse=True)[1:])
    return _clamp(peak + rest * 0.25)


def build_scorecard(
    judged: JudgedScores | None,
    critique: Critique | None,
    strategy: StrategyAnalysis,
    audience: AudienceFit | None,
    trend: TrendVerdict | None,
    neighbors: list[Neighbor],
    bucket_channels: list[str],
) -> Scorecard:
    """Blend computed + judged dimensions into the scorecard the charts render."""
    ch_score, ch_why = channel_fit(strategy, audience, bucket_channels)
    tm_score, tm_why = timing_fit(trend)
    nv_score, nv_why = novelty(neighbors)
    au_score, au_why = audience_fit_score(audience)

    dims: list[ScoreDimension] = [
        ScoreDimension(key="audience_fit", label="Audience fit", score=au_score, rationale=au_why, computed=True),
        ScoreDimension(key="channel_fit", label="Channel fit", score=ch_score, rationale=ch_why, computed=True),
        ScoreDimension(key="timing_fit", label="Timing", score=tm_score, rationale=tm_why, computed=True),
        ScoreDimension(key="novelty", label="Novelty vs our memory", score=nv_score, rationale=nv_why, computed=True),
    ]

    if judged is not None:
        dims += [
            ScoreDimension(key="hook_strength", label="Hook strength", score=judged.hook_strength),
            ScoreDimension(key="craft", label="Craft", score=judged.craft),
            ScoreDimension(key="originality", label="Originality", score=judged.originality),
            ScoreDimension(key="brand_fit", label="Brand fit", score=judged.brand_fit),
            ScoreDimension(key="replicability", label="Replicability for us", score=judged.replicability),
            ScoreDimension(
                key="evidence_strength",
                label="Evidence strength",
                score=judged.evidence_strength,
                rationale="How much of this analysis rests on visible evidence rather than inference.",
            ),
        ]

    by_key = {d.key: d.score for d in dims}
    total_w = sum(w for k, w in _RELEVANCE_WEIGHTS.items() if k in by_key)
    if total_w:
        relevance = sum(by_key[k] * w for k, w in _RELEVANCE_WEIGHTS.items() if k in by_key) / total_w
    else:
        relevance = 50.0

    # A campaign we cannot honestly read is not a campaign we can confidently
    # call relevant — thin evidence pulls the headline toward neutral.
    ev = by_key.get("evidence_strength")
    if ev is not None and ev < 50:
        relevance = relevance * (0.75 + 0.25 * ev / 50)

    return Scorecard(
        relevance_to_us=_clamp(relevance),
        dimensions=dims,
        risk_index=risk_index(critique),
        scoring_note=(judged.scoring_note if judged else ""),
    )
