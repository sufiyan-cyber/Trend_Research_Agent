"""The daily radar scan: fetch -> URL dedupe -> triage -> deep-analyze survivors.

Cost guardrail in action: only items that pass triage ever reach the full
pipeline; every run's stats (incl. filter rate) are appended to
data/radar/scan_stats.json. Target: >=80% of scanned items filtered out.
"""

import asyncio
import json
import logging
from pathlib import Path

from app.config import DATA_DIR
from app.radar.ingest import fetch_all
from app.radar.sources import load_sources
from app.radar.triage import triage_items
from app.schemas import ScanItem, ScanStats, utcnow

logger = logging.getLogger("trend_agent")

SEEN_PATH = DATA_DIR / "radar" / "seen_urls.json"
STATS_PATH = DATA_DIR / "radar" / "scan_stats.json"
SEEN_CAP = 5000

_scan_lock = asyncio.Lock()


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_history() -> list[ScanStats]:
    return [ScanStats.model_validate(s) for s in _load_json(STATS_PATH, [])]


async def _deep_analyze(item: ScanItem) -> str | None:
    """Crawl the survivor's page (full text + screenshot), then run the pipeline.

    Falls back to title+summary text-only analysis when the crawl fails.
    """
    from app.graph import graph, initial_state
    from app.radar.crawler import crawl_page
    from app.schemas import ImagePayload
    from app.storage import get_store, make_record, new_report_id

    page = await crawl_page(item.url)
    images: list[ImagePayload] = []
    if page is not None:
        text = (
            f"[Radar scan — {item.source_name}] {item.title}\n\n"
            f"Full page content (crawled):\n{page.markdown}\n\n"
            f"Source URL: {item.url}\nPublished: {item.published or 'unknown'}"
        )
        if page.screenshot_b64:
            images = [ImagePayload(data=page.screenshot_b64, mime_type="image/png")]
    else:
        text = (
            f"[Radar scan — {item.source_name}] {item.title}\n\n"
            f"{item.summary}\n\nSource URL: {item.url}\nPublished: {item.published or 'unknown'}"
        )

    report_id = new_report_id()
    state = await graph.ainvoke(initial_state(text, images, report_id, source="scan"))
    if state["existing_report_id"]:
        return None  # semantically already known
    record = make_record(report_id, text, images, state["report"], state["usages"])
    record["source"] = "scan"
    record["scan_item"] = item.model_dump()
    record["crawled"] = page is not None
    await get_store().save(record)
    return report_id


async def run_scan() -> ScanStats:
    """One full radar pass. Safe to trigger manually; refuses concurrent runs."""
    if _scan_lock.locked():
        raise RuntimeError("A scan is already running.")
    async with _scan_lock:
        stats = ScanStats(run_at=utcnow().isoformat())

        items, stats.sources_ok, stats.sources_failed = await fetch_all(load_sources())
        stats.fetched = len(items)

        seen: list[str] = _load_json(SEEN_PATH, [])
        seen_set = set(seen)
        new_items = [i for i in items if i.url_hash not in seen_set]
        stats.new = len(new_items)

        survivors: list[ScanItem] = []
        if new_items:
            survivors, _ = await triage_items(new_items)
        stats.notable = len(survivors)

        for item in survivors:
            try:
                if await _deep_analyze(item) is not None:
                    stats.analyzed += 1
            except Exception as e:
                stats.failed += 1
                logger.warning("deep analysis failed for %s: %s", item.url, e)

        # every fetched-new item is now 'seen', analyzed or not
        seen.extend(i.url_hash for i in new_items)
        _save_json(SEEN_PATH, seen[-SEEN_CAP:])

        stats.filter_rate = round(1 - (stats.analyzed / stats.new), 3) if stats.new else 1.0
        history = _load_json(STATS_PATH, [])
        history.append(stats.model_dump())
        _save_json(STATS_PATH, history[-200:])
        logger.info(
            "scan done: %d fetched, %d new, %d notable, %d analyzed (filter rate %.0f%%)",
            stats.fetched, stats.new, stats.notable, stats.analyzed, stats.filter_rate * 100,
        )
        return stats
