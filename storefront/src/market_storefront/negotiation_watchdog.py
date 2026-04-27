"""Background watchdog that marks stale negotiation threads as abandoned.

If a counterparty vanishes mid-negotiation (process crash, network drop,
bug) our side's negotiation thread sits forever in `terminal_state=NULL`,
blocking the buyer's `market buy` from exiting and leaving seller
inventory nominally "in deal" indefinitely.

On an interval (``NEGOTIATION_WATCHDOG_INTERVAL``, default 60 s), scan
the ``negotiation_threads`` table for rows where:

    terminal_state IS NULL
    AND updated_at < now - NEGOTIATION_TIMEOUT_SECONDS

Mark each such row as ``terminal_state='abandoned'`` via
``update_negotiation_thread_terminal`` and emit a stage event.

This is the *automatic* complement to user-invoked
``market buy --abort`` and ``market provide --abort-all``. Together they
give both sides a path out of stuck deals.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from market_storefront.utils.config import CONFIG
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils.stage_log import stage_event

logger = logging.getLogger(__name__)


ABANDONED = "abandoned"


def _parse_ts(raw: str) -> datetime | None:
    """Parse the various timestamp formats the agent stores for updated_at."""
    if not raw:
        return None
    # Normalise: drop trailing 'Z', treat as UTC if naive.
    text = raw.rstrip("Z")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stale_threads(db_path: str, cutoff: datetime) -> list[dict]:
    """Return rows of active negotiations whose updated_at is older than cutoff."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT negotiation_id, our_order_id, their_order_id, updated_at
               FROM negotiation_threads
               WHERE terminal_state IS NULL""",
        ).fetchall()
    finally:
        conn.close()

    stale: list[dict] = []
    for row in rows:
        ts = _parse_ts(row["updated_at"])
        if ts is None:
            continue
        if ts < cutoff:
            stale.append(dict(row))
    return stale


async def _watchdog_tick(sqlite_client: SQLiteClient) -> int:
    """Run one watchdog pass. Returns the number of threads abandoned."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CONFIG.negotiation_timeout_seconds)
    stale = _stale_threads(sqlite_client.db_path, cutoff)
    if not stale:
        return 0

    for thread in stale:
        nid = thread["negotiation_id"]
        logger.warning(
            "negotiation_watchdog: marking %s as abandoned (updated_at=%s, cutoff=%s)",
            nid, thread["updated_at"], cutoff.isoformat(),
        )
        try:
            await sqlite_client.update_negotiation_thread_terminal(
                negotiation_id=nid,
                terminal_state=ABANDONED,
            )
        except Exception as exc:
            logger.warning(
                "negotiation_watchdog: failed to terminate thread %s: %s", nid, exc,
            )
            continue
        try:
            stage_event(
                stage="negotiation",
                event="abandoned",
                negotiation_id=nid,
                order_id=thread.get("our_order_id"),
                reason="watchdog_timeout",
                updated_at=thread.get("updated_at"),
            )
        except Exception as exc:
            logger.debug("stage_event emit failed for %s: %s", nid, exc)
    return len(stale)


async def watchdog_loop() -> None:
    """Continuously sweep for stale negotiations.

    Initial 15 s delay lets the agent finish startup before the first scan
    (so freshly-created threads aren't misclassified if the clock hasn't
    caught up).
    """
    await asyncio.sleep(15)
    sqlite_client = SQLiteClient(db_path=CONFIG.agent_db_path)
    logger.info(
        "negotiation_watchdog_loop: started (interval=%ds, timeout=%ds)",
        CONFIG.negotiation_watchdog_interval,
        CONFIG.negotiation_timeout_seconds,
    )
    while True:
        try:
            await asyncio.sleep(CONFIG.negotiation_watchdog_interval)
            n = await _watchdog_tick(sqlite_client)
            if n:
                logger.info("negotiation_watchdog_loop: abandoned %d stale thread(s)", n)
        except asyncio.CancelledError:
            logger.info("negotiation_watchdog_loop: cancelled, shutting down")
            break
        except Exception as exc:
            logger.exception("negotiation_watchdog_loop error: %s", exc)
