"""Phase 2: dedupe short-circuit, seen-before recall, memory persistence, backfill."""

import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.memory import MemoryIndex, analysis_summary_text
from app.schemas import ImagePayload, utcnow
from app.storage import image_hashes_of, make_record
from tests.conftest import fake_embed_texts, make_v1_report, png_b64

client = TestClient(app)


async def seed_memory_and_store(tmp_memory, tmp_store, report_id: str, input_text: str, image_b64: str | None):
    """Put one finished analysis into both memory and the report store."""
    images = [ImagePayload(data=image_b64)] if image_b64 else []
    report = make_v1_report()
    await tmp_store.save(make_record(report_id, input_text, images, report, []))
    await tmp_memory.index_report(
        report_id=report_id,
        created_at=utcnow().isoformat(),
        report=report,
        input_text=input_text,
        image_hashes=image_hashes_of(images),
    )


@pytest.mark.anyio
async def test_dedupe_by_image_hash_short_circuits(tmp_memory, tmp_store, fake_llm):
    img = png_b64((7, 99, 200))
    await seed_memory_and_store(tmp_memory, tmp_store, "20260701-aaaa", "old context", img)

    r = client.post("/analyze", json={"text": "totally different words here", "images": [{"data": img, "mime_type": "image/png"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["deduped"] is True
    assert body["report_id"] == "20260701-aaaa"
    assert fake_llm.nodes == []  # never analyzed twice — zero model calls


@pytest.mark.anyio
async def test_dedupe_by_near_identical_text(tmp_memory, tmp_store, fake_llm):
    text = "Blinkit's match-day ambush ad with the free delivery hook during India vs Pakistan"
    await seed_memory_and_store(tmp_memory, tmp_store, "20260702-bbbb", text, None)

    r = client.post("/analyze", json={"text": text, "images": []})
    assert r.status_code == 200
    assert r.json()["deduped"] is True
    assert r.json()["report_id"] == "20260702-bbbb"
    assert fake_llm.nodes == []


@pytest.mark.anyio
async def test_fresh_input_is_not_deduped_and_gets_indexed(tmp_memory, tmp_store, fake_llm):
    r = client.post("/analyze", json={"text": "a completely new campaign about gardening tools", "images": []})
    assert r.status_code == 200
    assert r.json()["deduped"] is False
    assert tmp_memory.count() == 1  # finished analysis entered memory


@pytest.mark.anyio
async def test_seen_before_neighbors_reach_composer_and_response(tmp_memory, tmp_store, fake_llm):
    # Seed a past analysis whose summary shares play/hook/emotion vocabulary.
    past = make_v1_report()
    await tmp_memory.index_report(
        report_id="20260615-cccc",
        created_at="2026-06-15T09:00:00+00:00",
        report=past,
        input_text="seniors placement fomo reel",
        image_hashes=[],
    )

    r = client.post("/analyze", json={"text": "new campaign, fresh screenshots", "images": [{"data": png_b64((250, 250, 0)), "mime_type": "image/png"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["deduped"] is False

    neighbors = body["report"]["neighbors"]
    assert neighbors and neighbors[0]["report_id"] == "20260615-cccc"

    composer_briefing = fake_llm.messages["composer"][1].content
    assert "20260615-cccc" in composer_briefing  # memory reached the composer prompt
    assert "Similar campaigns we've analyzed before" in composer_briefing


@pytest.mark.anyio
async def test_memory_survives_restart(tmp_path):
    path = str(tmp_path / "qdrant-restart")
    mem1 = MemoryIndex(path=path)
    import app.memory as memory_mod

    memory_mod.embed_texts = fake_embed_texts  # ensure fake in this direct usage
    await mem1.index_report(
        report_id="r-1",
        created_at=utcnow().isoformat(),
        report=make_v1_report(),
        input_text="some persisted campaign",
        image_hashes=["deadbeef"],
    )
    mem1.close()

    mem2 = MemoryIndex(path=path)
    assert mem2.count() == 1
    dup = await mem2.find_duplicate("", ["deadbeef"])
    assert dup and dup["report_id"] == "r-1"
    mem2.close()


@pytest.mark.anyio
async def test_backfill_ingests_then_skips_duplicates(tmp_memory, tmp_store, fake_llm, tmp_path):
    root = tmp_path / "campaigns"
    camp = root / "blinkit_match_day"
    camp.mkdir(parents=True)
    (camp / "text.md").write_text("Blinkit ambush ad during the match", encoding="utf-8")
    (camp / "ad.png").write_bytes(base64.b64decode(png_b64((10, 10, 200))))

    from scripts.backfill import run

    await run(root)
    assert tmp_memory.count() == 1
    assert len(await tmp_store.list()) == 1

    calls_before = len(fake_llm.nodes)
    await run(root)  # second pass: duplicate short-circuits, no new model calls
    assert tmp_memory.count() == 1
    assert len(await tmp_store.list()) == 1
    assert len(fake_llm.nodes) == calls_before
