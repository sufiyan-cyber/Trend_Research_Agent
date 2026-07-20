"""Crawl4AI wrapper: URL -> clean markdown + full-page screenshot.

Per the approved architecture, every triage survivor gets crawled so the
deep analysis sees the full article text AND the rendered page (the visual
specialist gets a real screenshot instead of nothing). Everything here is
best-effort: any failure returns None and the scan falls back to
title+summary — a dead or hostile page never kills a radar run.
"""

import logging

from pydantic import BaseModel

from app.config import CRAWL_ENABLED, CRAWL_TIMEOUT_S

logger = logging.getLogger("trend_agent")

MAX_MARKDOWN_CHARS = 6000  # plenty for analysis; keeps token cost bounded


class CrawledPage(BaseModel):
    url: str
    markdown: str
    screenshot_b64: str | None = None  # PNG, base64


async def crawl_page(url: str) -> CrawledPage | None:
    """Fetch a JS-rendered page as clean markdown + full-page screenshot."""
    if not CRAWL_ENABLED:
        return None
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        logger.warning("crawl4ai not installed — scans fall back to title+summary")
        return None

    try:
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            screenshot=True,
            cache_mode=CacheMode.BYPASS,
            page_timeout=CRAWL_TIMEOUT_S * 1000,
            verbose=False,
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
        if not getattr(result, "success", False):
            logger.warning("crawl failed for %s: %s", url, getattr(result, "error_message", "unknown"))
            return None
        markdown = str(getattr(result, "markdown", "") or "")[:MAX_MARKDOWN_CHARS]
        if not markdown.strip():
            return None
        return CrawledPage(url=url, markdown=markdown, screenshot_b64=getattr(result, "screenshot", None))
    except Exception as e:
        logger.warning("crawl error for %s: %s", url, e)
        return None
