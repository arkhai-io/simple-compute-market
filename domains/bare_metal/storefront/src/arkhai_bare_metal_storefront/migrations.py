"""Versioned SQLite migrations owned by the bare-metal storefront."""

from __future__ import annotations

import sqlite3

from core_storefront.sqlite_migrations import Migration


def _add_agreement_payloads(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bare_metal_agreement_payloads (
          negotiation_id TEXT PRIMARY KEY,
          message_json TEXT,
          terms_json TEXT,
          materialization_json TEXT,
          receipt_json TEXT,
          result_json TEXT,
          created_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
    )


BARE_METAL_STOREFRONT_MIGRATIONS = (
    Migration(
        id="bare-metal-storefront-0001-agreement-payloads",
        apply=_add_agreement_payloads,
    ),
)
