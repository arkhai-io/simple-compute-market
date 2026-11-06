"""The bare-metal storefront's migration chain.

The chain composes core storefront's baseline, the baselines of the kits whose
tables the storefront holds (the settlement runtime, contact exchange, and the
pool-override store), and the bare-metal domain's own, in that order, then
every migration after the baseline. The baselines reproduce the database the
marketplace v0.3.0 release's storefront built at construction; a database
recording every ID that release's chain recorded (:data:`FLOOR_IDS`) is adopted
at the baseline without running it. A later change to any of these tables is a
migration appended to :data:`CHAIN`, never an edit to a baseline.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core_storefront import migrations as core_migrations
from market_contact_exchange import migrations as contact_exchange_migrations
from market_deal_servicing import create_schema as create_servicing_schema
from market_pool_overrides import migrations as pool_override_migrations
from market_schema_migrations import (
    Chain,
    CheckResult,
    MigrateReport,
    Migration,
    SqliteMigrationConnection,
    check_sqlite_file,
    migrate,
    refusal_message,
)
from market_settlement_runtime import migrations as settlement_migrations

MIGRATION_COMMAND = "bare-metal-storefront-migrate"
"""The storefront's migration command's name, which every refusal names as the
remedy; the command applies :data:`CHAIN` through :func:`migrate_storefront_database`."""

_BASELINE_DDL: tuple[str, ...] = (
    # Each capacity reservation's site and the service peer that site is bound
    # to, so a later release or end reaches the site that holds the reservation.
    """
    CREATE TABLE bare_metal_selected_site_bindings (
      capacity_reservation_id TEXT PRIMARY KEY,
      site_id TEXT NOT NULL,
      service_peer TEXT NOT NULL,
      authority_scheme TEXT NOT NULL,
      authority_identifier TEXT NOT NULL,
      created_at TEXT NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
      updated_at TEXT NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
      CHECK (LENGTH(TRIM(capacity_reservation_id)) > 0),
      CHECK (LENGTH(TRIM(site_id)) > 0),
      CHECK (LENGTH(TRIM(service_peer)) > 0),
      CHECK (LENGTH(TRIM(authority_scheme)) > 0),
      CHECK (LENGTH(TRIM(authority_identifier)) > 0)
    )
    """,
    "CREATE INDEX idx_bare_metal_selected_site ON bare_metal_selected_site_bindings(site_id)",
    """
    CREATE TABLE bare_metal_fulfillment_lifecycle (
      negotiation_id TEXT PRIMARY KEY,
      settlement_ref TEXT NOT NULL UNIQUE,
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
      lease_ready_evidence_json TEXT,
      lease_ready_evidence_digest TEXT,
      evidence_rejections INTEGER NOT NULL DEFAULT 0,
      CHECK (LENGTH(TRIM(negotiation_id)) > 0),
      CHECK (LENGTH(TRIM(settlement_ref)) > 0),
      CHECK (LENGTH(TRIM(site_id)) > 0),
      CHECK (LENGTH(TRIM(physical_resource_id)) > 0)
    )
    """,
    "CREATE INDEX idx_bare_metal_fulfillment_state ON bare_metal_fulfillment_lifecycle(state)",
    """
    CREATE TRIGGER bare_metal_selected_site_immutable
    BEFORE UPDATE OF
      capacity_reservation_id, site_id, service_peer,
      authority_scheme, authority_identifier
    ON bare_metal_selected_site_bindings
    WHEN NOT (
      OLD.capacity_reservation_id IS NEW.capacity_reservation_id
      AND OLD.site_id IS NEW.site_id
      AND OLD.service_peer IS NEW.service_peer
      AND OLD.authority_scheme IS NEW.authority_scheme
      AND OLD.authority_identifier IS NEW.authority_identifier
    )
    BEGIN
      SELECT RAISE(
        ABORT,
        'bare-metal selected-site authority binding is immutable'
      );
    END
    """,
    """
    CREATE TABLE bare_metal_settlement_records (
      negotiation_id TEXT PRIMARY KEY,
      mechanism TEXT NOT NULL,
      agreement_sha256 TEXT NOT NULL,
      settlement_ref TEXT UNIQUE,
      status TEXT NOT NULL CHECK (
        status IN (
          'accepted', 'settlement_verified', 'failed', 'refunding', 'refunded'
        )
      ),
      evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
      created_at TEXT NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
      updated_at TEXT NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
    "CREATE UNIQUE INDEX idx_bare_metal_fulfillment_evidence_digest"
    " ON bare_metal_fulfillment_lifecycle(lease_ready_evidence_digest)"
    " WHERE lease_ready_evidence_digest IS NOT NULL",
    # The listing record each negotiation's opening was authorized against.
    """
    CREATE TABLE bare_metal_opening_listings (
      negotiation_id TEXT PRIMARY KEY,
      listing_json TEXT NOT NULL CHECK (json_valid(listing_json)),
      created_at TEXT NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
)

BASELINE_TABLES: frozenset[str] = frozenset(
    {
        "bare_metal_selected_site_bindings",
        "bare_metal_fulfillment_lifecycle",
        "bare_metal_settlement_records",
        "bare_metal_opening_listings",
    }
)
"""The tables :data:`BASELINE` creates."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_bare_metal_storefront", _create_baseline
)
"""The bare-metal domain's tables as the v0.3.0 release built them."""


