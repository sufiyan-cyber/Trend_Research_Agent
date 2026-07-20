"""Fetch and normalize items from registered sources (RSS + GDELT).

Internal data collection for the radar — distinct from user input, which
stays text+images. Each source is fetched with per-source error isolation:
one dead feed never kills a scan.
"""

import hashlib
import html
import logging
import re

import feedparser
import httpx

from app.schemas import ScanItem, Source, SourceRegistry

logger = logging.getLogger("trend_agent")

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_TAGS = re.compile(r"<[^>]+>")
_HEADERS = {"User-Agent": "TrendResearchAgent/0.4 (internal radar; contact: hidevs)"}


def _clean(text: str, limit: int = 500) -> str:
    text = html.unescape(_TAGS.sub(" ", text or ""))
    return " ".join(text.split())[:limit]


def _hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:24]


async def _fetch_rss(client: httpx.AsyncClient, src: Source) -> list[ScanItem]:
    resp = await client.get(src.url, headers=_HEADERS)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries[:40]:
        link = getattr(e, "link", "") or ""
        if not link:
            continue
        items.append(
            ScanItem(
                url_hash=_hash(link),
                source_id=src.id,
                source_name=src.name,
                title=_clean(getattr(e, "title", ""), 200),
                url=link,
                published=getattr(e, "published", "") or getattr(e, "updated", ""),
                summary=_clean(getattr(e, "summary", "")),
            )
        )
    return items


async def _fetch_gdelt(client: httpx.AsyncClient, src: Source) -> list[ScanItem]:
    resp = await client.get(
        GDELT_URL,
        params={
            "query": src.query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": src.max_records,
            "timespan": src.timespan,
        },
        headers=_HEADERS,
    )
    resp.raise_for_status()
    articles = (resp.json() or {}).get("articles", [])
    items = []
    for a in articles:
        url = a.get("url", "")
        if not url:
            continue
        items.append(
            ScanItem(
                url_hash=_hash(url),
                source_id=src.id,
                source_name=src.name,
                title=_clean(a.get("title", ""), 200),
                url=url,
                published=a.get("seendate", ""),
                summary=_clean(a.get("domain", "")),
            )
        )
    return items


async def fetch_all(registry: SourceRegistry) -> tuple[list[ScanItem], int, int]:
    """Fetch every source; returns (items, sources_ok, sources_failed)."""
    items: list[ScanItem] = []
    ok = failed = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for src in registry.sources:
            try:
                fetched = await (_fetch_rss(client, src) if src.type == "rss" else _fetch_gdelt(client, src))
                items.extend(fetched)
                ok += 1
                logger.info("radar fetch %s: %d items", src.id, len(fetched))
            except Exception as e:
                failed += 1
                logger.warning("radar fetch %s failed: %s", src.id, e)
    # de-dupe within the batch (same story via multiple sources)
    seen: set[str] = set()
    unique = [i for i in items if not (i.url_hash in seen or seen.add(i.url_hash))]
    return unique, ok, failed
