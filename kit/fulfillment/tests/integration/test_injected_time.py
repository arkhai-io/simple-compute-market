"""Library integration test: the aggregate's read times come from the process source.

Recovery claims rows oldest first, leases each claim to an instant, and reports
the oldest row's age; a fulfillment's resources are listed in creation order.
Under an injected source, every one of those columns holds the source's instant,
never the database's clock, on the schema the aggregate's migration builds.
"""

from __future__ import annotations

from datetime import datetime, timezone

from market_core import envelope
from sqlalchemy.orm import Session, sessionmaker

from market_fulfillment.db import ProvisionedResource, SettlementRecord, SettlementRecordState
from market_fulfillment.settlement_repository import SettlementRepository
from market_fulfillment.settlement_types import SettlementRequirement, SettlementResource

PENDING = SettlementRecordState.dispatch_pending.value


def _utc(value: datetime) -> datetime:
    # SQLite hands a stored DateTime back without its offset.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _at(instant: int) -> datetime:
    return datetime.fromtimestamp(instant, timezone.utc)


def _write_record(sessions: sessionmaker[Session]) -> None:
    with sessions() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id="reservation-1",
                fulfillment_id="fulfillment-1",
                market="vms",
                scheduling_requirements={"resource_kind": "vm"},
                provider="ansible",
                state=PENDING,
            )
        )
        db.add(
            ProvisionedResource(
                provisioned_resource_id="provisioned-1",
                capacity_reservation_id="reservation-1",
                fulfillment_id="fulfillment-1",
            )
        )
        db.commit()


def _accept(sessions: sessionmaker[Session], repository: SettlementRepository, reservation: str) -> None:
    with sessions() as db:
        repository.schedule(
            db,
            capacity_reservation_id=reservation,
            market="vms",
            scheduling_requirements=SettlementRequirement(
                offering_mode="vm", resource_kind="compute.gpu", dimensions={"gpu_count": 1}
            ),
            resource=SettlementResource(
                settlement_resource_id="host-a",
                pool_id="pool-1",
                offering_mode="vm",
                resource_kind="compute.gpu",
                provider="ansible",
            ),
        )
        repository.accept_fulfillment(
            db,
            capacity_reservation_id=reservation,
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()


def test_every_read_column_holds_the_injected_instant(source, sessions) -> None:
    start = source.now()
    _write_record(sessions)
    repository = SettlementRepository()

    with sessions() as db:
        record = repository.get(db, "reservation-1")
        assert _utc(record.created_at) == _at(start)
        (resource,) = repository.list_provisioned_resources(db, "reservation-1")
        assert _utc(resource.created_at) == _at(start)

    with sessions() as db:
        (claimed,) = repository.claim_pending(
            db, states=[PENDING], limit=10, lease_seconds=30, worker_id="worker-1"
        )
    assert _utc(claimed.claim_expires_at) == _at(start + 30)

    with sessions() as db:
        assert repository.record_progress(
            db, "reservation-1", worker_id="worker-1", lease_seconds=60
        )
        db.commit()
    with sessions() as db:
        assert _utc(repository.get(db, "reservation-1").claim_expires_at) == _at(start + 60)


def test_recovery_diagnostics_count_claims_and_age_rows_against_the_source(
    source, sessions
) -> None:
    start = source.now()
    repository = SettlementRepository()
    _accept(sessions, repository, "cr-1")
    _accept(sessions, repository, "cr-2")
    with sessions() as db:
        # cr-1: claimed and still within its lease.
        repository.claim_pending(
            db, states=[PENDING], limit=1, lease_seconds=3600, worker_id="worker-a"
        )
    with sessions() as db:
        # cr-2: claimed an hour ago for a second, so its lease has lapsed.
        repository.claim_pending(
            db,
            states=[PENDING],
            limit=1,
            lease_seconds=1,
            worker_id="worker-b",
            now=_at(start - 3600),
        )

    with sessions() as db:
        held = repository.recovery_diagnostics(db)
    state = held.per_state[PENDING]
    assert (state.total, state.actively_claimed, state.expired_claims) == (2, 1, 1)
    assert state.max_attempt_count == 1
    assert state.oldest_row_age_seconds == 0
    empty = held.per_state[SettlementRecordState.tearing_down.value]
    assert (empty.total, empty.oldest_row_age_seconds, empty.max_attempt_count) == (0, None, 0)
    assert (held.failed_count, held.teardown_failed_count) == (0, 0)

    source.set(start + 3600)
    with sessions() as db:
        lapsed = repository.recovery_diagnostics(db).per_state[PENDING]
    assert (lapsed.actively_claimed, lapsed.expired_claims) == (0, 2)
    assert lapsed.oldest_row_age_seconds == 3600
