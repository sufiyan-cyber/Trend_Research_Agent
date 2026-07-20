"""API validation and schema-shape tests — no LLM, no API key."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.render import core_to_markdown
from app.schemas import CampaignReport
from tests.conftest import FIXTURE_CORE, png_b64

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_analyze_rejects_empty_input():
    r = client.post("/analyze", json={"text": "", "images": []})
    assert r.status_code == 400
    assert "Provide text" in r.json()["detail"]


def test_analyze_rejects_bad_base64():
    r = client.post("/analyze", json={"text": "x", "images": [{"data": "not-base64!!!", "mime_type": "image/png"}]})
    assert r.status_code == 400
    assert "not valid base64" in r.json()["detail"]


def test_analyze_rejects_malformed_body():
    r = client.post("/analyze", json={"images": "nope"})
    assert r.status_code == 422


def test_form_rejects_non_image_upload():
    r = client.post(
        "/analyze/form",
        data={"text": "ctx"},
        files={"images": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
    assert "only image uploads" in r.json()["detail"]


def test_analyze_without_key_returns_503(monkeypatch, tmp_store):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/analyze", json={"text": "why did this ad work?", "images": [{"data": png_b64(), "mime_type": "image/png"}]})
    assert r.status_code == 503
    assert "API key" in r.json()["detail"]


def test_core_schema_is_v0_plus_seen_before():
    # v0's seven fields, plus the additive Phase 2 memory section.
    assert list(CampaignReport.model_fields) == [
        "campaign_idea",
        "how_it_was_run",
        "hook",
        "emotional_trigger",
        "visual_notes",
        "why_it_worked",
        "takeaway_for_us",
        "seen_before",
    ]


def test_core_markdown_has_all_sections():
    md = core_to_markdown(FIXTURE_CORE)
    for heading in [
        "# Campaign Deconstruction",
        "## The Campaign Idea",
        "## How It Was Run",
        "## The Hook",
        "## Emotional Trigger",
        "## Visual Notes",
        "## Why It Worked",
        "## Takeaway for Us",
    ]:
        assert heading in md


def test_missing_report_404():
    r = client.get("/report/does-not-exist")
    assert r.status_code == 404
