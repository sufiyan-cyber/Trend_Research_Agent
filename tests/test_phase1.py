"""Phase 1: parallel specialists, skill packs, palette, persistence."""

import pytest
from fastapi.testclient import TestClient

from app.config import load_skill_pack
from app.graph import graph, initial_state
from app.main import app
from app.palette import extract_palette
from app.render import report_to_markdown
from app.schemas import CampaignReportV1, ImagePayload
from tests.conftest import FIXTURE_CORE, FIXTURE_HOOK, FIXTURE_STRATEGY, FIXTURE_VISUAL, png_b64

client = TestClient(app)


def test_palette_extraction_finds_dominant_colors():
    imgs = [ImagePayload(data=png_b64((255, 0, 0))), ImagePayload(data=png_b64((0, 0, 255)))]
    palette = extract_palette(imgs)
    hexes = {c.hex for c in palette}
    assert "#ff0000" in hexes and "#0000ff" in hexes
    assert abs(sum(c.coverage_pct for c in palette) - 100) < 1


def test_palette_skips_undecodable_images():
    assert extract_palette([ImagePayload(data="aGVsbG8=", mime_type="image/png")]) == []


def test_skill_packs_load_for_all_specialists():
    for name in ("strategy", "hook", "visual"):
        assert len(load_skill_pack(name)) > 500, f"skill pack '{name}' missing or too thin"


def test_new_skill_pack_doc_is_picked_up_with_zero_code_change(monkeypatch, tmp_path):
    packs = tmp_path / "skill_packs" / "strategy"
    packs.mkdir(parents=True)
    (packs / "a_base.md").write_text("base doc", encoding="utf-8")
    monkeypatch.setattr("app.config.SKILL_PACKS_DIR", tmp_path / "skill_packs")
    before = load_skill_pack("strategy")
    (packs / "b_new_taxonomy.md").write_text("NEW PLAY: reverse-FOMO", encoding="utf-8")
    after = load_skill_pack("strategy")
    assert "reverse-FOMO" not in before
    assert "reverse-FOMO" in after  # dropped-in doc reaches the prompt, no code touched


@pytest.mark.anyio
async def test_graph_runs_all_specialists_and_composes(fake_llm):
    state = await graph.ainvoke(
        initial_state("some campaign", [ImagePayload(data=png_b64((10, 200, 30)))], "test-report-1")
    )
    assert set(fake_llm.nodes) == {"strategy", "hook", "visual", "composer", "trend", "audience", "critique"}
    report = state["report"]
    assert isinstance(report, CampaignReportV1)
    assert report.core == FIXTURE_CORE
    assert report.strategy == FIXTURE_STRATEGY
    assert report.hook_copy == FIXTURE_HOOK
    assert report.visual == FIXTURE_VISUAL
    assert report.palette, "programmatic palette should be attached"
    # three specialists + composer + trend search + trend verdict + audience fit + critique
    assert len(state["usages"]) == 8
    assert state["existing_report_id"] is None


def test_analyze_persists_and_report_is_retrievable(fake_llm, tmp_store):
    r = client.post("/analyze", json={"text": "placement season ad", "images": [{"data": png_b64(), "mime_type": "image/png"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["schema_version"] == "v3"
    assert body["report"]["strategy"]["primary_play"] == "FOMO / Scarcity"
    assert len(body["usages"]) == 8

    rid = body["report_id"]
    stored = client.get(f"/report/{rid}")
    assert stored.status_code == 200
    assert stored.json()["report"]["core"]["takeaway_for_us"] == FIXTURE_CORE.takeaway_for_us
    assert stored.json()["input"]["images"][0]["sha256"]

    md = client.get(f"/report/{rid}", params={"format": "markdown"})
    assert md.status_code == 200
    assert "# Campaign Deconstruction" in md.text

    listing = client.get("/reports")
    assert listing.status_code == 200
    assert any(item["report_id"] == rid for item in listing.json())
    assert listing.json()[0]["primary_play"] == "FOMO / Scarcity"


def test_v1_markdown_includes_specialist_detail():
    report = CampaignReportV1(
        core=FIXTURE_CORE,
        strategy=FIXTURE_STRATEGY,
        hook_copy=FIXTURE_HOOK,
        visual=FIXTURE_VISUAL,
        palette=[],
    )
    md = report_to_markdown(report)
    assert "## Specialist Detail" in md
    assert "FOMO / Scarcity" in md
    assert "Your seniors already know this" in md
