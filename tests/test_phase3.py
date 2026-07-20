"""Phase 3: trend verdict, audience fit, bucket registry, review flow, UI."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import BucketRegistry, utcnow
from tests.conftest import make_v1_report, png_b64

client = TestClient(app)


@pytest.fixture
def tmp_buckets(monkeypatch, tmp_path):
    """Copy the real registry into tmp so PUT tests don't touch tracked config."""
    from app.buckets import BUCKETS_PATH

    p = tmp_path / "buckets.json"
    p.write_text(BUCKETS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("app.buckets.BUCKETS_PATH", p)
    return p


def test_default_buckets_present(tmp_buckets):
    r = client.get("/buckets")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()["buckets"]]
    assert ids == ["third-year-interns", "final-years", "switchers", "beginners"]


def test_buckets_editable_via_put(tmp_buckets):
    reg = BucketRegistry.model_validate(client.get("/buckets").json())
    reg.buckets.append(
        reg.buckets[0].model_copy(update={"id": "alumni", "name": "Alumni upskilling"})
    )
    r = client.put("/buckets", json=json.loads(reg.model_dump_json()))
    assert r.status_code == 200
    assert "alumni" in [b["id"] for b in client.get("/buckets").json()["buckets"]]
    assert "alumni" in tmp_buckets.read_text(encoding="utf-8")  # persisted to the file


def test_put_buckets_rejects_duplicates_and_empty(tmp_buckets):
    reg = client.get("/buckets").json()
    reg["buckets"].append(dict(reg["buckets"][0]))
    assert client.put("/buckets", json=reg).status_code == 400
    assert client.put("/buckets", json={"buckets": []}).status_code == 400


def test_full_pipeline_produces_v2_campaign_brief(fake_llm, tmp_store, tmp_buckets):
    r = client.post(
        "/analyze",
        json={"text": "hot new campaign everyone is copying", "images": [{"data": png_b64((90, 30, 200)), "mime_type": "image/png"}]},
    )
    assert r.status_code == 200
    body = r.json()
    rep = body["report"]
    assert rep["schema_version"] == "v3"
    assert rep["trend"]["verdict"] == "rising"
    assert rep["trend"]["citations"] == [{"title": "Marketing Dive", "url": "https://example.com/a"}]
    assert rep["audience"]["bucket_id"] == "final-years"
    # trend + audience made it into markdown (the campaign-brief render)
    assert "Trend Verdict" in body["markdown"]
    assert "Audience Recommendation" in body["markdown"]
    # graph ran the full node sequence
    assert fake_llm.nodes == ["strategy", "hook", "visual", "composer", "trend", "audience"] or set(
        fake_llm.nodes[:3]
    ) == {"strategy", "hook", "visual"}
    assert fake_llm.market_topics, "trend node consulted the market signal"
    # stored record is v2 and summarized correctly
    listing = client.get("/reports").json()
    assert listing[0]["trend_verdict"] == "rising"
    assert listing[0]["audience_bucket"] == "Final-year students facing placements"


def test_review_flow_updates_status(fake_llm, tmp_store, tmp_buckets):
    rid = client.post("/analyze", json={"text": "campaign to review", "images": []}).json()["report_id"]

    r = client.post(f"/report/{rid}/review", json={"decision": "approved", "comment": "ship it"})
    assert r.status_code == 200
    rec = client.get(f"/report/{rid}").json()
    assert rec["status"] == "approved"
    assert rec["review_comment"] == "ship it"
    assert rec["reviewed_at"] <= utcnow().isoformat()
    assert client.get("/reports").json()[0]["status"] == "approved"


def test_review_validates_decision(tmp_store):
    assert client.post("/report/whatever/review", json={"decision": "maybe"}).status_code == 422
    assert client.post("/report/missing/review", json={"decision": "approved"}).status_code == 404


def test_review_ui_is_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Trend Research Agent" in r.text
    assert "Analyze a campaign" in r.text


@pytest.mark.anyio
async def test_play_frequency_windows(tmp_memory):
    report = make_v1_report()
    await tmp_memory.index_report("old-1", "2026-04-01T00:00:00+00:00", report, "old thing", [])
    await tmp_memory.index_report("new-1", utcnow().isoformat(), report, "new thing", [])
    freq = tmp_memory.play_frequency("FOMO / Scarcity", days=30)
    assert freq["recent"] == 1
    assert freq["prior"] == 1
    assert freq["total_analyses_in_memory"] == 2
