"""The settlement runtime's migrations, for a storefront chain holding its tables.

A storefront composition composes :data:`BASELINE` after core storefront's. The
baseline is fixed DDL reproducing the settlement tables as the marketplace
v0.3.0 release's storefronts built them; a later change to them is a migration
after it, never an edit to it, since an adopted v0.3.0 database records the
baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import sqlite3

from market_schema_migrations import Migration

_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE settlement_obligations (
      obligation_ref TEXT PRIMARY KEY,
      agreement_ref TEXT NOT NULL,
      obligation_index INTEGER NOT NULL CHECK (obligation_index >= 0),
      obligation_hash TEXT NOT NULL,
      obligation TEXT NOT NULL,
      mechanism_params TEXT NOT NULL DEFAULT '{}',
      payer_principal TEXT NOT NULL,
      claimant_principal TEXT NOT NULL,
      mechanism_ref TEXT,
      mechanism_status TEXT,
      mechanism_state TEXT NOT NULL DEFAULT '{}',
      buyer_action TEXT,
      condition_anchor TEXT,
      fulfillment_ref TEXT,
      materialization_state TEXT NOT NULL DEFAULT 'pending',
      condition_state TEXT NOT NULL DEFAULT 'pending',
      collection_state TEXT NOT NULL DEFAULT 'pending',
      reclaim_state TEXT NOT NULL DEFAULT 'pending',
      materialization_receipt TEXT,
      status_receipt TEXT,
      collection_receipt TEXT,
      reclaim_receipt TEXT,
      last_error TEXT,
      version INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (agreement_ref, obligation_index)
    )
    """,
    """
    CREATE TABLE settlement_operations (
      obligation_ref TEXT NOT NULL,
      operation TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      uncertain_acknowledgement INTEGER NOT NULL DEFAULT 0,
      receipt TEXT,
      last_error TEXT,
      lease_owner TEXT,
      lease_until_unix REAL,
      next_attempt_unix REAL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      awaiting_delivery INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (obligation_ref, operation),
      FOREIGN KEY (obligation_ref) REFERENCES settlement_obligations(obligation_ref)
    )
    """,
    "CREATE INDEX idx_settlement_obligations_agreement"
    " ON settlement_obligations(agreement_ref, obligation_index)",
    "CREATE UNIQUE INDEX idx_settlement_obligations_mechanism_ref"
    " ON settlement_obligations(mechanism_ref) WHERE mechanism_ref IS NOT NULL",
    "CREATE INDEX idx_settlement_operations_due"
    " ON settlement_operations(state, next_attempt_unix, lease_until_unix)",
    "CREATE TRIGGER settlement_principals_insert_required BEFORE INSERT ON"
    " settlement_obligations WHEN NEW.payer_principal IS NULL OR NEW.payer_principal = ''"
    " OR NEW.claimant_principal IS NULL OR NEW.claimant_principal = '' BEGIN SELECT"
    " RAISE(ABORT, 'settlement principals required'); END",
    "CREATE TRIGGER settlement_principals_update_required BEFORE UPDATE OF"
    " payer_principal, claimant_principal ON settlement_obligations WHEN"
    " NEW.payer_principal IS NULL OR NEW.payer_principal = '' OR"
    " NEW.claimant_principal IS NULL OR NEW.claimant_principal = '' BEGIN SELECT"
    " RAISE(ABORT, 'settlement principals required'); END",
)

BASELINE_TABLES: frozenset[str] = frozenset(
    {"settlement_obligations", "settlement_operations"}
)
"""The tables :data:`BASELINE` creates."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_settlement_runtime", _create_baseline
)
"""The settlement tables as the v0.3.0 release's storefronts built them."""
