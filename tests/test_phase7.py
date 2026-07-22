"""Phase 7: emotion normalization + the per-bucket trigger playbook."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analytics import emotion_mix
from app.emotions import DESIRE, NEGATIVE, POSITIVE, VALENCE, normalize
from app.main import app
from app.render import report_to_markdown
from app.schemas import AudienceDraft, TriggerPlay
from tests.conftest import FIXTURE_AUDIENCE, FIXTURE_PLAYBOOK, make_v1_report

client = TestClient(app)


# --- taxonomy + normalizer ---------------------------------------------------


def test_taxonomy_has_no_duplicates_across_groups():
    all_terms = POSITIVE + NEGATIVE + DESIRE
    assert len(all_terms) == len(set(all_terms)), "an emotion must live in exactly one valence group"
    assert len(VALENCE) == len(all_terms)


@pytest.mark.parametrize(
    ("raw", "canon", "valence"),
    [
        ("FOMO", "fomo", "desire"),
        ("insecurity", "anxiety", "negative"),  # the spelling our own fixtures use
        ("Fear of missing out", "fomo", "desire"),
        ("aspiration", "aspiration", "desire"),
        ("Pride", "pride", "positive"),
        ("outrage", "anger", "negative"),
        ("status anxiety", "anxiety", "negative"),  # synonym beats shorter containment
        ("greed (value seeking)", "value seeking", "desire"),
        ("melancholy", "melancholy", "unclassified"),  # off-map degrades visibly, not silently
        ("", "", "unclassified"),
    ],
)
def test_normalize(raw, canon, valence):
    assert normalize(raw) == (canon, valence)


def test_normalize_prefers_longest_canonical_match():
    # "self-improvement" contains "self" of nothing else, but "desire" strings
    # like "desire for self-improvement" must resolve to the longer term.
    assert normalize("a desire for self-improvement")[0] == "self-improvement"


# --- schema ------------------------------------------------------------------


def test_playbook_cannot_be_empty():
    with pytest.raises(ValidationError):
        AudienceDraft(fit=FIXTURE_AUDIENCE, trigger_playbook=[])


def test_avoid_is_a_legal_playbook_entry():
    play = TriggerPlay(
        bucket_id="beginners", bucket_name="Complete beginners", fit="avoid",
        how_to_fire="No peer cohort — reads as gatekeeping.", example_hook="",
    )
    assert play.fit == "avoid" and play.example_hook == ""


# --- pipeline ----------------------------------------------------------------


def test_analyze_attaches_emotion_profile_and_playbook(fake_llm, tmp_store, tmp_memory):
    body = client.post("/analyze", json={"text": "placement season fomo ad", "images": []}).json()
    rep = body["report"]

    em = rep["emotion"]
    assert em["primary"] == "anxiety", "fixture's 'insecurity' must normalize to canon"
    assert em["valence"] == "negative"
    assert em["raw"] == "insecurity"
    assert em["trigger_element"]

    plays = rep["trigger_playbook"]
    assert len(plays) == 2
    assert {p["fit"] for p in plays} == {"strong", "avoid"}


def test_audience_briefing_names_the_trigger_to_transfer(fake_llm, tmp_store, tmp_memory):
    client.post("/analyze", json={"text": "trigger transfer briefing check", "images": []})
    briefing = fake_llm.messages["audience"][-1].content
    assert "Detected emotional trigger" in briefing
    assert "anxiety" in briefing, "normalized canon must be in the briefing, not just the raw spelling"
    assert "valence: negative" in briefing


def test_memory_payload_stores_canonical_emotion(fake_llm, tmp_store, tmp_memory):
    client.post("/analyze", json={"text": "canonical emotion payload check", "images": []})
    payloads = tmp_memory.all_payloads()
    assert payloads[0]["emotion"] == "anxiety"
    assert payloads[0]["emotion_valence"] == "negative"
    assert payloads[0]["emotion_raw"] == "insecurity"


def test_emotion_and_playbook_reach_markdown(fake_llm, tmp_store, tmp_memory):
    rid = client.post("/analyze", json={"text": "emotion markdown check", "images": []}).json()["report_id"]
    md = client.get(f"/report/{rid}?format=markdown").text
    assert "## Emotional Trigger: anxiety (negative)" in md
    assert "How to pull this trigger in our buckets" in md
    assert "AVOID" in md, "the honest 'no' must survive into the export"
    assert "Caution:" in md


def test_report_without_emotion_still_renders():
    md = report_to_markdown(make_v1_report())
    assert "Emotional Trigger:" not in md  # pre-Phase-7 reports stay valid


# --- cache policy ------------------------------------------------------------


def test_nothing_the_ui_consumes_is_cacheable(fake_llm, tmp_store, tmp_memory):
    """Stale-browser class of bugs: documents and JSON must never be reused
    without asking the server; static assets may revalidate (304) but not
    be assumed fresh. Both regressions shipped once — hence this test."""
    assert client.get("/").headers["cache-control"] == "no-store"
    assert client.get("/dashboard").headers["cache-control"] == "no-store"
    assert client.get("/reports").headers["cache-control"] == "no-store"
    assert client.get("/analytics").headers["cache-control"] == "no-store"
    assert client.get("/static/charts.js").headers["cache-control"] == "no-cache"


def test_sw_route_serves_a_self_destruct_worker():
    """A leftover service worker on this port was serving stale pages. The
    browser polls /sw.js (with a ?v= query) to check for updates; we answer
    with a worker that clears caches and unregisters itself, so the rogue
    worker dies on the next check instead of getting a 404 that keeps it alive."""
    r = client.get("/sw.js?v=2")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-store"
    assert "self.registration.unregister()" in r.text
    assert "caches.delete" in r.text


# --- analytics ---------------------------------------------------------------


def test_emotion_mix_folds_spellings_and_reports_valence():
    payloads = [{"emotion": e} for e in ["FOMO", "fomo", "fear of missing out", "insecurity", "anxiety", "pride"]]
    mix = emotion_mix(payloads, top=5)
    by_label = {i["label"]: i for i in mix["items"]}
    assert by_label["fomo"]["value"] == 3, "three spellings of fomo must count as one emotion"
    assert by_label["anxiety"]["value"] == 2
    assert by_label["fomo"]["valence"] == "desire"
    assert mix["valence_totals"] == {"positive": 1, "negative": 2, "desire": 3}
