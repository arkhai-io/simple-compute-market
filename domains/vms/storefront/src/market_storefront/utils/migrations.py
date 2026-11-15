"""The VM storefront's migration chain.

The chain composes core storefront's baseline, the baselines of the kits whose
tables the storefront holds (the settlement runtime, contact exchange, and the
pool-override store), and the VM domain's own, in that order, then every
migration after the baseline. The baselines reproduce the database the
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

MIGRATION_COMMAND = "market-storefront-migrate"
"""The storefront's migration command's name, which every refusal names as the
remedy; the command applies :data:`CHAIN` through :func:`migrate_storefront_database`."""

_BASELINE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE vm_settlement_evidence (
      negotiation_id TEXT PRIMARY KEY,
      mechanism TEXT NOT NULL,
      agreement_sha256 TEXT NOT NULL,
      settlement_ref TEXT UNIQUE,
      status TEXT NOT NULL
        CHECK (status IN ('pending', 'verified', 'refunding', 'refunded')),
      evidence_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE vm_delivery_records (
      negotiation_id TEXT PRIMARY KEY REFERENCES vm_settlement_evidence(negotiation_id),
      status TEXT NOT NULL,
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
    # A settlement job is bound to the exact obligation it accepted; core's
    # escrows table carries no obligation identity of its own.
    "ALTER TABLE escrows ADD COLUMN obligation_ref TEXT",
    "ALTER TABLE escrows ADD COLUMN obligation_index INTEGER",
    "CREATE UNIQUE INDEX idx_escrows_obligation_ref"
    " ON escrows(obligation_ref) WHERE obligation_ref IS NOT NULL",
    "CREATE INDEX idx_escrows_negotiation_obligation"
    " ON escrows(negotiation_id, obligation_index)",
)

BASELINE_TABLES: frozenset[str] = frozenset(
    {"vm_settlement_evidence", "vm_delivery_records"}
)
"""The tables :data:`BASELINE` creates; it also adds the obligation columns and
indexes to core's ``escrows``."""


def _create_baseline(connection: sqlite3.Connection) -> None:
    for statement in _BASELINE_DDL:
        connection.execute(statement)


BASELINE: Migration[sqlite3.Connection] = Migration(
    "v0_3_0_baseline_vms_storefront", _create_baseline
)
"""The VM domain's settlement and delivery records as the v0.3.0 release built them."""


def _add_delivery_activation(connection: sqlite3.Connection) -> None:
    """Add the site's activation instant, and read a provider-ready phase as ``ready``.

    ``activated_at_utc`` is the instant the site returned when it activated the
    lease; a null records no activation, which is all it means for a delivery
    that became available without one. The phase ``ready`` is the provider
    reporting the VM active, and ``activate`` names only the site's transition
    of the lease, so a row whose phase records readiness as ``activate`` is
    rewritten to ``ready``.
    """
    connection.execute("ALTER TABLE vm_delivery_records ADD COLUMN activated_at_utc INTEGER")
    connection.execute(
        "UPDATE vm_delivery_records SET fulfillment_phase='ready' "
        "WHERE fulfillment_phase='activate'"
    )


def _clear_vm_credentials(connection: sqlite3.Connection) -> None:
    """Remove every stored copy of a VM tenant's credentials.

    A VM's credentials are read live from provisioning's fulfillment result
    and never stored, so the copies an earlier storefront kept are removed:
    the delivery records' and escrows' ``tenant_credentials``, and the rows of
    core's ``credentials`` table for every listing not bound to another
    offering mode, a combined storefront's other domains included. Core's replay
    table records no route, so the ``tenant_credentials`` member is removed
    from every recorded response body that has one, whatever route wrote it; a
    stripped body is still a recorded body, so each record keeps its status and
    remains a completed outcome.
    """
    for table in ("vm_delivery_records", "escrows"):
        connection.execute(
            f"UPDATE {table} SET tenant_credentials = NULL "
            "WHERE tenant_credentials IS NOT NULL"
        )
    connection.execute(
        "DELETE FROM credentials WHERE listing_id NOT IN ("
        "SELECT listing_id FROM storefront_listing_bindings WHERE offering_mode != 'vm')"
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
        if not isinstance(body, dict) or "tenant_credentials" not in body:
            continue
        stripped = {key: value for key, value in body.items() if key != "tenant_credentials"}
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
    """Create the deal-servicing tables the v0.3.0 release created at store open.

    That release created them when a lifecycle store opened, some only when a
    deal's delivery was first registered, so an adopted database may hold all,
    some, or none of them; their DDL tolerates the ones present, and this is the
    one migration of the chain that does. On a fresh database it creates them.
    """
    create_servicing_schema(connection)


# The physical inventory the storefront once held. Nothing reads or writes
# these tables: inventory is read from site projections. A database an older
# storefront created may still hold them, and a v0.3.0 database never created
# them, so each is dropped only where present.
_FROZEN_INVENTORY_TABLES = (
    "compute_allocations",
    "resource_transition_events",
    "compute_pool_members",
    "resources",
    "hosts",
    "compute_capacity_pools",
    "compute_inventory_pools",
)


def _drop_frozen_inventory(connection: sqlite3.Connection) -> None:
    for table in _FROZEN_INVENTORY_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")


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
    "20260604_003_derived_compute_listing_pool_ids",
    "20260810_009_escrow_settlement_identity",
    "20261006_011_connection_details_to_delivery",
    "20261006_012_fulfillment_context_names_no_guest",
    "20261001_011_vm_settlement_records",
    "20261027_001_fulfillment_context_carries_no_connectivity",
)
"""Every ID the v0.3.0 release's VM storefront chain recorded."""

CHAIN: Chain[sqlite3.Connection] = Chain(
    service="the VM storefront",
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
        Migration("20261106_001_vm_delivery_activation", _add_delivery_activation),
        Migration("20261106_002_vm_credentials_cleared", _clear_vm_credentials),
        Migration("20261109_001_vm_store_open_tables", _create_store_open_tables),
        Migration("20261109_002_vm_frozen_inventory_dropped", _drop_frozen_inventory),
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
