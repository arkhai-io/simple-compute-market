"""Structured stage-boundary logging for storefront runtimes."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any
from market_identity import Identity, Signer


_logger = logging.getLogger("stage")
_db_path: str | None = None
RUN_LOG_VERSION = 2
_FORBIDDEN_KEYS = frozenset(
    {
        "credential",
        "credentials",
        "identity_credential",
        "mnemonic",
        "private_key",
        "secret",
        "secret_key",
        "seed",
        "seed_phrase",
        "signing_key",
    }
)


def _public_value(value: Any) -> Any:
    if isinstance(value, Identity):
        return value.model_dump(mode="json")
    if isinstance(value, Signer):
        raise ValueError("signers cannot be written to storefront run logs")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("binary signing material cannot be written to storefront run logs")
    if isinstance(value, dict):
        forbidden = sorted(
            str(key)
            for key in value
            if (
                (normalized := str(key).lower().replace("-", "_"))
                in _FORBIDDEN_KEYS
                or normalized.replace("_", "").endswith("privatekey")
            )
        )
        if forbidden:
            raise ValueError(
                f"private signing material cannot be logged: {forbidden!r}"
            )
        return {key: _public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return value




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
    public_fields = _public_value(fields)
    entry = {
        "version": RUN_LOG_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "event": event,
        **public_fields,
    }
    _logger.info(json.dumps(entry, default=str))
    _persist(entry)
