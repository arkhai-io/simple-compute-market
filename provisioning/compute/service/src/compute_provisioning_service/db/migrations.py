"""Compute provisioning's migration chain.

The chain begins with one baseline per package whose tables the database
holds, each fixed DDL reproducing what the marketplace v0.3.0 release built on
a fresh database, composed in foreign-key order: the resource pools every
pool-scoped table names, the relays, VM's pool configuration, the hosts, the
jobs, this service's own tables, the fulfillment aggregate, and the site
ledger. Every migration merged after that release follows, in order. A
database recording every ID the v0.3.0 chain recorded is adopted at the
baseline; any other database the chain did not build is refused.

Every migration takes only the database connection, never the service's
configuration, so one database migrates to one schema and one set of rows
under any configuration.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import Connection, text

from compute_provisioning.hosts import ConnectionEnvelope, ProtectedValue
from compute_provisioning.hosts.migrations import BASELINE as HOSTS_BASELINE
from compute_provisioning.jobs.migrations import BASELINE as JOBS_BASELINE
from compute_provisioning.relays.migrations import BASELINE as RELAYS_BASELINE
from compute_provisioning_ansible.connection import SSH_CONNECTION_KIND, SshConnectionCodec
from market_fulfillment.migrations import BASELINE as FULFILLMENT_BASELINE
from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_schema_migrations import Chain, Migration
from market_site.migrations import BASELINE as SITE_BASELINE
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS
# VM's pool configuration is VM's table, held in this database; VM's package
# owns its baseline.
from vm_provisioning_adapter.migrations import BASELINE as VM_BASELINE

logger = logging.getLogger(__name__)

SERVICE = "compute provisioning"
COMMAND = "compute-provisioning-migrate"

_SERVICE_BASELINE_DDL = (
    """
    CREATE TABLE provisioning_replay_reservations (
        principal_scheme VARCHAR NOT NULL,
        principal_identifier VARCHAR NOT NULL,
        request_id VARCHAR NOT NULL,
        request_hash VARCHAR NOT NULL,
        dispatch_lease_expires_at DATETIME NOT NULL,
        dispatch_attempt_count INTEGER DEFAULT '1' NOT NULL,
        response_status INTEGER,
        response_body JSON,
        response_body_empty BOOLEAN DEFAULT '0' NOT NULL,
        response_media_type VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        completed_at DATETIME,
        PRIMARY KEY (principal_scheme, principal_identifier, request_id)
    )
    """,
    """
    CREATE TABLE capacity_release_callback_outbox (
        capacity_reservation_id VARCHAR NOT NULL,
        attempt_count INTEGER DEFAULT '0' NOT NULL,
        last_error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        last_attempted_at DATETIME,
        delivered_at DATETIME,
        PRIMARY KEY (capacity_reservation_id)
    )
    """,
    """
    CREATE TABLE lease_end_report_outbox (
        event_id VARCHAR NOT NULL,
        capacity_reservation_id VARCHAR NOT NULL,
        peer VARCHAR NOT NULL,
        report TEXT NOT NULL,
        parked BOOLEAN DEFAULT '0' NOT NULL,
        attempt_count INTEGER DEFAULT '0' NOT NULL,
        last_error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        last_attempted_at DATETIME,
        delivered_at DATETIME,
        PRIMARY KEY (event_id)
    )
    """,
    "CREATE INDEX ix_lease_end_report_outbox_capacity_reservation_id "
    "ON lease_end_report_outbox (capacity_reservation_id)",
    """
    CREATE TABLE provisioning_trusted_principals (
        role VARCHAR NOT NULL,
        principal_scheme VARCHAR NOT NULL,
        principal_identifier VARCHAR NOT NULL,
        generation INTEGER NOT NULL,
        valid_until DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (role, principal_scheme, principal_identifier)
    )
    """,
    """
    CREATE TABLE provisioning_identity_rotation_audit (
        nonce VARCHAR NOT NULL,
        role VARCHAR NOT NULL,
        current_scheme VARCHAR NOT NULL,
        current_identifier VARCHAR NOT NULL,
        replacement_scheme VARCHAR NOT NULL,
        replacement_identifier VARCHAR NOT NULL,
        overlap_seconds INTEGER NOT NULL,
        intent_expires_at INTEGER NOT NULL,
        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (nonce)
    )
    """,
    """
    CREATE TABLE definition_document_imports (
        document_kind VARCHAR NOT NULL,
        digest VARCHAR NOT NULL,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (document_kind)
    )
    """,
)


def _create_service_baseline(connection: Connection) -> None:
    for statement in _SERVICE_BASELINE_DDL:
        connection.exec_driver_sql(statement)


class MigrationDataError(RuntimeError):
    """Stored data a migration cannot map without guessing; it rewrote nothing."""


def _json_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise MigrationDataError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationDataError(f"{label} must be a JSON object")
    return value


_SSH_VERSION_2 = 2


def _rewrite_ssh_connections_to_version_2(connection: Connection) -> None:
    """Rewrite every host's ``ssh`` connection stored at version 1 to version 2.

    The v0.3.0 chain stored hosts at ``ssh`` version 1, which no codec serves,
    so such a host runs no work and every job dispatched to it fails before
    its playbook. Version 2 is version 1 with one optional field,
    ``public_port``, which falls back to the connection's port when absent, so
    the mapping is exact: the version changes and the public fields and
    protected values stay byte for byte as stored. Each connection's public
    fields are first checked by the ``ssh`` codec, which neither encrypts nor
    decrypts; if it refuses any, the migration fails naming every refused host
    and rewrites none.

    The target version is fixed at 2 rather than read from the codec: this
    mapping is exact only from version 1 to version 2. A codec serving another
    version refuses every version-2 envelope it is asked to check, so the
    migration then fails naming each host instead of stamping a version whose
    fields it never mapped.

    Only the host row holds a connection: a job names its host and reads the
    host's connection when it is dispatched, so an unfinished job runs against
    the rewritten one.
    """
    codec = SshConnectionCodec()
    rows = connection.execute(
        text(
            "SELECT host_id, connection_public, connection_protected FROM hosts "
            "WHERE connection_kind = :kind AND connection_version = 1 "
            "ORDER BY host_id"
        ),
        {"kind": SSH_CONNECTION_KIND},
    ).mappings().all()
    refused: list[str] = []
    for row in rows:
        try:
            public = _json_mapping(
                row["connection_public"], label=f"hosts {row['host_id']} connection_public"
            )
            protected = _json_mapping(
                row["connection_protected"],
                label=f"hosts {row['host_id']} connection_protected",
            )
            codec.validate(
                ConnectionEnvelope(
                    kind=SSH_CONNECTION_KIND,
                    version=_SSH_VERSION_2,
                    public=public,
                    protected={
                        name: ProtectedValue.from_stored(value)
                        for name, value in protected.items()
                    },
                )
            )
        except (MigrationDataError, ValueError, KeyError, TypeError) as exc:
            refused.append(f"host {row['host_id']!r}: {exc}")
    if refused:
        raise MigrationDataError(
            f"{len(refused)} ssh connection(s) stored at version 1 are not valid at "
            f"version {_SSH_VERSION_2}, so none was rewritten; submit each "
            f"host again at version {_SSH_VERSION_2}, then rerun the migration:\n  "
            + "\n  ".join(refused)
        )
    for row in rows:
        connection.execute(
            text("UPDATE hosts SET connection_version = :version WHERE host_id = :host_id"),
            {"version": _SSH_VERSION_2, "host_id": row["host_id"]},
        )
    if rows:
        logger.info(
            "Rewrote %d ssh connection(s) from version 1 to version %d",
            len(rows),
            _SSH_VERSION_2,
        )


SERVICE_BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_compute_provisioning_service", _create_service_baseline
)
"""This service's own tables as the v0.3.0 release built them."""

