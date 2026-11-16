"""The tables deal servicing reads and writes, as DDL a storefront's chain applies.

No session creates a table: a storefront composing deal servicing applies each
set below in a migration of its own chain, so opening a session issues no DDL.

:data:`SERVICING_SCHEMA` is the set a release created while sessions still
created their tables when they first opened, so a storefront database may hold
some, all, or none of it: every statement is ``IF NOT EXISTS``, and the one
migration that applies it is the only migration that tolerates objects already
present. Every table added since is its own set, created by an ordinary
migration appended to the chain after that one, which tolerates nothing.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import sqlite3

SERVICING_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS servicing_evidence_deals (
        negotiation_id TEXT PRIMARY KEY,
        acceptance_expires_at INTEGER,
        accepted_by TEXT,
        lifecycle TEXT,
        observation TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_evidence_items (
        position INTEGER PRIMARY KEY AUTOINCREMENT,
        negotiation_id TEXT NOT NULL,
        evidence_id TEXT NOT NULL,
        item TEXT NOT NULL,
        UNIQUE (negotiation_id, evidence_id)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_evidence_commitments (
        negotiation_id TEXT NOT NULL,
        commitment_ref TEXT NOT NULL,
        superseded INTEGER NOT NULL,
        PRIMARY KEY (negotiation_id, commitment_ref)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS servicing_one_live_commitment
        ON servicing_evidence_commitments(negotiation_id) WHERE superseded = 0""",
    """CREATE TABLE IF NOT EXISTS servicing_delivery (
        negotiation_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, record TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_final_requests (
        negotiation_id TEXT NOT NULL, source_ref TEXT NOT NULL, ended_at INTEGER NOT NULL,
        request TEXT NOT NULL, classification TEXT, correction_basis INTEGER NOT NULL,
        PRIMARY KEY (negotiation_id,source_ref)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_intents (
        intent_ref TEXT PRIMARY KEY, negotiation_id TEXT NOT NULL,
        kind TEXT NOT NULL, operation_key TEXT NOT NULL, intent TEXT NOT NULL,
        UNIQUE (negotiation_id,kind,operation_key)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS servicing_one_billing_intent
        ON servicing_intents(negotiation_id) WHERE kind='billing'""",
    """CREATE TABLE IF NOT EXISTS servicing_end_receipts (
        negotiation_id TEXT NOT NULL, operation_key TEXT NOT NULL,
        request_digest TEXT NOT NULL, receipt_at INTEGER NOT NULL,
        PRIMARY KEY (negotiation_id,operation_key)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_receipt_claims (
        negotiation_id TEXT NOT NULL, operation_key TEXT NOT NULL, claim TEXT NOT NULL,
        PRIMARY KEY (negotiation_id,operation_key)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_seller_deals (
        negotiation_id TEXT PRIMARY KEY, deal TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_operations (
        negotiation_id TEXT NOT NULL, operation_key TEXT NOT NULL, digest TEXT NOT NULL,
        PRIMARY KEY (negotiation_id,operation_key)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_watch (
        negotiation_id TEXT NOT NULL, record_ref TEXT NOT NULL,
        sequence INTEGER NOT NULL, view TEXT NOT NULL,
        PRIMARY KEY (negotiation_id,record_ref)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_observations (
        negotiation_id TEXT NOT NULL, record_ref TEXT NOT NULL, view TEXT NOT NULL,
        PRIMARY KEY (negotiation_id,record_ref)
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_respondent (
        record TEXT PRIMARY KEY, cursor TEXT NOT NULL, page TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS servicing_respondent_repairs (
        record TEXT NOT NULL, case_ref TEXT NOT NULL, commitment_ref TEXT NOT NULL,
        case_json TEXT NOT NULL, reason TEXT NOT NULL,
        PRIMARY KEY (record,case_ref)
    )""",
)


#: The storefront-clock instant of the latest successful payment observation of
#: each deal's commitment, written by the payment watch in the transaction that
#: records what the observation showed and read by admission's deadline rule.
PAYMENT_OBSERVATIONS_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE servicing_payment_observations (
        negotiation_id TEXT NOT NULL, commitment_ref TEXT NOT NULL, observed_at INTEGER NOT NULL,
        PRIMARY KEY (negotiation_id,commitment_ref)
    )""",
)


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply :data:`SERVICING_SCHEMA` inside the caller's transaction, committing nothing.

    The body of a storefront migration, not something a session calls.
    """

    for statement in SERVICING_SCHEMA:
        conn.execute(statement)


def create_payment_observations(conn: sqlite3.Connection) -> None:
    """Apply :data:`PAYMENT_OBSERVATIONS_SCHEMA` inside the caller's transaction.

    The body of a storefront migration after the one applying
    :data:`SERVICING_SCHEMA`; it fails on a database that already holds the table.
    """

    for statement in PAYMENT_OBSERVATIONS_SCHEMA:
        conn.execute(statement)
