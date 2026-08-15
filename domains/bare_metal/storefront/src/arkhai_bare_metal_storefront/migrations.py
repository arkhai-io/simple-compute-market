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


def _add_derived_publication_tracking(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='derived_bare_metal_listings'",
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            CREATE TABLE derived_bare_metal_listings (
              listing_id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL,
              physical_resource_id TEXT NOT NULL,
              machine_id TEXT NOT NULL,
              physical_host_id TEXT NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL UNIQUE,
              last_reconciled_at TEXT NOT NULL
                DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """,
        )
    else:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(derived_bare_metal_listings)",
            )
        }
        if "site_id" not in columns:
            conn.execute(
                "ALTER TABLE derived_bare_metal_listings ADD COLUMN site_id TEXT",
            )
        if "physical_resource_id" not in columns:
            conn.execute(
                "ALTER TABLE derived_bare_metal_listings "
                "ADD COLUMN physical_resource_id TEXT",
            )
        conn.execute(
            "UPDATE derived_bare_metal_listings SET status = 'closed' "
            "WHERE site_id IS NULL OR physical_resource_id IS NULL",
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_bare_metal_site_resource "
        "ON derived_bare_metal_listings(site_id, physical_resource_id)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_bare_metal_status "
        "ON derived_bare_metal_listings(status)",
    )


def _add_operator_state(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bare_metal_operator_state (
          singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
          paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
          updated_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
    )
    conn.execute(
        "INSERT INTO bare_metal_operator_state(singleton_id, paused) VALUES (1, 0)",
    )



def _add_selected_site_bindings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bare_metal_selected_site_bindings (
          capacity_reservation_id TEXT PRIMARY KEY,
          site_id TEXT NOT NULL,
          authority_scheme TEXT NOT NULL,
          authority_identifier TEXT NOT NULL,
          created_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          CHECK (LENGTH(TRIM(capacity_reservation_id)) > 0),
          CHECK (LENGTH(TRIM(site_id)) > 0),
          CHECK (LENGTH(TRIM(authority_scheme)) > 0),
          CHECK (LENGTH(TRIM(authority_identifier)) > 0)
        )
        """,
    )
    conn.execute(
        "CREATE INDEX idx_bare_metal_selected_site "
        "ON bare_metal_selected_site_bindings(site_id)",
    )

BARE_METAL_STOREFRONT_MIGRATIONS = (
    Migration(
        id="bare-metal-storefront-0001-agreement-payloads",
        apply=_add_agreement_payloads,
    ),
    Migration(
        id="bare-metal-storefront-0002-derived-publications",
        apply=_add_derived_publication_tracking,
    ),
    Migration(
        id="bare-metal-storefront-0003-operator-state",
        apply=_add_operator_state,
    ),
    Migration(
        id="bare-metal-storefront-0004-selected-site-bindings",
        apply=_add_selected_site_bindings,
    ),
)
