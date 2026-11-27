"""Compute provisioning's migration chain.

The chain begins with one baseline per package whose tables the database
holds, each fixed DDL reproducing what the marketplace v0.3.0 release built on
a fresh database, composed in foreign-key order: the resource pools every
pool-scoped table names, the relays, VM's pool configuration, the hosts, the
jobs, this service's own tables, the fulfillment aggregate, and the site
ledger. Every migration merged after that release follows, in order. The
chain's floor is marketplace 0.3.0: a database recording every ID the v0.3.0
chain recorded is one that release ran on, and is adopted at the baseline
whatever earlier releases recorded beside those IDs; one recording only some
of them is older than the floor, or another service's sharing its history --
the API-credit service holds the same resource pools and site ledger -- and,
once confirmed as this service's, is upgraded through marketplace 0.3.0 first;
any other database the chain did not build is refused.

Every migration takes only the database connection, never the service's
configuration, so one database migrates to one schema and one set of rows
under any configuration.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Connection, insert, select, text, update

from compute_provisioning.hosts import ConnectionEnvelope, ProtectedValue
from compute_provisioning.hosts.migrations import BASELINE as HOSTS_BASELINE
from compute_provisioning.hosts.migrations import mark_hosts_for_key_adoption
from compute_provisioning.jobs.migrations import BASELINE as JOBS_BASELINE
from compute_provisioning.jobs.migrations import MIGRATIONS as JOBS_MIGRATIONS
from compute_provisioning.relays.migrations import BASELINE as RELAYS_BASELINE
from compute_provisioning_ansible.connection import SSH_CONNECTION_KIND, SshConnectionCodec
from compute_provisioning_contracts import SignedLeaseEndedReport
from eventing import (
    ACTIVE,
    ENVELOPE_VERSION,
    PARKED,
    PENDING,
    Catalogue,
    Envelope,
    EventDraft,
    Kind,
    Source,
)
from eventing import SCHEMA_STEPS as EVENTING_SCHEMA_STEPS
from eventing import schema as event_schema
from market_fulfillment.migrations import BASELINE as FULFILLMENT_BASELINE
from market_resource_pools.migrations import BASELINE as POOLS_BASELINE
from market_schema_migrations import Chain, Floor, Migration
from market_site.events import (
    SITE_CAPACITY_RELEASED,
    SITE_KINDS,
    SITE_LEASE_ENDED,
    CapacityReleasedDetails,
    capacity_released_draft,
    lease_ended_draft,
)
from market_site.migrations import BASELINE as SITE_BASELINE
from market_site.migrations import MIGRATIONS as SITE_MIGRATIONS
# VM's pool configuration is VM's table, held in this database; VM's package
# owns its baseline.
from vm_provisioning_adapter.migrations import BASELINE as VM_BASELINE

from compute_provisioning_service.event_names import (
    CAPACITY_RELEASED_CONSUMER,
    CAPACITY_RELEASED_DESTINATION,
    EVENT_SCHEMA_PREFIX,
    EVENT_SOURCE_SERVICE,
    LEASE_END_REPORT_CONSUMER,
    peer_destination,
)

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
_SSH_VERSION_3 = 3


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

    This step writes version 2. Validation uses only the fields that version
    2 and version 3 share; a version-1 row cannot already carry a host pin.

    Only the host row holds a connection: a job names its host and reads the
    host's connection when it is dispatched, so an unfinished job runs against
    the rewritten one.
    """
    rows = _validated_legacy_ssh_hosts(connection, 1, _SSH_VERSION_2)
    for host_id in rows:
        connection.execute(
            text("UPDATE hosts SET connection_version = :version WHERE host_id = :host_id"),
            {"version": _SSH_VERSION_2, "host_id": host_id},
        )
    if rows:
        logger.info(
            "Rewrote %d ssh connection(s) from version 1 to version %d",
            len(rows),
            _SSH_VERSION_2,
        )


