"""Structured stage-boundary logging for storefront runtimes."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("stage")
_db_path: str | None = None


def set_stage_event_db_path(db_path: str | None) -> None:
    """Set the SQLite DB path used for best-effort stage-event persistence."""
    global _db_path
    _db_path = db_path or None


def _persist(entry: dict[str, Any]) -> None:
    """Best-effort write to the stage_events SQLite table."""
    if not _db_path:
        return
    try:
        conn = sqlite3.connect(_db_path, timeout=2)
        try:
            conn.execute(
                """INSERT INTO stage_events (ts, stage, event, negotiation_id, listing_id, escrow_uid, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["ts"],
                    entry["stage"],
                    entry["event"],
                    entry.get("negotiation_id"),
                    entry.get("listing_id") or entry.get("our_listing_id") or entry.get("negotiation_id"),
                    entry.get("escrow_uid"),
                    json.dumps(entry, default=str),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def stage_event(stage: str, event: str, **fields: Any) -> None:
    """Emit a structured stage-boundary log entry."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "event": event,
        **fields,
    }
    _logger.info(json.dumps(entry, default=str))
    _persist(entry)