#: The members of a recorded access response that say how to reach the host.
_ACCESS_MATERIAL = ("host", "port", "username")


def _add_delivery_activation(connection: sqlite3.Connection) -> None:
    """Record the site's activation instant, and clear recorded access responses.

    ``activated_at_utc`` is the instant, in Unix seconds, the site returned when
    it activated the lease; a null records no activation, which is all it means
    for a delivery that became available without one. Access is read live and
    never replayed, and core's replay table records no route, so the host, port
    and username are removed from every recorded body shaped as an access
    response, one whose ``method`` is ``ssh``: no other route's body carries
    those members. A stripped body is still a recorded body, so each record
    keeps its status and remains a completed outcome.

    A delivery whose materialization, the fulfillment request, was saved but
    whose fulfillment identity was never recorded may have reached
    provisioning, so it is marked dispatched (state ``dispatch``): delivery
    then repeats the same request and adopts the fulfillment provisioning
    accepted, and an end ends it through the lease rather than releasing its
    capacity.
    """
    connection.execute(
        "ALTER TABLE bare_metal_fulfillment_lifecycle ADD COLUMN activated_at_utc INTEGER"
    )
    connection.execute(
        "UPDATE bare_metal_fulfillment_lifecycle SET state='dispatch' "
        "WHERE fulfillment_id IS NULL AND capacity_reservation_id IS NOT NULL "
        "AND state NOT IN ('dispatch', 'released', 'terminating') "
        "AND EXISTS (SELECT 1 FROM storefront_domain_artifacts a "
        "WHERE a.negotiation_id = bare_metal_fulfillment_lifecycle.negotiation_id "
        "AND a.artifact_slot = 'materialization')"
    )
    rows = connection.execute(
        "SELECT principal_scheme, principal_identifier, request_id, response_body "
        "FROM auth_replay_reservations WHERE response_body IS NOT NULL"
    ).fetchall()
    for scheme, identifier, request_id, raw in rows:
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(body, dict)
            or body.get("method") != "ssh"
            or not any(member in body for member in _ACCESS_MATERIAL)
        ):
            continue
        stripped = {key: value for key, value in body.items() if key not in _ACCESS_MATERIAL}
        connection.execute(
            "UPDATE auth_replay_reservations SET response_body = ? "
            "WHERE principal_scheme = ? AND principal_identifier = ? AND request_id = ?",
            (
                json.dumps(stripped, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                scheme,
                identifier,
                request_id,
            ),
        )


def _create_store_open_tables(connection: sqlite3.Connection) -> None:
    """Create the tables the v0.3.0 release created when its lifecycle store opened.

    Deal servicing's tables and the lifecycle's continuation cursor: that
    release created them when the store opened, so an adopted database holds
    them only if its store ever did. Their DDL tolerates the ones present, and
    this is the one migration of the chain that does. On a fresh database it
    creates them.
    """
    create_servicing_schema(connection)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS bare_metal_lifecycle_cursor "
        "(id INTEGER PRIMARY KEY CHECK (id=1), continuation TEXT)"
    )


def _drop_accepted_site_generations(connection: sqlite3.Connection) -> None:
    """Drop the projection generations publication once accepted, where present.

    Nothing reads or writes the table; a v0.3.0 database holds it only if an
    earlier release created it.
    """
    connection.execute("DROP TABLE IF EXISTS bare_metal_accepted_site_generations")


