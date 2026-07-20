"""Phase 4: source registry, ingestion, scan+triage flow, alerts, digest, market map, costs."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.radar.ingest import _fetch_gdelt, _fetch_rss
from app.schemas import ScanItem, Source, utcnow
from tests.conftest import make_v1_report, png_b64

client = TestClient(app)


@pytest.fixture
def tmp_sources(monkeypatch, tmp_path):
    from app.radar.sources import SOURCES_PATH

    p = tmp_path / "sources.json"
    p.write_text(SOURCES_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("app.radar.sources.SOURCES_PATH", p)
    return p


# --- registry ----------------------------------------------------------------


def test_sources_registry_present(tmp_sources):
    r = client.get("/sources")
    assert r.status_code == 200
    types = {s["type"] for s in r.json()["sources"]}
    assert types == {"rss", "gdelt"}


def test_sources_put_validation(tmp_sources):
    reg = client.get("/sources").json()
    reg["sources"].append(dict(reg["sources"][0]))
    assert client.put("/sources", json=reg).status_code == 400  # duplicate id
    bad = {"sources": [{"id": "x", "type": "rss", "name": "X"}]}
    assert client.put("/sources", json=bad).status_code == 400  # rss without url
    good = {"sources": [{"id": "x", "type": "rss", "name": "X", "url": "https://x.test/feed"}]}
    assert client.put("/sources", json=good).status_code == 200
    assert "x.test" in tmp_sources.read_text(encoding="utf-8")


# --- ingestion ---------------------------------------------------------------

RSS_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Blinkit's match-day &amp; ambush ad</title><link>https://ex.test/a1</link>
<description>&lt;p&gt;A &lt;b&gt;bold&lt;/b&gt; topical creative during the final.&lt;/p&gt;</description>
<pubDate>Fri, 17 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>5 tips for email marketing</title><link>https://ex.test/a2</link>
<description>Generic listicle content here.</description></item>
</channel></rss>"""

GDELT_JSON = {
    "articles": [
        {"url": "https://news.test/b1", "title": "Edtech brand goes viral with meme push", "seendate": "20260717T060000Z", "domain": "news.test"}
    ]
}


@pytest.mark.anyio
async def test_rss_ingestion_normalizes_items():
    src = Source(id="t", type="rss", name="Test Feed", url="https://ex.test/feed")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=RSS_XML))
    async with httpx.AsyncClient(transport=transport) as c:
        items = await _fetch_rss(c, src)
    assert len(items) == 2
    assert items[0].title == "Blinkit's match-day & ambush ad"
    assert "<" not in items[0].summary and "bold topical creative" in items[0].summary
    assert items[0].url_hash and items[0].source_name == "Test Feed"


@pytest.mark.anyio
async def test_gdelt_ingestion_normalizes_items():
    src = Source(id="g", type="gdelt", name="GDELT", query="edtech campaign")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=GDELT_JSON))
    async with httpx.AsyncClient(transport=transport) as c:
        items = await _fetch_gdelt(c, src)
    assert len(items) == 1
    assert items[0].title.startswith("Edtech brand")


# --- scan flow ---------------------------------------------------------------


def _scan_items() -> list[ScanItem]:
    mk = lambda n, title: ScanItem(
        url_hash=f"hash-{n}", source_id="t", source_name="Test Feed",
        title=title, url=f"https://ex.test/{n}", summary=f"summary {n}",
    )
    return [mk(1, "Brand X viral countdown stunt"), mk(2, "5 generic tips"), mk(3, "Old already-seen story")]


@pytest.mark.anyio
async def test_scan_dedupes_triages_and_analyzes(monkeypatch, fake_llm, tmp_store, tmp_memory, tmp_radar):
    from app.radar import scan

    async def fake_fetch(_registry):
        return _scan_items(), 2, 0

    monkeypatch.setattr("app.radar.scan.fetch_all", fake_fetch)
    (tmp_radar).mkdir(parents=True, exist_ok=True)
    (tmp_radar / "seen_urls.json").write_text(json.dumps(["hash-3"]), encoding="utf-8")

    stats = await scan.run_scan()
    assert (stats.fetched, stats.new, stats.notable, stats.analyzed) == (3, 2, 1, 1)
    assert stats.filter_rate == 0.5
    assert "triage" in fake_llm.nodes and "composer" in fake_llm.nodes

    # survivor persisted as a scan-sourced report and indexed into memory
    records = await tmp_store.list()
    assert len(records) == 1 and records[0]["source"] == "scan"
    assert records[0]["scan_item"]["url"] == "https://ex.test/1"
    assert records[0]["crawled"] is False  # crawl disabled here -> title+summary fallback
    assert tmp_memory.count() == 1

    # second run: everything already seen -> nothing new, perfect filter rate
    stats2 = await scan.run_scan()
    assert (stats2.new, stats2.analyzed, stats2.filter_rate) == (0, 0, 1.0)
    assert len(scan.scan_history()) == 2


