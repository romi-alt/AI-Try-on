"""Fallback sweeper for webcam captures.

Captures are deleted after `capture_ttl_seconds` (default 1 hour). Object-store lifecycle
rules only work in whole days, so a bucket rule (`scripts/apply_lifecycle.py`) is just a coarse
safety net; this loop is what enforces the one-hour limit.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.storage import delete_captures_older_than

logger = logging.getLogger("app.capture_cleanup")


async def sweep_once(ttl_seconds: int | None = None) -> int:
    ttl = settings.capture_ttl_seconds if ttl_seconds is None else ttl_seconds
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl)
    deleted = await run_in_threadpool(delete_captures_older_than, cutoff)
    if deleted:
        logger.info("captures_deleted", extra={"count": deleted, "older_than": cutoff.isoformat()})
    return deleted


async def cleanup_loop(interval_seconds: float, ttl_seconds: int | None = None) -> None:
    """Sweep forever. A failed sweep (storage down) is logged and retried next interval."""
    while True:
        try:
            await sweep_once(ttl_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("capture_sweep_failed")
        await asyncio.sleep(interval_seconds)