SSH_CONNECTIONS_VERSION_2: Migration[Connection] = Migration(
    "20261108_001_ssh_connections_version_2", _rewrite_ssh_connections_to_version_2
)

FLOOR_IDS: tuple[str, ...] = (
    "20260603_001_ansible_jobs_escrow_uid",
    "20260603_002_hosts_public_host",
    "20260603_003_vm_leases_table",
    "20260603_004_vm_leases_allocation_id",
    "20260707_001_site_allocations_executor_fields",
    "20260713_001_ansible_jobs_contract_fields",
    "20260713_002_resource_pools_and_hosts_pool_id",
    "20260720_001_multidimensional_capacity",
    "20260722_001_pools7_capacity_model_cutover",
    "20260724_001_legacy_vm_leases_to_fulfillment",
    "20260724_002_drop_vm_leases_table",
    "20260803_001_ansible_pool_config_vm_size_defaults",
    "20260804_001_hosts_gpu_model",
    "20260811_001_provisioning_replay_reservations",
    "20260815_001_pool_declared_offering_modes",
    "20260901_001_relay_reachable_hosts",
    "20260911_001_reservation_offering_mode_name",
    "20260921_001_host_identity",
    "20260921_002_capacity_declaration_contract",
    "20260921_003_capacity_declaration_attributes",
    "20260921_004_legacy_host_capacity_declarations",
    "20260922_001_pool_advertisement_and_backing",
    "20260927_001_drop_reservation_release_mirror",
    "20261002_001_host_connection_envelope",
    "20261002_002_job_envelopes",
    "20261002_003_bare_metal_job_shapes",
    "20261005_001_drop_job_contract_version",
    "20261005_002_reservation_release_requested_at",
    "20261006_001_drop_job_deal_correlation",
    "20261006_002_vm_job_backed_fulfillment",
    "20261006_003_vm_fulfillment_request_names_no_guest",
    "20261006_004_active_fulfillment_targets_on_reservations",
    "20261019_001_vm_provider_identity",
    "20261023_001_vm_pool_playbook_optional",
    "20261023_002_hosts_pool_optional",
    "20261027_001_vm_fulfillment_request_carries_no_connectivity",
    "20261028_001_retired_reservation_states",
    "20261028_002_hosts_drop_gpu_columns",
    "20261101_001_pool_relays",
    "20261101_002_relay_grant_keys",
    "20261101_003_relay_lease_grants",
    "20261102_001_lease_end_reports",
    "20261106_001_reservation_activated_at",
)
"""Every ID the v0.3.0 release's chain recorded on a database it built."""

CHAIN: Chain[Connection] = Chain(
    service=SERVICE,
    command=COMMAND,
    baselines=(
        POOLS_BASELINE,
        RELAYS_BASELINE,
        VM_BASELINE,
        HOSTS_BASELINE,
        JOBS_BASELINE,
        SERVICE_BASELINE,
        FULFILLMENT_BASELINE,
        SITE_BASELINE,
    ),
    migrations=(*SITE_MIGRATIONS, SSH_CONNECTIONS_VERSION_2),
    floor_ids=FLOOR_IDS,
)
