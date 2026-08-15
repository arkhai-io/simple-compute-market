"""Versioned SQLite migrations owned by the bare-metal storefront."""

from __future__ import annotations

import json
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


def _add_fulfillment_lifecycle(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bare_metal_fulfillment_lifecycle (
          negotiation_id TEXT PRIMARY KEY,
          escrow_uid TEXT NOT NULL UNIQUE,
          site_id TEXT NOT NULL,
          physical_resource_id TEXT NOT NULL,
          capacity_reservation_id TEXT UNIQUE,
          settlement_resource_id TEXT,
          fulfillment_id TEXT UNIQUE,
          state TEXT NOT NULL,
          failure_reason TEXT,
          created_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          CHECK (LENGTH(TRIM(negotiation_id)) > 0),
          CHECK (LENGTH(TRIM(escrow_uid)) > 0),
          CHECK (LENGTH(TRIM(site_id)) > 0),
          CHECK (LENGTH(TRIM(physical_resource_id)) > 0)
        )
        """,
    )
    conn.execute(
        "CREATE INDEX idx_bare_metal_fulfillment_state "
        "ON bare_metal_fulfillment_lifecycle(state)",
    )


def _add_selected_site_immutability(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS bare_metal_selected_site_immutable
        BEFORE UPDATE OF
          capacity_reservation_id, site_id,
          authority_scheme, authority_identifier
        ON bare_metal_selected_site_bindings
        WHEN NOT (
          OLD.capacity_reservation_id IS NEW.capacity_reservation_id
          AND OLD.site_id IS NEW.site_id
          AND OLD.authority_scheme IS NEW.authority_scheme
          AND OLD.authority_identifier IS NEW.authority_identifier
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'bare-metal selected-site authority binding is immutable'
          );
        END
        """
    )