@pytest.mark.anyio
async def test_scan_crawls_survivors_for_full_text_and_screenshot(monkeypatch, fake_llm, tmp_store, tmp_memory, tmp_radar):
    from app.radar import scan
    from app.radar.crawler import CrawledPage

    async def fake_fetch(_registry):
        return _scan_items()[:2], 1, 0  # item 0 notable, item 1 rejected by triage fixture

    async def fake_crawl(url):
        return CrawledPage(url=url, markdown="Full article text about the countdown stunt.", screenshot_b64=png_b64((5, 5, 5)))

    monkeypatch.setattr("app.radar.scan.fetch_all", fake_fetch)
    monkeypatch.setattr("app.radar.crawler.crawl_page", fake_crawl)

    stats = await scan.run_scan()
    assert stats.analyzed == 1
    rec = (await tmp_store.list())[0]
    assert rec["crawled"] is True
    assert "Full article text" in rec["input"]["text"]  # crawled markdown, not the thin RSS summary
    assert rec["input"]["images"], "page screenshot stored as an input image"


# --- alerts ------------------------------------------------------------------


def test_rising_verdict_creates_alert_once(fake_llm, tmp_store):
    client.post("/analyze", json={"text": "first hot campaign about countdown offers", "images": []})
    client.post("/analyze", json={"text": "second campaign, same play, different words entirely", "images": []})
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1  # same play within 7 days -> deduped
    assert alerts[0]["play"] == "FOMO / Scarcity"
    assert alerts[0]["verdict"] == "rising"


# --- digest ------------------------------------------------------------------


@pytest.mark.anyio
async def test_digest_from_week_of_memory(fake_llm, tmp_memory):
    report = make_v1_report()
    await tmp_memory.index_report("seed-1", utcnow().isoformat(), report, "campaign one", [], extra_payload={"trend_verdict": "rising"})
    await tmp_memory.index_report("seed-2", utcnow().isoformat(), report, "campaign two", [], extra_payload={"trend_verdict": "rising"})

    rec = client.post("/radar/digest").json()
    assert rec["week_items"] == 2
    assert rec["digest"]["headline"].startswith("Self-selection")
    assert "digest" in fake_llm.nodes

    latest = client.get("/digest/latest")
    assert latest.status_code == 200 and latest.json()["generated_at"] == rec["generated_at"]
    md = client.get("/digest/latest", params={"format": "markdown"})
    assert "Weekly Trend Digest" in md.text and "FOMO / Scarcity" in md.text
    assert client.get("/digests").json() == [rec["generated_at"][:10]]


def test_quiet_week_digest_needs_no_llm(fake_llm):
    rec = client.post("/radar/digest").json()
    assert rec["week_items"] == 0
    assert rec["digest"]["headline"].startswith("Quiet week")
    assert "digest" not in fake_llm.nodes  # zero-cost when there is nothing to say


# --- market map --------------------------------------------------------------


@pytest.mark.anyio
async def test_market_map_profiles_tracked_players(fake_llm, tmp_memory):
    report = make_v1_report()
    await tmp_memory.index_report("mm-1", utcnow().isoformat(), report, "That Blinkit ambush ad again", [])
    await tmp_memory.index_report("mm-2", utcnow().isoformat(), report, "Blinkit countdown push", [])

    rec = client.post("/radar/market-map/refresh").json()
    assert len(rec["players"]) == 1
    p = rec["players"][0]
    assert p["player_id"] == "blinkit" and p["campaigns"] == 2
    assert p["profile"].startswith("Rides live moments")
    assert "Zomato" in rec["tracked_but_unseen"]
    assert client.get("/market-map").status_code == 200


def test_market_map_404_before_first_refresh():
    assert client.get("/market-map").status_code == 404


# --- costs -------------------------------------------------------------------


def test_costs_aggregates_tokens_by_node(fake_llm, tmp_store):
    client.post("/analyze", json={"text": "one analyzed campaign for cost accounting", "images": []})
    body = client.get("/costs").json()
    assert body["reports"] == 1
    assert body["tokens_by_node"]["strategy"]["calls"] == 1
    assert body["total_tokens"] > 0
    assert body["radar"]["target_filter_rate"] == 0.8
