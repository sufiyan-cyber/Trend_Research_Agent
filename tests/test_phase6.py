"""Phase 6: the critique node (the negative section) + scorecard + analytics.

The point of these tests is the anti-sycophancy contract. A model that decides
everything is wonderful should fail here, not ship.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analytics import (
    emotion_mix,
    plays_leaderboard,
    relevance_distribution,
    risk_profile,
    verdict_mix_by_week,
)
from app.main import app
from app.render import report_to_markdown
from app.schemas import (
    AudienceFit,
    Critique,
    JudgedScores,
    Neighbor,
    TrendVerdict,
    Weakness,
    utcnow,
)
from app.scoring import build_scorecard, channel_fit, novelty, risk_index, timing_fit
from tests.conftest import FIXTURE_AUDIENCE, FIXTURE_CRITIQUE, FIXTURE_STRATEGY, make_v1_report

client = TestClient(app)


# --- the schema is the first line of defence ---------------------------------


def test_critique_cannot_be_empty():
    """'Nothing negative to report' must be structurally impossible to emit.

    This is the load-bearing anti-sycophancy mechanism: prompts can be argued
    with, a min_length cannot.
    """
    with pytest.raises(ValidationError):
        Critique(
            weaknesses=[],
            why_it_might_not_work="It's great.",
            risk_if_we_copy_it="None.",
            brand_safety_flag="None identified",
            survivorship_check="n/a",
            what_we_could_not_verify="nothing",
            confidence_in_positive_read="high",
        )


def test_critique_requires_at_least_two_weaknesses():
    one = [Weakness(issue="i", severity="low", evidence="e", mitigation="m")]
    with pytest.raises(ValidationError):
        Critique(
            weaknesses=one,
            why_it_might_not_work="x",
            risk_if_we_copy_it="x",
            brand_safety_flag="x",
            survivorship_check="x",
            what_we_could_not_verify="x",
            confidence_in_positive_read="medium",
        )


# --- the critique node runs and lands in the report --------------------------


def test_analyze_produces_a_critique_and_scorecard(fake_llm, tmp_store, tmp_memory):
    body = client.post("/analyze", json={"text": "a campaign worth pulling apart", "images": []}).json()
    report = body["report"]

    assert "critique" in fake_llm.nodes, "the critique node must run on every analysis"
    assert report["schema_version"] == "v3"

    cr = report["critique"]
    assert len(cr["weaknesses"]) >= 2
    assert cr["what_we_could_not_verify"]
    assert cr["confidence_in_positive_read"] in ("low", "medium", "high")

    sc = report["scorecard"]
    assert 0 <= sc["relevance_to_us"] <= 100
    assert sc["risk_index"] > 0
    assert {d["key"] for d in sc["dimensions"]} >= {"audience_fit", "channel_fit", "timing_fit", "novelty"}


def test_critic_sees_the_positive_read_it_is_reviewing(fake_llm, tmp_store, tmp_memory):
    """The critic must receive the composed report, not just the raw material —
    it can only flag over-claiming if it can see the claims."""
    client.post("/analyze", json={"text": "campaign under review", "images": []})
    briefing = fake_llm.messages["critique"][-1].content
    assert "composed deconstruction" in briefing
    assert "claim under review" in briefing
    assert "Results data" in briefing, "the critic must be told there is no results data"


def test_critique_reaches_markdown_and_api(fake_llm, tmp_store, tmp_memory):
    rid = client.post("/analyze", json={"text": "markdown rendering check", "images": []}).json()["report_id"]
    md = client.get(f"/report/{rid}?format=markdown").text
    assert "## The Case Against" in md
    assert "## Scorecard" in md
    assert "Survivorship check" in md
    assert "What we could not verify" in md


def test_report_without_critique_still_renders(tmp_store):
    """Reports stored before this phase must keep working — every new field is optional."""
    md = report_to_markdown(make_v1_report())
    assert "Campaign Deconstruction" in md
    assert "The Case Against" not in md


# --- computed scoring --------------------------------------------------------


def test_channel_fit_rewards_channels_we_actually_publish_on():
    ours = ["Instagram", "LinkedIn", "WhatsApp community", "email"]
    hit, _ = channel_fit(FIXTURE_STRATEGY, None, ours)

    strat = FIXTURE_STRATEGY.model_copy(update={"channel_inference": "Billboard / OOH placement (inference)"})
    miss, why = channel_fit(strat, None, ours)

    assert hit > miss, "a format native to our channels must outscore one that is not"
    assert miss < 40 and "no presence" in why


def test_timing_fit_prefers_rising_over_fading():
    def verdict(v, conf="high"):
        return TrendVerdict(
            verdict=v, confidence=conf, reasoning="r", memory_frequency="m", market_signal="s"
        )

    rising, _ = timing_fit(verdict("rising"))
    peaked, _ = timing_fit(verdict("peaked"))
    fading, _ = timing_fit(verdict("fading"))
    assert rising > peaked > fading

    # Low confidence must not swing the headline as hard as high confidence.
    assert timing_fit(verdict("fading", "low"))[0] > fading


def test_novelty_is_inverse_of_closest_memory_match():
    fresh, _ = novelty([])
    near, _ = novelty([Neighbor(report_id="a", analyzed_at="2026-01-01", similarity=0.97)])
    far, _ = novelty([Neighbor(report_id="b", analyzed_at="2026-01-01", similarity=0.58)])
    assert fresh > far > near


def test_risk_index_weights_severity_not_count():
    def crit(sevs):
        return Critique(
            weaknesses=[Weakness(issue="i", severity=s, evidence="e", mitigation="m") for s in sevs],
            why_it_might_not_work="x",
            risk_if_we_copy_it="x",
            brand_safety_flag="x",
            survivorship_check="x",
            what_we_could_not_verify="x",
            confidence_in_positive_read="low",
        )

    assert risk_index(crit(["high", "low"])) > risk_index(crit(["low", "low", "low", "low"]))
    assert risk_index(None) == 0


def test_thin_evidence_pulls_relevance_down():
    """A campaign we cannot honestly read should not score as confidently relevant."""
    common = dict(
        critique=FIXTURE_CRITIQUE.critique,
        strategy=FIXTURE_STRATEGY,
        audience=FIXTURE_AUDIENCE,
        trend=TrendVerdict(
            verdict="rising", confidence="high", reasoning="r", memory_frequency="m", market_signal="s"
        ),
        neighbors=[],
        bucket_channels=["Instagram", "LinkedIn"],
    )
    strong = build_scorecard(judged=FIXTURE_CRITIQUE.scores.model_copy(update={"evidence_strength": 85}), **common)
    thin = build_scorecard(judged=FIXTURE_CRITIQUE.scores.model_copy(update={"evidence_strength": 10}), **common)
    assert strong.relevance_to_us > thin.relevance_to_us


def test_scorecard_marks_which_numbers_were_computed():
    sc = build_scorecard(
        judged=FIXTURE_CRITIQUE.scores,
        critique=FIXTURE_CRITIQUE.critique,
        strategy=FIXTURE_STRATEGY,
        audience=FIXTURE_AUDIENCE,
        trend=None,
        neighbors=[],
        bucket_channels=["Instagram"],
    )
    computed = {d.key for d in sc.dimensions if d.computed}
    judged = {d.key for d in sc.dimensions if not d.computed}
    assert computed == {"audience_fit", "channel_fit", "timing_fit", "novelty"}
    assert "brand_fit" in judged and "evidence_strength" in judged


def test_scorecard_survives_a_missing_critique():
    sc = build_scorecard(
        judged=None, critique=None, strategy=FIXTURE_STRATEGY, audience=None,
        trend=None, neighbors=[], bucket_channels=[],
    )
    assert 0 <= sc.relevance_to_us <= 100
    assert sc.risk_index == 0


# --- analytics ---------------------------------------------------------------


def test_verdict_mix_emits_an_unbroken_week_axis():
    events = [{"at": utcnow().isoformat(), "verdict": "rising", "play": "p", "report_id": "r"}]
    mix = verdict_mix_by_week(events, weeks=6)
    assert len(mix["labels"]) == 6
    assert sorted(mix["labels"]) == mix["labels"], "weeks must run oldest to newest"
    assert {s["key"] for s in mix["series"]} == {"new", "rising", "peaked", "fading"}
    assert all(len(s["values"]) == 6 for s in mix["series"])
    assert mix["total"] == 1


def test_plays_leaderboard_reports_the_latest_verdict_per_play():
    payloads = [
        {"primary_play": "FOMO", "created_at": "2026-01-01", "trend_verdict": "new"},
        {"primary_play": "FOMO", "created_at": "2026-06-01", "trend_verdict": "peaked"},
        {"primary_play": "UGC bait", "created_at": "2026-03-01", "trend_verdict": "rising"},
    ]
    board = plays_leaderboard(payloads)
    top = board["items"][0]
    assert top["label"] == "FOMO" and top["value"] == 2
    assert top["verdict"] == "peaked", "must use the most recent observation, not the first"


def test_relevance_and_risk_aggregates():
    reports = [
        {"report": {"scorecard": {"relevance_to_us": 82, "risk_index": 60},
                    "critique": {"weaknesses": [{"severity": "high"}, {"severity": "low"}]}}},
        {"report": {"scorecard": {"relevance_to_us": 30, "risk_index": 40},
                    "critique": {"weaknesses": [{"severity": "medium"}]}}},
        {"report": {}},  # pre-Phase-6 report — must not break the aggregate
    ]
    rel = relevance_distribution(reports)
    assert rel["scored_reports"] == 2 and rel["mean"] == 56
    assert rel["values"][4] == 1 and rel["values"][1] == 1

    risk = risk_profile(reports)
    assert risk["values"] == [1, 1, 1]
    assert risk["total_weaknesses"] == 3 and risk["critiqued_reports"] == 2
    assert risk["mean_risk_index"] == 50


def test_emotion_mix_folds_the_tail_into_other():
    payloads = [{"emotion": e} for e in ["fomo"] * 3 + ["pride", "belonging", "envy", "guilt", "awe", "relief"]]
    mix = emotion_mix(payloads, top=3)
    assert mix["items"][0]["label"] == "fomo" and mix["items"][0]["value"] == 3
    assert mix["items"][-1]["label"] == "other"


def test_analytics_endpoint_serves_every_chart_series(fake_llm, tmp_store, tmp_memory):
    client.post("/analyze", json={"text": "something for the dashboard to chart", "images": []})
    an = client.get("/analytics").json()
    assert {"verdict_mix", "plays", "relevance", "risk", "emotions", "reports_total"} <= an.keys()
    assert an["reports_total"] >= 1
    assert an["relevance"]["scored_reports"] >= 1
    assert an["risk"]["total_weaknesses"] >= 2
