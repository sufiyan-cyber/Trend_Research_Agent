"""APScheduler wiring: daily scan, weekly digest, monthly market map.

Times are server-local and configurable via .env (SCAN_HOUR, DIGEST_WEEKDAY,
DIGEST_HOUR, MARKET_MAP_DAY). Every job is exception-isolated: a failed run
logs and waits for the next tick, never crashes the app.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import DIGEST_HOUR, DIGEST_WEEKDAY, MARKET_MAP_DAY, SCAN_HOUR

logger = logging.getLogger("trend_agent")


async def _scan_job() -> None:
    from app.radar.scan import run_scan

    try:
        await run_scan()
    except Exception as e:
        logger.error("scheduled scan failed: %s", e)


async def _digest_job() -> None:
    from app.radar.digest import generate_digest

    try:
        await generate_digest()
    except Exception as e:
        logger.error("scheduled digest failed: %s", e)


async def _market_map_job() -> None:
    from app.radar.market_map import refresh_market_map

    try:
        await refresh_market_map()
    except Exception as e:
        logger.error("scheduled market map refresh failed: %s", e)


def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.add_job(_scan_job, CronTrigger(hour=SCAN_HOUR, minute=0), id="daily_scan")
    sched.add_job(_digest_job, CronTrigger(day_of_week=DIGEST_WEEKDAY, hour=DIGEST_HOUR, minute=0), id="weekly_digest")
    sched.add_job(_market_map_job, CronTrigger(day=MARKET_MAP_DAY, hour=9, minute=0), id="monthly_market_map")
    logger.info(
        "radar scheduler: daily scan %02d:00, digest %s %02d:00, market map day %d",
        SCAN_HOUR, DIGEST_WEEKDAY, DIGEST_HOUR, MARKET_MAP_DAY,
    )
    return sched
