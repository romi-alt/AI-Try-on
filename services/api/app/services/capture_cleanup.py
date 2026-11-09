"""Fallback sweeper for webcam captures, plus oversized garment uploads.

Captures are deleted after `capture_ttl_seconds` (default 1 hour). Object-store lifecycle
rules only work in whole days, so a bucket rule (`scripts/apply_lifecycle.py`) is just a coarse
safety net; this loop is what enforces the one-hour limit.

The same loop deletes garment images over `garment_max_bytes`. A presigned PUT cannot cap the size, and
`POST /uploads/verify` only checks uploads a client asks about, so this covers the rest.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.storage import delete_captures_older_than, delete_oversized_garments

logger = logging.getLogger("app.capture_cleanup")


async def sweep_once(ttl_seconds: int | None = None) -> int:
    ttl = settings.capture_ttl_seconds if ttl_seconds is None else ttl_seconds
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl)
    deleted = await run_in_threadpool(delete_captures_older_than, cutoff)
    if deleted:
        logger.info("captures_deleted", extra={"count": deleted, "older_than": cutoff.isoformat()})
    return deleted


async def sweep_oversized_garments_once(max_bytes: int | None = None) -> int:
    limit = settings.garment_max_bytes if max_bytes is None else max_bytes
    deleted = await run_in_threadpool(delete_oversized_garments, limit)
    if deleted:
        logger.warning("oversized_garments_deleted", extra={"count": deleted, "max_bytes": limit})
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
        try:
            await sweep_oversized_garments_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("garment_sweep_failed")
        await asyncio.sleep(interval_seconds)
