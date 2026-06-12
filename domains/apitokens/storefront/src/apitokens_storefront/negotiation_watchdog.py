"""Background watchdog that marks stale negotiation threads as abandoned.

Same mechanics as the VM storefront's watchdog: on an interval, scan
``negotiation_threads`` for non-terminal rows older than the timeout,
mark them ``abandoned``, emit a stage event.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from core_storefront.stage_log import stage_event

from apitokens_storefront.utils.config import settings
from apitokens_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

ABANDONED = "abandoned"


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    text = raw.rstrip("Z")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stale_threads(db_path: str, cutoff: datetime) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT negotiation_id, our_listing_id, updated_at
               FROM negotiation_threads
               WHERE terminal_state IS NULL""",
        ).fetchall()
    finally:
        conn.close()

    stale: list[dict] = []
    for row in rows:
        ts = _parse_ts(row["updated_at"])
        if ts is not None and ts < cutoff:
            stale.append(dict(row))
    return stale


async def _watchdog_tick(sqlite_client: SQLiteClient) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.negotiation_timeout_seconds,
    )
    stale = _stale_threads(sqlite_client.db_path, cutoff)
    for thread in stale:
        nid = thread["negotiation_id"]
        logger.warning(
            "negotiation_watchdog: marking %s as abandoned (updated_at=%s)",
            nid, thread["updated_at"],
        )
        try:
            await sqlite_client.update_negotiation_thread_terminal(
                negotiation_id=nid,
                terminal_state=ABANDONED,
            )
        except Exception as exc:
            logger.warning(
                "negotiation_watchdog: failed to terminate thread %s: %s",
                nid, exc,
            )
            continue
        try:
            stage_event(
                stage="negotiation",
                event="abandoned",
                negotiation_id=nid,
                order_id=thread.get("our_listing_id"),
                reason="watchdog_timeout",
                updated_at=thread.get("updated_at"),
            )
        except Exception as exc:
            logger.debug("stage_event emit failed for %s: %s", nid, exc)
    return len(stale)


async def watchdog_loop() -> None:
    """Continuously sweep for stale negotiations."""
    await asyncio.sleep(15)
    sqlite_client = SQLiteClient(db_path=settings.db_path)
    while True:
        try:
            await asyncio.sleep(settings.negotiation_watchdog_interval)
            n = await _watchdog_tick(sqlite_client)
            if n:
                logger.info(
                    "negotiation_watchdog_loop: abandoned %d stale thread(s)", n,
                )
        except asyncio.CancelledError:
            logger.info("negotiation_watchdog_loop: cancelled, shutting down")
            break
        except Exception as exc:
            logger.exception("negotiation_watchdog_loop error: %s", exc)