def _add_hosted_physical_lifecycle(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE bare_metal_hosted_lifecycle (
          obligation_ref TEXT PRIMARY KEY,
          agreement_ref TEXT NOT NULL,
          negotiation_id TEXT NOT NULL UNIQUE,
          accepted_binding_json TEXT NOT NULL,
          accepted_binding_digest TEXT NOT NULL,
          fulfillment_identity TEXT NOT NULL UNIQUE,
          physical_state TEXT NOT NULL DEFAULT 'accepted',
          financial_state TEXT NOT NULL DEFAULT 'pending',
          recovery_state TEXT NOT NULL DEFAULT 'none',
          teardown_state TEXT NOT NULL DEFAULT 'not_started',
          capacity_reservation_id TEXT UNIQUE,
          settlement_resource_id TEXT,
          fulfillment_id TEXT UNIQUE,
          public_result_json TEXT,
          public_result_digest TEXT,
          portable_evidence_json TEXT,
          portable_evidence_digest TEXT,
          portable_evidence_ref TEXT,
          failure_reason TEXT,
          created_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL
            DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          CHECK (LENGTH(TRIM(obligation_ref)) > 0),
          CHECK (LENGTH(TRIM(agreement_ref)) > 0),
          CHECK (LENGTH(TRIM(negotiation_id)) > 0),
          CHECK (accepted_binding_digest GLOB 'sha256:[0-9a-f]*'),
          CHECK (fulfillment_identity GLOB 'sha256:[0-9a-f]*'),
          CHECK (
            (public_result_json IS NULL AND public_result_digest IS NULL)
            OR
            (public_result_json IS NOT NULL AND public_result_digest IS NOT NULL)
          ),
          CHECK (
            (
              portable_evidence_json IS NULL
              AND portable_evidence_digest IS NULL
              AND portable_evidence_ref IS NULL
            )
            OR
            (
              portable_evidence_json IS NOT NULL
              AND portable_evidence_digest IS NOT NULL
              AND portable_evidence_ref IS NOT NULL
            )
          )
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_bare_metal_hosted_physical_state "
        "ON bare_metal_hosted_lifecycle(physical_state)"
    )
    conn.execute(
        "CREATE INDEX idx_bare_metal_hosted_recovery_state "
        "ON bare_metal_hosted_lifecycle(recovery_state, teardown_state)"
    )
    conn.execute(
        """
        CREATE TRIGGER bare_metal_hosted_binding_immutable
        BEFORE UPDATE OF
          obligation_ref, agreement_ref, negotiation_id,
          accepted_binding_json, accepted_binding_digest, fulfillment_identity
        ON bare_metal_hosted_lifecycle
        WHEN NOT (
          OLD.obligation_ref IS NEW.obligation_ref
          AND OLD.agreement_ref IS NEW.agreement_ref
          AND OLD.negotiation_id IS NEW.negotiation_id
          AND OLD.accepted_binding_json IS NEW.accepted_binding_json
          AND OLD.accepted_binding_digest IS NEW.accepted_binding_digest
          AND OLD.fulfillment_identity IS NEW.fulfillment_identity
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'bare-metal hosted accepted binding is immutable'
          );
        END
        """
    )


def _migrate_common_domain_bindings(conn: sqlite3.Connection) -> None:
    """Move historical bare-metal rows under common immutable ownership."""
    rows = conn.execute(
        """
        SELECT d.listing_id, d.site_id, d.physical_resource_id,
               d.machine_id, d.physical_host_id, d.derivation_key,
               d.last_reconciled_at, l.offer_resource
        FROM derived_bare_metal_listings d
        JOIN listings l ON l.listing_id=d.listing_id
        WHERE d.site_id IS NOT NULL AND d.physical_resource_id IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        offer_resource = json.loads(str(row[7]))
        offer_resource["virtualization_type"] = "bare_metal"
        conn.execute(
            "UPDATE listings SET offer_resource=? WHERE listing_id=?",
            (
                json.dumps(
                    offer_resource,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                row[0],
            ),
        )
        source_envelope = json.dumps(
            {
                "kind": "bare_metal.resource-projection.v1",
                "machine_id": row[3],
                "physical_host_id": row[4],
                "physical_resource_id": row[2],
                "schema_version": 1,
                "site_id": row[1],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO storefront_listing_bindings(
              listing_id, site_id, pool_id, physical_resource_id,
              offering_mode, domain_identity, contract_major,
              contract_minor, derivation_key, source_envelope_json,
              last_reconciled_at
            ) VALUES (?, ?, NULL, ?, 'bare_metal', 'bare_metal.v1',
                      1, 0, ?, ?, ?)
            """,
            (
                row[0],
                row[1],
                row[2],
                row[5],
                source_envelope,
                row[6],
            ),
        )
    conn.execute(
        """
        UPDATE negotiation_threads
        SET domain_listing_id=our_listing_id,
            site_id=(
              SELECT site_id FROM storefront_listing_bindings b
              WHERE b.listing_id=negotiation_threads.our_listing_id
            ),
            offering_mode='bare_metal',
            domain_identity='bare_metal.v1',
            contract_major=1,
            contract_minor=0
        WHERE EXISTS (
          SELECT 1 FROM bare_metal_agreement_payloads p
          WHERE p.negotiation_id=negotiation_threads.negotiation_id
        )
        """
    )
    artifact_columns = (
        ("message", "message_json"),
        ("terms", "terms_json"),
        ("materialization", "materialization_json"),
        ("receipt", "receipt_json"),
        ("result", "result_json"),
    )
    orphan = conn.execute(
        """
        SELECT p.negotiation_id
        FROM bare_metal_agreement_payloads p
        LEFT JOIN negotiation_threads t
          ON t.negotiation_id=p.negotiation_id
        WHERE t.negotiation_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if orphan is not None:
        raise RuntimeError(
            f"historical bare-metal artifact has no negotiation owner: {orphan[0]}"
        )
    payload_rows = conn.execute(
        """
        SELECT p.negotiation_id, p.message_json, p.terms_json,
               p.materialization_json, p.receipt_json, p.result_json,
               t.offering_mode, t.domain_identity,
               t.contract_major, t.contract_minor
        FROM bare_metal_agreement_payloads p
        JOIN negotiation_threads t ON t.negotiation_id=p.negotiation_id
        """
    ).fetchall()
    for payload_row in payload_rows:
        if any(value is None for value in payload_row[6:]):
            raise RuntimeError(
                "historical bare-metal agreement has no exact listing/site binding: "
                f"{payload_row[0]}"
            )
        for index, (artifact_slot, _column) in enumerate(
            artifact_columns,
            start=1,
        ):
            artifact_json = payload_row[index]
            if artifact_json is None:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO storefront_domain_artifacts(
                  negotiation_id, artifact_slot, offering_mode,
                  domain_identity, contract_major, contract_minor,
                  artifact_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload_row[0],
                    artifact_slot,
                    *payload_row[6:],
                    artifact_json,
                ),
            )
    conn.execute("DROP TABLE bare_metal_agreement_payloads")


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
    Migration(
        id="bare-metal-storefront-0005-fulfillment-lifecycle",
        apply=_add_fulfillment_lifecycle,
    ),
    Migration(
        id="bare-metal-storefront-0006-common-domain-bindings",
        apply=_migrate_common_domain_bindings,
    ),
    Migration(
        id="bare-metal-storefront-0007-selected-site-immutability",
        apply=_add_selected_site_immutability,
    ),
    Migration(
        id="bare-metal-storefront-0008-hosted-physical-lifecycle",
        apply=_add_hosted_physical_lifecycle,
    ),
)
