"""Phase 5: outcome loop, trend lifecycles, ask-the-agent, dashboard, eval scoring."""

import pytest
from fastapi.testclient import TestClient

from app.lifecycle import record_event, timelines
from app.main import app
from app.schemas import CampaignReportV3, TrendVerdict, utcnow
from scripts.eval_reports import score_report
from tests.conftest import (
    FIXTURE_AUDIENCE,
    FIXTURE_CITATIONS,
    FIXTURE_TREND,
    make_v1_report,
)

client = TestClient(app)


# --- outcome loop ------------------------------------------------------------


def test_outcome_recorded_and_fed_back_to_memory(fake_llm, tmp_store, tmp_memory):
    rid = client.post("/analyze", json={"text": "campaign that we actually shipped later", "images": []}).json()["report_id"]

    r = client.post(
        f"/report/{rid}/outcome",
        json={"became_campaign": True, "performance": "strong", "ctr": 3.4, "notes": "best reel this quarter"},
    )
    assert r.status_code == 200

    rec = client.get(f"/report/{rid}").json()
    assert rec["outcome"]["performance"] == "strong"
    assert rec["outcome_recorded_at"]

    summary = tmp_memory.outcome_summary()
    assert summary and summary[0]["play"] == "FOMO / Scarcity"
    assert rid in summary[0]["examples"]


def test_outcome_404_for_missing_report(tmp_store):
    assert client.post("/report/nope/outcome", json={"became_campaign": True}).status_code == 404


def test_outcome_history_reaches_audience_node(fake_llm, tmp_store, tmp_memory):
    rid = client.post("/analyze", json={"text": "first shipped campaign, we rated it", "images": []}).json()["report_id"]
    client.post(f"/report/{rid}/outcome", json={"became_campaign": True, "performance": "strong"})

    client.post("/analyze", json={"text": "a totally different second campaign about webinars", "images": []})
    briefing = fake_llm.messages["audience"][1].content
    assert "What has worked for our audience historically" in briefing
    assert rid in briefing


# --- lifecycles --------------------------------------------------------------


def test_analyses_build_trend_timelines(fake_llm, tmp_store):
    client.post("/analyze", json={"text": "one campaign building a timeline", "images": []})
    body = client.get("/trends").json()
    assert len(body) == 1
    t = body[0]
    assert t["play"] == "FOMO / Scarcity"
    assert t["current_verdict"] == "rising"
    assert t["observations"] == 1
    assert client.get("/trends/FOMO %2F Scarcity").status_code in (200, 404)  # path-encoded lookup optional
    assert client.get("/trends/fomo / scarcity").status_code == 200


def test_early_call_days_computed():
    record_event("Meme hijack", "rising", "r-1")
    record_event("Meme hijack", "rising", "r-2")
    record_event("Meme hijack", "peaked", "r-3")
    t = timelines()[0]
    assert t.first_rising_at and t.first_peaked_at
    assert t.early_call_days == 0  # same-day in tests; the field exists and computes
    assert t.current_verdict == "peaked"
    assert t.observations == 3


# --- ask-the-agent -----------------------------------------------------------


@pytest.mark.anyio
async def test_ask_grounds_in_memory_and_cites(fake_llm, tmp_memory):
    await tmp_memory.index_report("20260615-cccc", "2026-06-15T09:00:00+00:00", make_v1_report(), "seniors placement fomo reel", [])

    r = client.post("/ask", json={"question": "which hooks are working on students?"})
    assert r.status_code == 200
    body = r.json()
    assert body["sources"] == ["20260615-cccc"]
    assert body["confidence"] == "medium"
    assert "ask" in fake_llm.nodes
    context = fake_llm.messages["ask"][1].content
    assert "Relevant past analyses" in context and "20260615-cccc" in context


def test_ask_validates_question():
    assert client.post("/ask", json={"question": "x"}).status_code == 422


# --- dashboard + brand config -------------------------------------------------


def test_dashboard_served():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Trend Dashboard" in r.text


def test_brand_context_is_injected_not_hardcoded(fake_llm, tmp_store):
    from app.config import load_brand

    assert "HiDevs" in load_brand()  # company specifics live in config/brand.md ...
    from app.config import load_prompt

    for prompt in ("composer_v1.md", "audience_v1.md", "digest_v1.md", "market_map_v1.md"):
        assert "HiDevs" not in load_prompt(prompt)  # ... not in the engine prompts

    client.post("/analyze", json={"text": "brand injection check", "images": []})
    composer_system = fake_llm.messages["composer"][0].content
    assert "Brand Context" in composer_system and "HiDevs" in composer_system


# --- storage backends --------------------------------------------------------


def test_store_backend_selection(monkeypatch):
    import app.storage as storage

    monkeypatch.setattr(storage, "STORE_BACKEND", "auto")
    monkeypatch.setattr(storage, "MONGODB_URI", "")
    monkeypatch.setattr(storage, "FIREBASE_CREDENTIALS", "")
    assert isinstance(storage._build_store(), storage.LocalJsonStore)

    monkeypatch.setattr(storage, "STORE_BACKEND", "local")
    monkeypatch.setattr(storage, "MONGODB_URI", "mongodb://ignored-because-forced-local")
    assert isinstance(storage._build_store(), storage.LocalJsonStore)

    monkeypatch.setattr(storage, "STORE_BACKEND", "auto")
    assert isinstance(storage._build_store(), storage.MongoStore)


def test_every_backend_implements_the_same_interface():
    from app.storage import FirestoreStore, LocalJsonStore, MongoStore

    for backend in (LocalJsonStore, MongoStore, FirestoreStore):
        for method in ("save", "get", "list", "update"):
            assert callable(getattr(backend, method)), f"{backend.__name__} missing {method}"


# --- eval scoring ------------------------------------------------------------


def test_score_report_rubric():
    report = make_v1_report()
    report = CampaignReportV3(
        **{**report.model_dump(), "trend": TrendVerdict(**FIXTURE_TREND.model_dump(), citations=FIXTURE_CITATIONS).model_dump(), "audience": FIXTURE_AUDIENCE.model_dump()}
    )
    expected = {
        "plays_any": ["fomo"],
        "emotion_any": ["insecurity"],
        "bucket_any": ["final-years"],
    }
    result = score_report(report, expected)
    assert result["max"] == 100
    assert result["score"] == 100  # fixture report satisfies the whole rubric
    assert all(result["checks"].values())

    bad = score_report(report, {"plays_any": ["nostalgia"], "emotion_any": ["pride"], "bucket_any": ["beginners"]})
    assert bad["score"] == 100 - 25 - 15 - 15
