"""Structured stage-boundary logging.

Emits JSON log entries at each marketplace stage transition, documenting
what a hypothetical functional stage would return. Each entry has:

    stage       — discovery | negotiation | settlement | provision | post_settlement
    event       — specific transition within the stage
    deal fields — IDs, prices, resources, attestations as applicable

These logs serve three purposes:
1. Observability: grep for stage=settlement to see all escrow creations
2. Documentation: the logged fields ARE the stage's functional output
3. Rewrite guide: when stages become real functions, these become returns

Events are emitted to both:
- The "stage" Python logger (for stdout/file streaming)
- The agent's SQLite stage_events table (for CLI querying via `market logs`)

Usage:
    from core.agent.app.utils.stage_log import stage_event
    stage_event("discovery", "order_published", order_id=oid, offer=spec)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("stage")

# Set lazily on first use to avoid circular imports with sqlite_client.
_db_path: str | None = None


def _get_db_path() -> str | None:
    global _db_path
    if _db_path is not None:
        return _db_path
    try:
        from core.agent.app.utils.config import CONFIG
        _db_path = CONFIG.agent_db_path
    except Exception:
        _db_path = ""  # mark as "tried and failed" so we don't retry
    return _db_path or None


def _persist(entry: dict[str, Any]) -> None:
    """Best-effort write to the stage_events SQLite table."""
    db_path = _get_db_path()
    if not db_path:
        return
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            conn.execute(
                """INSERT INTO stage_events (ts, stage, event, negotiation_id, order_id, escrow_uid, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["ts"],
                    entry["stage"],
                    entry["event"],
                    entry.get("negotiation_id"),
                    entry.get("order_id") or entry.get("our_order_id") or entry.get("buyer_order_id"),
                    entry.get("escrow_uid"),
                    json.dumps(entry, default=str),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # best-effort; don't break the action flow for a log write


def stage_event(stage: str, event: str, **fields: Any) -> None:
    """Emit a structured stage-boundary log entry.

    All values are JSON-serialized. Non-serializable values (Pydantic
    models, enums) should be converted before passing.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "event": event,
        **fields,
    }
    _logger.info(json.dumps(entry, default=str))
    _persist(entry)