def _validated_legacy_ssh_hosts(
    connection: Connection, source_version: int, destination_version: int
) -> list[str]:
    """Validate the named version's rows before writing any of them."""
    codec = SshConnectionCodec()
    rows = connection.execute(
        text(
            "SELECT host_id, connection_public, connection_protected FROM hosts "
            "WHERE connection_kind = :kind AND connection_version = :version "
            "ORDER BY host_id"
        ),
        {"kind": SSH_CONNECTION_KIND, "version": source_version},
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
            if "host_keys" in public:
                raise ValueError("a connection from before host pinning cannot state host_keys")
            codec.validate(
                ConnectionEnvelope(
                    kind=SSH_CONNECTION_KIND,
                    version=_SSH_VERSION_3,
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
            f"{len(refused)} ssh connection(s) stored at version {source_version} are not valid at "
            f"version {destination_version}, so none was rewritten; restore a database "
            f"backup with valid connection records for these hosts, then rerun the migration:\n  "
            + "\n  ".join(refused)
        )
    return [row["host_id"] for row in rows]


def _rewrite_ssh_connections_to_version_3(connection: Connection) -> None:
    """Mark every upgraded host for adoption without altering its stored fields."""
    host_ids = _validated_legacy_ssh_hosts(connection, _SSH_VERSION_2, _SSH_VERSION_3)
    mark_hosts_for_key_adoption(connection, host_ids, _SSH_VERSION_3)
    if host_ids:
        logger.info("Marked %d SSH hosts for host-key adoption", len(host_ids))


_LEASE_END_REPORTS_DDL = (
    """
    CREATE TABLE lease_end_reports (
        event_id VARCHAR NOT NULL,
        capacity_reservation_id VARCHAR NOT NULL,
        report TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        envelope_id VARCHAR,
        PRIMARY KEY (event_id)
    )
    """,
    "CREATE INDEX ix_lease_end_reports_capacity_reservation_id "
    "ON lease_end_reports (capacity_reservation_id)",
    "CREATE INDEX ix_lease_end_reports_created_at ON lease_end_reports (created_at)",
)

#: The instant the migration stamps on the consumers it registers: fixed, so one
#: database migrates to the same rows whenever it runs.
_REGISTERED_AT = datetime(1970, 1, 1)


def _stored_instant(value: Any, *, label: str) -> datetime:
    """A time the outboxes stored, as an aware UTC datetime."""
    if isinstance(value, datetime):
        instant = value
    else:
        try:
            instant = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise MigrationDataError(f"{label} is not a time: {value!r}") from exc
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _record_moved_event(
    connection: Connection,
    catalogue: Catalogue,
    kind: Kind[Any],
    draft: EventDraft,
    *,
    event_id: str,
    site_id: str,
    recorded_at: datetime,
) -> int:
    """Write ``draft`` as the event store's next event under ``event_id``,
    recorded at ``recorded_at``, and return its sequence.

    The event is written as the recorder writes one — its sequence from the
    store's counter, its occurrence key, its related references, a whole
    envelope — except that its identity and instant are the moved record's.
    """
    attributes = kind.validate_attributes(draft.attributes)
    details = kind.validate_details(draft.details)
    dedup = kind.dedup_value(draft, details)
    sequence = int(
        connection.execute(
            update(event_schema.sequence_counter)
            .where(event_schema.sequence_counter.c.name == event_schema.SEQUENCE_COUNTER)
            .values(value=event_schema.sequence_counter.c.value + 1)
            .returning(event_schema.sequence_counter.c.value)
        ).scalar_one()
    )
    envelope = Envelope(
        envelope_version=ENVELOPE_VERSION,
        id=event_id,
        kind=kind.name,
        kind_version=kind.version,
        data_schema=catalogue.data_schema(kind),
        source=Source(service=EVENT_SOURCE_SERVICE, instance=site_id),
        sequence=sequence,
        occurred_at=recorded_at,
        severity=kind.severity,
        subject=draft.subject,
        related=draft.related,
        correlation_id=draft.correlation_id,
        causation_id=draft.causation_id,
        attributes=attributes,
        summary=kind.summary(draft, details),
        details=details.model_dump(mode="json"),
        extensions={},
    )
    stored = event_schema.to_stored(recorded_at)
    connection.execute(
        insert(event_schema.events).values(
            sequence=sequence,
            id=event_id,
            kind=kind.name,
            kind_version=kind.version,
            dedup_key=dedup if dedup is not None else event_id,
            severity_rank=kind.severity.rank,
            subject_type=draft.subject.type,
            subject_id=draft.subject.id,
            occurred_at=stored,
            recorded_at=stored,
            envelope=envelope.to_json(),
        )
    )
    for reference in sorted({(item.type, item.id) for item in draft.related}):
        connection.execute(
            insert(event_schema.related).values(
                event_sequence=sequence, type=reference[0], id=reference[1]
            )
        )
    return sequence


def _pending_delivery(
    connection: Connection,
    *,
    consumer: str,
    destination: str,
    sequence: int,
    row: Mapping[str, Any],
    label: str,
) -> None:
    """A pending delivery of ``sequence`` carrying an outbox row's attempts and
    last error, due at once."""
    created_at = event_schema.to_stored(_stored_instant(row["created_at"], label=label))
    last_attempted_at = row["last_attempted_at"]
    connection.execute(
        insert(event_schema.deliveries).values(
            consumer=consumer,
            destination=destination,
            event_sequence=sequence,
            state=PENDING,
            attempts=int(row["attempt_count"] or 0),
            last_error=row["last_error"],
            created_at=created_at,
            last_attempted_at=(
                None
                if last_attempted_at is None
                else event_schema.to_stored(_stored_instant(last_attempted_at, label=label))
            ),
            next_attempt_at=created_at,
        )
    )


def _move_lease_end_reports(connection: Connection, catalogue: Catalogue) -> None:
    """Keep every signed report; make each undelivered one a pending, or
    parked, delivery of a ``site.lease_ended`` event under its own identity,
    which the report names as the event it is kept for. A delivered report has
    no event and is kept by its own retention alone."""
    connection.exec_driver_sql(
        "INSERT INTO lease_end_reports "
        "(event_id, capacity_reservation_id, report, created_at, envelope_id) "
        "SELECT event_id, capacity_reservation_id, report, created_at, "
        "CASE WHEN delivered_at IS NULL THEN event_id END FROM lease_end_report_outbox"
    )
    parked_peers = {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT DISTINCT peer FROM lease_end_report_outbox WHERE parked"
        )
    }
    latest = {
        str(row[0]): _stored_instant(row[1], label=f"lease_end_report_outbox of {row[0]}")
        for row in connection.exec_driver_sql(
            "SELECT peer, max(created_at) FROM lease_end_report_outbox GROUP BY peer"
        )
    }
    rows = connection.execute(text(
        "SELECT o.event_id, o.capacity_reservation_id, o.peer, o.report, o.attempt_count, "
        "o.last_error, o.created_at, o.last_attempted_at, e.transition_key "
        "FROM lease_end_report_outbox o "
        "LEFT JOIN site_lease_ended_events e ON e.event_id = o.event_id "
        "WHERE o.delivered_at IS NULL ORDER BY o.created_at, o.event_id"
    )).mappings().all()
    unmapped = [row["event_id"] for row in rows if row["transition_key"] is None]
    if unmapped:
        raise MigrationDataError(
            f"{len(unmapped)} undelivered lease-end report(s) name no recorded lease end, "
            "so none was moved; restore the database backup taken before the upgrade: "
            + ", ".join(unmapped)
        )
    peers: dict[str, str] = {}
    for row in rows:
        label = f"lease_end_report_outbox {row['event_id']}"
        try:
            payload = json.loads(SignedLeaseEndedReport.model_validate_json(row["report"]).payload)
        except ValueError as exc:
            raise MigrationDataError(f"{label} holds no signed report: {exc}") from exc
        sequence = _record_moved_event(
            connection,
            catalogue,
            SITE_LEASE_ENDED,
            lease_ended_draft(payload, transition_key=str(row["transition_key"])),
            event_id=str(row["event_id"]),
            site_id=str(payload["site_id"]),
            recorded_at=_stored_instant(row["created_at"], label=label),
        )
        destination = peer_destination(str(row["peer"]))
        peers[destination] = str(row["peer"])
        _pending_delivery(
            connection,
            consumer=LEASE_END_REPORT_CONSUMER,
            destination=destination,
            sequence=sequence,
            row=row,
            label=label,
        )
    for peer in parked_peers:
        peers[peer_destination(str(peer))] = str(peer)
    for destination, peer in sorted(peers.items()):
        _migrated_destination(
            connection,
            consumer=LEASE_END_REPORT_CONSUMER,
            name=destination,
            parked=peer in parked_peers,
            at=latest[peer],
        )


def _move_capacity_release_callbacks(connection: Connection, catalogue: Catalogue) -> None:
    """Make each undelivered callback of a released reservation a pending
    delivery of a ``site.capacity_released`` event.

    A callback whose reservation is not released was never delivered, since
    delivery waits for the release, and is dropped with its table. The event
    carries the release as the reservation records it, and the site its lease
    ends name, the one site this database serves; it was forced when the
    reservation was force-released, and follows a release failure when the
    reservation recorded one at any time before — an earlier release failure
    the release need not have followed directly, since the outbox kept no
    reservation's state before its release. The outbox held only the lease
    lifecycle's releases, so each event is marked the lease lifecycle's.
    """
    rows = connection.execute(text(
        "SELECT o.capacity_reservation_id, o.attempt_count, o.last_error, o.created_at, "
        "o.last_attempted_at, r.state, r.released_at, r.failure_reason, "
        "(SELECT e.payload FROM site_lease_ended_events e "
        " WHERE e.capacity_reservation_id = o.capacity_reservation_id "
        " ORDER BY e.event_id LIMIT 1) AS ended, "
        "EXISTS (SELECT 1 FROM site_lease_ended_events f "
        " WHERE f.capacity_reservation_id = o.capacity_reservation_id "
        " AND f.transition_key = 'release_failure') AS failed_before "
        "FROM capacity_release_callback_outbox o "
        "JOIN capacity_reservations r ON r.capacity_reservation_id = o.capacity_reservation_id "
        "WHERE o.delivered_at IS NULL AND r.state IN ('released', 'force_released') "
        "ORDER BY o.created_at, o.capacity_reservation_id"
    )).mappings().all()
    unmapped = [
        row["capacity_reservation_id"]
        for row in rows
        if row["ended"] is None or row["released_at"] is None
    ]
    if unmapped:
        raise MigrationDataError(
            f"{len(unmapped)} undelivered capacity-released callback(s) name a release "
            "recording no time or lease end, so none was moved; restore the database "
            "backup taken before the upgrade: " + ", ".join(unmapped)
        )
    for row in rows:
        label = f"capacity_release_callback_outbox {row['capacity_reservation_id']}"
        site_id = str(_json_mapping(row["ended"], label=label)["site_id"])
        details = CapacityReleasedDetails(
            capacity_reservation_id=str(row["capacity_reservation_id"]),
            site_id=site_id,
            state=str(row["state"]),
            released_at=str(row["released_at"]),
            failure_reason=row["failure_reason"],
        )
        sequence = _record_moved_event(
            connection,
            catalogue,
            SITE_CAPACITY_RELEASED,
            capacity_released_draft(
                details,
                forced=row["state"] == "force_released",
                after_release_failure=bool(row["failed_before"]),
                lease_lifecycle=True,
            ),
            event_id=f"capacity_released:{details.capacity_reservation_id}:{details.released_at}",
            site_id=site_id,
            recorded_at=_stored_instant(row["created_at"], label=label),
        )
        _pending_delivery(
            connection,
            consumer=CAPACITY_RELEASED_CONSUMER,
            destination=CAPACITY_RELEASED_DESTINATION,
            sequence=sequence,
            row=row,
            label=label,
        )
    if rows:
        _migrated_destination(
            connection,
            consumer=CAPACITY_RELEASED_CONSUMER,
            name=CAPACITY_RELEASED_DESTINATION,
            parked=False,
            at=max(
                _stored_instant(row["created_at"], label="capacity_release_callback_outbox")
                for row in rows
            ),
        )


def _migrated_destination(
    connection: Connection, *, consumer: str, name: str, parked: bool, at: datetime
) -> None:
    """A moved destination, added and in its state since ``at``, the latest
    outbox row it carries."""
    stored = event_schema.to_stored(at)
    connection.execute(
        insert(event_schema.destinations).values(
            consumer=consumer,
            name=name,
            state=PARKED if parked else ACTIVE,
            added_at_position=0,
            added_at=stored,
            state_changed_at=stored,
            state_reason="unsupported" if parked else None,
        )
    )


def _move_outboxes_to_the_event_store(connection: Connection) -> None:
    """Carry both storefront outboxes into the event store, then drop them.

    Every signed lease-end report moves to ``lease_end_reports``. Each
    undelivered report becomes a ``site.lease_ended`` event under its own
    event identity, in the order the reports were created, carrying the lease
    end's payload; its delivery to the peer it was signed for is pending with
    the attempts and last error it had, and that peer's destination is parked
    when the peer had parked its reports. Each undelivered capacity-released
    callback of a released reservation becomes a pending delivery of a
    ``site.capacity_released`` event. Delivered rows need no event.

    The storefront peer's consumers are registered past every moved event, so
    they read none twice and every event recorded after the upgrade, on a
    fresh database as on an upgraded one. Any row the move cannot map without
    guessing refuses the migration, which then writes nothing.
    """
    for statement in _LEASE_END_REPORTS_DDL:
        connection.exec_driver_sql(statement)
    catalogue = Catalogue(SITE_KINDS, schema_prefix=EVENT_SCHEMA_PREFIX)
    _move_lease_end_reports(connection, catalogue)
    _move_capacity_release_callbacks(connection, catalogue)
    position = int(
        connection.execute(
            select(event_schema.sequence_counter.c.value).where(
                event_schema.sequence_counter.c.name == event_schema.SEQUENCE_COUNTER
            )
        ).scalar_one()
    )
    now = _REGISTERED_AT
    for consumer in (LEASE_END_REPORT_CONSUMER, CAPACITY_RELEASED_CONSUMER):
        connection.execute(
            insert(event_schema.consumers).values(name=consumer, position=position, created_at=now)
        )
    connection.exec_driver_sql("DROP TABLE lease_end_report_outbox")
    connection.exec_driver_sql("DROP TABLE capacity_release_callback_outbox")


SERVICE_BASELINE: Migration[Connection] = Migration(
    "v0_3_0_baseline_compute_provisioning_service", _create_service_baseline
)
"""This service's own tables as the v0.3.0 release built them."""

SSH_CONNECTIONS_VERSION_2: Migration[Connection] = Migration(
    "20261108_001_ssh_connections_version_2", _rewrite_ssh_connections_to_version_2
)

SSH_CONNECTIONS_VERSION_3: Migration[Connection] = Migration(
    "20261119_001_ssh_connections_version_3", _rewrite_ssh_connections_to_version_3
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

#: The eventing component's schema, one migration per step it supplies, in its
#: order: the service's event store, which the site ledger, the job engine and
#: the delivery worker share with the rest of its database.
EVENTING_MIGRATIONS: tuple[Migration[Connection], ...] = tuple(
    Migration(step.name, step.apply) for step in EVENTING_SCHEMA_STEPS
)

OUTBOXES_TO_EVENT_STORE: Migration[Connection] = Migration(
    "20261126_002_storefront_outboxes_to_event_store", _move_outboxes_to_the_event_store
)

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
    migrations=(
        *SITE_MIGRATIONS,
        SSH_CONNECTIONS_VERSION_2,
        *JOBS_MIGRATIONS,
        SSH_CONNECTIONS_VERSION_3,
        *EVENTING_MIGRATIONS,
        OUTBOXES_TO_EVENT_STORE,
    ),
    floor=Floor("marketplace 0.3.0", FLOOR_IDS),
)