FLOOR_IDS: tuple[str, ...] = (
    "20260604_000_listing_resource_timestamps",
    "20260604_004_negotiation_amount_text_columns",
    "20260604_005_escrows_and_listings",
    "20260722_001_capacity_holds_reservation_id",
    "20260810_003_negotiation_provision_terms",
    "20260811_001_marketplace_principals_v2",
    "20260811_002_replay_attempt_leases",
    "20260815_001_storefront_domain_bindings",
    "20260911_001_listing_resource_column",
    "20260923_001_listing_binding_capacity_backing",
    "20260923_002_listing_binding_capacity_backing_required",
    "20260923_003_listing_closed_by",
    "20261001_001_listing_rate_structure",
    "20260810_001_settlement_obligation_lifecycle",
    "20260810_002_settlement_servicing_runtime",
    "20260811_003_settlement_principal_authorization",
    "20260815_004_settlement_mechanism_materialization_params",
    "20261028_005_settlement_operation_awaiting_delivery",
    "20260815_006_contact_introductions",
    "20261001_007_contact_introduction_tombstones",
    "20261027_008_contact_introduction_seller_dispatch_claims",
    "20260925_001_pool_overrides",
    "20261001_001_pool_override_asking_rates",
    "bare-metal-storefront-0009-refuse-retired-listing-kind",
    "bare-metal-storefront-0001-agreement-payloads",
    "bare-metal-storefront-0002-derived-publications",
    "bare-metal-storefront-0003-operator-state",
    "bare-metal-storefront-0004-selected-site-bindings",
    "bare-metal-storefront-0005-fulfillment-lifecycle",
    "bare-metal-storefront-0006-common-domain-bindings",
    "bare-metal-storefront-0007-selected-site-immutability",
    "bare-metal-storefront-0008-settlement-records",
    "bare-metal-storefront-0010-drop-derived-publications",
    "bare-metal-storefront-0012-retire-storefront-negotiation",
    "bare-metal-storefront-0013-alkahest-lease-ready-evidence",
    "bare-metal-storefront-0014-refuse-reservations-without-their-peer",
    "bare-metal-storefront-0015-opening-listings",
)
"""Every ID the v0.3.0 release's bare-metal storefront chain recorded."""

CHAIN: Chain[sqlite3.Connection] = Chain(
    service="the bare-metal storefront",
    command=MIGRATION_COMMAND,
    baselines=(
        core_migrations.BASELINE,
        settlement_migrations.BASELINE,
        contact_exchange_migrations.BASELINE,
        pool_override_migrations.BASELINE,
        BASELINE,
    ),
    migrations=(
        *core_migrations.MIGRATIONS,
        Migration("bare-metal-storefront-0016-delivery-activation", _add_delivery_activation),
        Migration("bare-metal-storefront-0017-store-open-tables", _create_store_open_tables),
        Migration(
            "bare-metal-storefront-0018-drop-accepted-site-generations",
            _drop_accepted_site_generations,
        ),
    ),
    floor_ids=FLOOR_IDS,
)


def migrate_storefront_database(db_path: str | Path) -> MigrateReport:
    """Apply :data:`CHAIN` to the database at ``db_path``, creating it if absent.

    Refuses an ahead or unsupported database applying nothing
    (``MigrationRefused``); a failing migration leaves the ones before it
    recorded (``MigrationFailed``).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        return migrate(CHAIN, SqliteMigrationConnection(connection))
    finally:
        connection.close()


class IncompatibleStorefrontDatabase(RuntimeError):
    """The database is not exactly at the chain this image carries."""

    def __init__(self, result: CheckResult) -> None:
        super().__init__(
            refusal_message(result, service=CHAIN.service, command=CHAIN.command)
        )
        self.result = result


def check_storefront_database(db_path: str | Path) -> CheckResult:
    """The database's state against :data:`CHAIN`, read without changing it.

    The file is opened read-only, so a missing database is *absent* and is not
    created.
    """
    return check_sqlite_file(CHAIN, db_path)


def require_compatible_storefront_database(db_path: str | Path) -> None:
    """Refuse to serve a database not exactly at :data:`CHAIN`, naming the command."""
    result = check_storefront_database(db_path)
    if not result.compatible:
        raise IncompatibleStorefrontDatabase(result)
