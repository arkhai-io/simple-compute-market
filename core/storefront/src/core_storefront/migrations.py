"""Core storefront's migrations, for every storefront composition's chain.

A storefront composition's chain begins with :data:`BASELINE`, then the
baselines of the kits it composes that own tables, then its domain's. The
baseline is fixed DDL reproducing the market-state tables, indexes, and triggers
the marketplace v0.3.0 release's storefront database client built; a later
change to them is a migration after it, never an edit to it, since an adopted
v0.3.0 database records the baseline without running it.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import sqlite3

from market_schema_migrations import Migration

_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE negotiation_threads (
      negotiation_id TEXT PRIMARY KEY,
      our_listing_id TEXT,
      their_listing_id TEXT,
      our_agent_id TEXT,
      their_agent_id TEXT,
      status TEXT DEFAULT 'active',
      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
      updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
      terminal_state TEXT,
      requested_duration_seconds INTEGER,
      requested_start_utc TEXT,
      buyer_escrow_proposal TEXT,
      provision_terms TEXT,
      settlement_plan TEXT,
      agreed_price TEXT,
      agreed_duration_seconds INTEGER,
      agreed_at TEXT,
      agreement_bytes BLOB,
      settlement_data TEXT,
      buyer_scheme TEXT,
      buyer_identifier TEXT,
      seller_scheme TEXT,
      seller_identifier TEXT,
      matched_offer_id TEXT,
      domain_listing_id TEXT,
      site_id TEXT,
      offering_mode TEXT,
      domain_identity TEXT,
      contract_major INTEGER,
      contract_minor INTEGER,
      CHECK ((buyer_scheme IS NULL) = (buyer_identifier IS NULL)),
      CHECK ((seller_scheme IS NULL) = (seller_identifier IS NULL))
    )
    """,
    """
    CREATE TABLE negotiation_local_state (
      negotiation_id TEXT NOT NULL,
      owner_id TEXT NOT NULL,
      our_initial_price TEXT,
      our_strategy TEXT,
      PRIMARY KEY(negotiation_id, owner_id),
      FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id)
    )
    """,
    """
    CREATE TABLE negotiation_messages (
      message_id INTEGER PRIMARY KEY AUTOINCREMENT,
      negotiation_id TEXT NOT NULL,
      round INTEGER NOT NULL,
      sender_role TEXT NOT NULL,
      sender_scheme TEXT NOT NULL,
      sender_identifier TEXT NOT NULL,
      our_price TEXT,
      their_price TEXT,
      proposed_price TEXT,
      action_taken TEXT NOT NULL,
      message_type TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id),
      UNIQUE(negotiation_id, round)
    )
    """,
    """
    CREATE TABLE listings (
      listing_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      listing_resource TEXT NOT NULL,
      fulfillment_resource TEXT,
      max_duration_seconds INTEGER,
      seller_scheme TEXT NOT NULL,
      seller_identifier TEXT NOT NULL,
      oracle_address TEXT,
      paused INTEGER NOT NULL DEFAULT 0,
      accepted_escrows TEXT,
      settlement_options TEXT,
      publication_clauses TEXT,
      demands TEXT,
      storefront_url TEXT,
      closed_by TEXT CHECK (closed_by IN ('seller', 'reconciliation')),
      rate_structure TEXT
    )
    """,
    """
    CREATE TABLE capacity_holds (
      negotiation_id TEXT PRIMARY KEY,
      listing_id TEXT,
      capacity_reservation_id TEXT NOT NULL,
      payload TEXT,
      expires_at TEXT,
      created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
    """
    CREATE TRIGGER listings_principal_insert
    BEFORE INSERT ON listings
    WHEN NEW.storefront_url IS NULL OR NEW.seller_scheme IS NULL OR NEW.seller_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TRIGGER listings_principal_update
    BEFORE UPDATE ON listings
    WHEN NEW.storefront_url IS NULL OR NEW.seller_scheme IS NULL OR NEW.seller_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TRIGGER negotiation_threads_principal_insert
    BEFORE INSERT ON negotiation_threads
    WHEN NEW.buyer_scheme IS NULL OR NEW.buyer_identifier IS NULL OR NEW.seller_scheme IS NULL OR NEW.seller_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TRIGGER negotiation_threads_principal_update
    BEFORE UPDATE ON negotiation_threads
    WHEN NEW.buyer_scheme IS NULL OR NEW.buyer_identifier IS NULL OR NEW.seller_scheme IS NULL OR NEW.seller_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TRIGGER negotiation_messages_principal_insert
    BEFORE INSERT ON negotiation_messages
    WHEN NEW.sender_role IS NULL OR NEW.sender_scheme IS NULL OR NEW.sender_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TRIGGER negotiation_messages_principal_update
    BEFORE UPDATE ON negotiation_messages
    WHEN NEW.sender_role IS NULL OR NEW.sender_scheme IS NULL OR NEW.sender_identifier IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'canonical principal fields are required');
    END
    """,
    """
    CREATE TABLE storefront_listing_bindings (
      listing_id TEXT PRIMARY KEY,
      site_id TEXT NOT NULL,
      pool_id TEXT,
      physical_resource_id TEXT,
      offering_mode TEXT NOT NULL,
      domain_identity TEXT NOT NULL,
      contract_major INTEGER NOT NULL CHECK (contract_major >= 1),
      contract_minor INTEGER NOT NULL CHECK (contract_minor >= 0),
      derivation_key TEXT NOT NULL UNIQUE,
      source_envelope_json TEXT NOT NULL,
      last_reconciled_at TEXT NOT NULL,
      capacity_backing TEXT CHECK (capacity_backing IN ('backed', 'unbacked')),
      FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
    )
    """,
    "CREATE INDEX idx_storefront_listing_bindings_site"
    " ON storefront_listing_bindings(site_id, offering_mode)",
    "CREATE INDEX idx_storefront_listing_bindings_domain"
    " ON storefront_listing_bindings(domain_identity, contract_major, contract_minor)",
    "CREATE INDEX idx_negotiation_threads_domain_binding"
    " ON negotiation_threads(domain_identity, contract_major, contract_minor, offering_mode)",
    "CREATE INDEX idx_negotiation_threads_domain_listing"
    " ON negotiation_threads(domain_listing_id)",
    """
    CREATE TABLE storefront_domain_artifacts (
      negotiation_id TEXT NOT NULL,
      artifact_slot TEXT NOT NULL,
      offering_mode TEXT NOT NULL,
      domain_identity TEXT NOT NULL,
      contract_major INTEGER NOT NULL CHECK (contract_major >= 1),
      contract_minor INTEGER NOT NULL CHECK (contract_minor >= 0),
      artifact_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (
        STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
      ),
      PRIMARY KEY (negotiation_id, artifact_slot),
      FOREIGN KEY (negotiation_id)
        REFERENCES negotiation_threads(negotiation_id)
    )
    """,
    "CREATE INDEX idx_storefront_domain_artifacts_binding"
    " ON storefront_domain_artifacts(domain_identity, contract_major, contract_minor, offering_mode)",
    """
    CREATE TRIGGER storefront_listing_binding_insert_owner
    BEFORE INSERT ON storefront_listing_bindings
    WHEN NOT EXISTS (
      SELECT 1 FROM listings WHERE listing_id = NEW.listing_id
    )
    BEGIN
      SELECT RAISE(ABORT, 'listing binding requires an existing listing');
    END
    """,
    """
    CREATE TRIGGER negotiation_domain_binding_complete_insert
    BEFORE INSERT ON negotiation_threads
    WHEN (
      NEW.domain_listing_id IS NULL
      OR NEW.site_id IS NULL
      OR NEW.offering_mode IS NULL
      OR NEW.domain_identity IS NULL
      OR NEW.contract_major IS NULL
      OR NEW.contract_minor IS NULL
    ) AND NOT (
      NEW.domain_listing_id IS NULL
      AND NEW.site_id IS NULL
      AND NEW.offering_mode IS NULL
      AND NEW.domain_identity IS NULL
      AND NEW.contract_major IS NULL
      AND NEW.contract_minor IS NULL
    )
    BEGIN
      SELECT RAISE(ABORT, 'negotiation domain binding is incomplete');
    END
    """,
    """
    CREATE TRIGGER negotiation_domain_binding_owner_insert
    BEFORE INSERT ON negotiation_threads
    WHEN NEW.domain_identity IS NOT NULL
      AND NOT EXISTS (
        SELECT 1
        FROM storefront_listing_bindings binding
        WHERE binding.listing_id = NEW.domain_listing_id
          AND binding.site_id = NEW.site_id
          AND binding.offering_mode = NEW.offering_mode
          AND binding.domain_identity = NEW.domain_identity
          AND binding.contract_major = NEW.contract_major
          AND binding.contract_minor = NEW.contract_minor
      )
    BEGIN
      SELECT RAISE(ABORT, 'negotiation domain binding disagrees with listing');
    END
    """,
    """
    CREATE TRIGGER negotiation_domain_binding_immutable
    BEFORE UPDATE OF
      domain_listing_id, site_id, offering_mode, domain_identity,
      contract_major, contract_minor
    ON negotiation_threads
    WHEN OLD.domain_identity IS NOT NULL
      AND (
        NOT (OLD.domain_listing_id IS NEW.domain_listing_id)
        OR NOT (OLD.site_id IS NEW.site_id)
        OR NOT (OLD.offering_mode IS NEW.offering_mode)
        OR NOT (OLD.domain_identity IS NEW.domain_identity)
        OR NOT (OLD.contract_major IS NEW.contract_major)
        OR NOT (OLD.contract_minor IS NEW.contract_minor)
      )
    BEGIN
      SELECT RAISE(ABORT, 'negotiation domain binding is immutable');
    END
    """,
    """
    CREATE TRIGGER negotiation_domain_binding_owner_update
    BEFORE UPDATE OF
      domain_listing_id, site_id, offering_mode, domain_identity,
      contract_major, contract_minor
    ON negotiation_threads
    WHEN NEW.domain_identity IS NOT NULL
      AND NOT EXISTS (
        SELECT 1
        FROM storefront_listing_bindings binding
        WHERE binding.listing_id = NEW.domain_listing_id
          AND binding.site_id = NEW.site_id
          AND binding.offering_mode = NEW.offering_mode
          AND binding.domain_identity = NEW.domain_identity
          AND binding.contract_major = NEW.contract_major
          AND binding.contract_minor = NEW.contract_minor
      )
    BEGIN
      SELECT RAISE(ABORT, 'negotiation domain binding disagrees with listing');
    END
    """,
    """
    CREATE TRIGGER storefront_domain_artifact_owner_insert
    BEFORE INSERT ON storefront_domain_artifacts
    WHEN NOT EXISTS (
      SELECT 1
      FROM negotiation_threads thread
      WHERE thread.negotiation_id = NEW.negotiation_id
        AND thread.offering_mode = NEW.offering_mode
        AND thread.domain_identity = NEW.domain_identity
        AND thread.contract_major = NEW.contract_major
        AND thread.contract_minor = NEW.contract_minor
    )
    BEGIN
      SELECT RAISE(ABORT, 'domain artifact disagrees with negotiation binding');
    END
    """,
    """
    CREATE TRIGGER storefront_domain_artifact_immutable
    BEFORE UPDATE ON storefront_domain_artifacts
    WHEN NOT (OLD.negotiation_id IS NEW.negotiation_id)
      OR NOT (OLD.artifact_slot IS NEW.artifact_slot)
      OR NOT (OLD.offering_mode IS NEW.offering_mode)
      OR NOT (OLD.domain_identity IS NEW.domain_identity)
      OR NOT (OLD.contract_major IS NEW.contract_major)
      OR NOT (OLD.contract_minor IS NEW.contract_minor)
      OR NOT (OLD.artifact_json IS NEW.artifact_json)
    BEGIN
      SELECT RAISE(ABORT, 'storefront domain artifact is immutable');
    END
    """,
    """
    CREATE TRIGGER storefront_listing_binding_immutable
    BEFORE UPDATE OF
      listing_id, site_id, pool_id, physical_resource_id, offering_mode,
      domain_identity, contract_major, contract_minor, derivation_key,
      source_envelope_json, capacity_backing
    ON storefront_listing_bindings
    WHEN NOT (OLD.listing_id IS NEW.listing_id)
      OR NOT (OLD.site_id IS NEW.site_id)
      OR NOT (OLD.pool_id IS NEW.pool_id)
      OR NOT (OLD.physical_resource_id IS NEW.physical_resource_id)
      OR NOT (OLD.offering_mode IS NEW.offering_mode)
      OR NOT (OLD.domain_identity IS NEW.domain_identity)
      OR NOT (OLD.contract_major IS NEW.contract_major)
      OR NOT (OLD.contract_minor IS NEW.contract_minor)
      OR NOT (OLD.derivation_key IS NEW.derivation_key)
      OR NOT (OLD.source_envelope_json IS NEW.source_envelope_json)
      OR NOT (OLD.capacity_backing IS NEW.capacity_backing)
    BEGIN
      SELECT RAISE(ABORT, 'storefront listing binding is immutable');
    END
    """,
    """
    CREATE TRIGGER storefront_listing_binding_backing_required
    BEFORE INSERT ON storefront_listing_bindings
    WHEN NEW.capacity_backing IS NULL
    BEGIN
      SELECT RAISE(ABORT, 'listing binding requires capacity_backing');
    END
    """,
    """
    CREATE TRIGGER listing_closed_by_consistent_insert
    BEFORE INSERT ON listings
    WHEN (NEW.status = 'closed' AND NEW.closed_by IS NULL)
      OR (NEW.status IS NOT 'closed' AND NEW.closed_by IS NOT NULL)
    BEGIN
      SELECT RAISE(
        ABORT, 'a closed listing records closed_by; an open one does not'
      );
    END
    """,
    """
    CREATE TRIGGER listing_closed_by_consistent_update
    BEFORE UPDATE ON listings
    WHEN (NEW.status = 'closed' AND NEW.closed_by IS NULL)
      OR (NEW.status IS NOT 'closed' AND NEW.closed_by IS NOT NULL)
    BEGIN
      SELECT RAISE(
        ABORT, 'a closed listing records closed_by; an open one does not'
      );
    END
    """,
    """
    CREATE TABLE credentials (
      id TEXT PRIMARY KEY,
      listing_id TEXT NOT NULL,
      role TEXT NOT NULL,
      granted_to TEXT NOT NULL,
      password TEXT,
      ssh_commands TEXT,
      ssh_key_path_host TEXT,
      key_type TEXT,
      created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_credentials_listing_id ON credentials(listing_id)",
    "CREATE INDEX idx_credentials_listing_granted ON credentials(listing_id, granted_to)",
    "CREATE INDEX idx_negotiation_messages_negotiation_id ON negotiation_messages(negotiation_id)",
    "CREATE INDEX idx_negotiation_messages_round ON negotiation_messages(negotiation_id, round)",
    "CREATE INDEX idx_negotiation_threads_our_listing_id ON negotiation_threads(our_listing_id)",
    "CREATE INDEX idx_negotiation_threads_their_listing_id ON negotiation_threads(their_listing_id)",
    "CREATE INDEX idx_negotiation_threads_our_agent_id ON negotiation_threads(our_agent_id)",
    "CREATE INDEX idx_negotiation_threads_their_agent_id ON negotiation_threads(their_agent_id)",
    "CREATE INDEX idx_negotiation_threads_status ON negotiation_threads(status)",
    "CREATE INDEX idx_listings_status ON listings(status)",
    "CREATE INDEX idx_listings_created_at ON listings(created_at)",
    "CREATE INDEX idx_listings_updated_at ON listings(updated_at)",
    """
    CREATE TABLE stage_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      stage TEXT NOT NULL,
      event TEXT NOT NULL,
      negotiation_id TEXT,
      listing_id TEXT,
      escrow_uid TEXT,
      data TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_stage_events_ts ON stage_events(ts)",
    "CREATE INDEX idx_stage_events_stage ON stage_events(stage)",
    "CREATE INDEX idx_stage_events_negotiation_id ON stage_events(negotiation_id)",
    """
    CREATE TABLE escrows (
      escrow_uid TEXT PRIMARY KEY,
      negotiation_id TEXT NOT NULL,
      status TEXT NOT NULL,
      chain_name TEXT,
      escrow_address TEXT,
      is_primary INTEGER NOT NULL DEFAULT 1,
      fulfillment_uid TEXT,
      provisioning_job_id TEXT,
      connection_details TEXT,
      tenant_credentials TEXT,
      reason TEXT,
      capacity_reservation_id TEXT,
      settlement_resource_id TEXT,
      fulfillment_id TEXT,
      fulfillment_context TEXT,
      fulfillment_phase TEXT,
      processing_owner TEXT,
      processing_lease_until TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_escrows_status ON escrows(status)",
    "CREATE INDEX idx_escrows_negotiation ON escrows(negotiation_id)",
    """
    CREATE TABLE deal_heartbeats (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      deal_ref TEXT NOT NULL,
      buyer_scheme TEXT NOT NULL,
      buyer_identifier TEXT NOT NULL,
      seller_scheme TEXT NOT NULL,
      seller_identifier TEXT NOT NULL,
      sent_at_unix REAL NOT NULL,
      payload TEXT,
      received_at_unix REAL NOT NULL
    )
    """,
    "CREATE INDEX idx_heartbeats_deal ON deal_heartbeats(deal_ref, sent_at_unix)",
    """
    CREATE TABLE auth_replay_reservations (
      principal_scheme TEXT NOT NULL,
      principal_identifier TEXT NOT NULL,
      request_id TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      response_status INTEGER,
      response_body TEXT,
      attempt_token TEXT,
      lease_until INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY (principal_scheme, principal_identifier, request_id)
    )
    """,
    """
    CREATE TABLE service_peers (
      peer_id TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      site_id TEXT NOT NULL,
      principal_scheme TEXT NOT NULL,
      principal_identifier TEXT NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'retired')),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (role, site_id),
      UNIQUE (role, principal_scheme, principal_identifier)
    )
    """,
    """
    CREATE TABLE identity_subjects (
      authority TEXT NOT NULL,
      subject TEXT NOT NULL,
      role TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (authority, subject)
    )
    """,
    """
    CREATE TABLE identity_bindings (
      authority TEXT NOT NULL,
      subject TEXT NOT NULL,
      principal_scheme TEXT NOT NULL,
      principal_identifier TEXT NOT NULL,
      status TEXT NOT NULL CHECK (
        status IN ('primary', 'overlap', 'disabled', 'retired')
      ),
      overlap_until INTEGER,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (
        authority, subject, principal_scheme, principal_identifier
      ),
      FOREIGN KEY (authority, subject)
        REFERENCES identity_subjects(authority, subject)
    )
    """,
    """
    CREATE UNIQUE INDEX idx_identity_binding_active_owner
    ON identity_bindings (
      authority, principal_scheme, principal_identifier
    )
    WHERE status IN ('primary', 'overlap')
    """,
    """
    CREATE TABLE identity_rotations (
      authority TEXT NOT NULL,
      subject TEXT NOT NULL,
      nonce TEXT NOT NULL,
      intent_hash TEXT NOT NULL,
      current_scheme TEXT NOT NULL,
      current_identifier TEXT NOT NULL,
      replacement_scheme TEXT NOT NULL,
      replacement_identifier TEXT NOT NULL,
      overlap_until INTEGER NOT NULL,
      applied_at INTEGER NOT NULL,
      PRIMARY KEY (authority, subject, nonce)
    )
    """,
    """
    CREATE TABLE identity_claims (
      claim_id TEXT PRIMARY KEY,
      resource_id TEXT NOT NULL,
      role TEXT NOT NULL,
      principal_scheme TEXT NOT NULL,
      principal_identifier TEXT NOT NULL,
      operation_id TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE (resource_id, role, operation_id)
    )
    """,
    """
    CREATE TABLE identity_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      authority TEXT NOT NULL,
      subject TEXT NOT NULL,
      action TEXT NOT NULL,
      actor_scheme TEXT NOT NULL,
      actor_identifier TEXT NOT NULL,
      target_scheme TEXT,
      target_identifier TEXT,
      operation_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      UNIQUE (authority, operation_id)
    )
    """,
    """
    CREATE TABLE publications (
      listing_id TEXT NOT NULL,
      registry_url TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      published_at INTEGER NOT NULL,
      registry_assigned_id TEXT,
      status TEXT NOT NULL,
      last_error TEXT,
      PRIMARY KEY (listing_id, registry_url)
    )
    """,
    "CREATE INDEX idx_publications_registry ON publications(registry_url)",
    "CREATE INDEX idx_publications_status ON publications(status)",
)

BASELINE_TABLES: frozenset[str] = frozenset(
    {
        "negotiation_threads",
        "negotiation_local_state",
        "negotiation_messages",
        "listings",
        "capacity_holds",
        "storefront_listing_bindings",
        "storefront_domain_artifacts",
        "credentials",
        "stage_events",
        "escrows",
        "deal_heartbeats",
        "auth_replay_reservations",
        "service_peers",
        "identity_subjects",
        "identity_bindings",
        "identity_rotations",
        "identity_claims",
        "identity_audit",
        "publications",
    }
)
"""The tables :data:`BASELINE` creates."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_core_storefront", _create_baseline
)
"""Core's market state as the v0.3.0 release's storefront client built it."""


def _add_negotiation_message_terms(connection: sqlite3.Connection) -> None:
    """Keep delivery terms alongside each scalar in the transcript."""
    connection.execute("ALTER TABLE negotiation_messages ADD COLUMN provision_terms TEXT")


def _add_publication_published_payload(connection: sqlite3.Connection) -> None:
    """Keep each registry's last successfully published payload.

    ``payload_json`` records the last attempt, failed or not; this column only
    a successful publish writes. No row is backfilled: an earlier attempt's
    payload is not known to be one a registry accepted, so a listing has none
    until its next successful publish.
    """
    connection.execute("ALTER TABLE publications ADD COLUMN published_payload_json TEXT")


def _name_negotiated_scalar(connection: sqlite3.Connection) -> None:
    """Name the accepted negotiation quantity for what it is.

    The column holds the domain's negotiated policy scalar — a basis-point
    multiplier on shape-priced listings, an absolute amount on flat paths —
    not a price; the accepted Agreement carries the monetary amount. Each
    thread keeps its stored value under the new column name.
    """
    connection.execute(
        "ALTER TABLE negotiation_threads RENAME COLUMN agreed_price TO negotiated_scalar"
    )


MIGRATIONS: tuple[Migration[sqlite3.Connection], ...] = (
    Migration("20261106_001_negotiation_message_terms", _add_negotiation_message_terms),
    Migration(
        "20261111_001_publication_published_payload",
        _add_publication_published_payload,
    ),
    Migration(
        "20261111_002_negotiation_negotiated_scalar",
        _name_negotiated_scalar,
    ),
)
"""Core's migrations after the baseline, composed by every storefront chain."""
