"""Scheduling applies the pool provider's host requirement.

The ledger here supplies no requirement and no report of hosts taking new
delivery, so it admits a declaration that names no host, or names one that
cannot take delivery. That isolates the scheduler's own recheck: each execution
layer must refuse on its own rather than rely on an earlier one having refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    FulfillmentBase,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    SchedulingCursor,
    SettlementRecord,
    SettlementRepository,
    SettlementRequirement,
    SettlementResource,
    SqlAlchemySchedulingTransaction,
    SqlAlchemySchedulingUnitOfWork,
)
from market_resource_pools import ResourcePoolService
from market_resource_pools_contracts import PoolCreate
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.db import CapacityReservationDebit
from market_site.ledger import CapacityLedgerService


class _Handler:
    provider = "ansible"

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, db, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        return self.read_config(db, pool_id)

    def replace_config(self, db, pool_id, config):
        pass


@pytest.fixture
def services():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    FulfillmentBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="pool-a",
        provider="ansible",
        enabled=True,
        policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
        provider_config={},
    ))
    ledger = CapacityLedgerService(
        factory, unit_claim_keys=("units", "gpu_count"), mirror_dimension="gpu_count"
    )
    scheduler = PhysicalSettlementScheduler(
        pools,
        ledger,
        session_factory=factory,
        default_resource_kind="compute.gpu",
        host_requirement={"ansible": True},
    )
    return ledger, scheduler, factory


def _declare(ledger, resource_id, *, host_id=None, units=4):
    ledger.register_resource(
        resource_id=resource_id,
        resource_type="compute.gpu",
        total_units=units,
        pool_id="pool-a",
        host_id=host_id,
    )


def _reserve(ledger, agreement):
    reserved = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1},
        deal_ref={"agreement_id": agreement, "market": "vms"},
    )
    assert reserved is not None
    return reserved


def _request(capacity_reservation_id, **kwargs):
    return PhysicalSettlementRequest(
        capacity_reservation_id=capacity_reservation_id, market="vms", **kwargs
    )


def test_automatic_selection_never_places_a_declaration_naming_no_host(services):
    ledger, scheduler, _ = services
    # Sorted first, so round-robin would reach it first if it were a candidate.
    _declare(ledger, "a-no-host")
    _declare(ledger, "b-hosted", host_id="kvm1")

    placed = {
        scheduler.schedule_resource(
            _request(_reserve(ledger, f"agreement-{n}")["capacity_reservation_id"])
        ).settlement_resource_id
        for n in range(3)
    }

    assert placed == {"b-hosted"}


def test_with_no_other_candidate_nothing_is_placed_rebound_or_advanced(services):
    ledger, scheduler, factory = services
    _declare(ledger, "a-no-host")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.schedule_resource(_request(capacity_reservation_id))

    with factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id) is None
        assert db.get(SchedulingCursor, "compute.gpu") is None
        assert db.get(CapacityReservationDebit, capacity_reservation_id) is not None
    # The admitted hold is untouched: still one unit held on the declaration.
    (row,) = ledger.snapshot()
    assert (row["resource_id"], row["available_units"]) == ("a-no-host", 3)


def test_an_explicit_constraint_naming_no_host_is_refused(services):
    ledger, scheduler, factory = services
    _declare(ledger, "a-no-host")
    _declare(ledger, "b-hosted", host_id="kvm1")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    with pytest.raises(NoEligibleSettlementResourceError, match="a-no-host"):
        scheduler.schedule_resource(
            _request(capacity_reservation_id, resource_id="a-no-host")
        )

    with factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id) is None
        assert db.get(SchedulingCursor, "compute.gpu") is None


def test_an_existing_assignment_keeps_the_host_it_was_placed_on(services):
    ledger, scheduler, _ = services
    _declare(ledger, "b-hosted", host_id="kvm1")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]
    first = scheduler.schedule_resource(_request(capacity_reservation_id))

    # The declaration is re-registered without its host after placement.
    _declare(ledger, "b-hosted")
    again = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert again.settlement_resource_id == first.settlement_resource_id == "b-hosted"
    assert again.host_id == "kvm1"


def test_a_provider_needing_no_host_places_and_returns_a_hostless_assignment(services):
    """Where the pool's provider needs no host, a declaration naming none is
    placed, its assignment carries no host, and a repeat returns it unchanged."""
    ledger, _, factory = services
    scheduler = PhysicalSettlementScheduler(
        ResourcePoolService(factory, {"ansible": _Handler()}),
        ledger,
        session_factory=factory,
        default_resource_kind="compute.gpu",
        host_requirement={"ansible": False},
    )
    _declare(ledger, "a-no-host")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    placed = scheduler.schedule_resource(_request(capacity_reservation_id))
    again = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert placed.settlement_resource_id == "a-no-host"
    assert placed.host_id is None
    assert again == placed


def test_an_assignment_recorded_with_no_host_is_refused_rather_than_returned(services):
    """An assignment placed before placement refused declarations naming no
    host. It is seeded directly, as that earlier scheduler wrote it, because
    the scheduler under test can no longer create one."""
    ledger, scheduler, factory = services
    _declare(ledger, "a-no-host")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]
    with factory() as db, db.begin():
        SettlementRepository().schedule(
            db,
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            scheduling_requirements=SettlementRequirement(
                offering_mode="vm",
                resource_kind="compute.gpu",
                dimensions={"gpu_count": 1},
                attributes={},
            ),
            resource=SettlementResource(
                settlement_resource_id="a-no-host",
                pool_id="pool-a",
                offering_mode="vm",
                resource_kind="compute.gpu",
                provider="ansible",
                attributes={},
                host_id=None,
            ),
        )

    with pytest.raises(NoEligibleSettlementResourceError, match="names no host"):
        scheduler.schedule_resource(_request(capacity_reservation_id))

    with factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id).state == "assigned"


class FakeDeliverableHosts:
    """A report over a fixed, mutable set, recording the session it was read in."""

    def __init__(self, host_ids=()) -> None:
        self.host_ids = set(host_ids)
        self.sessions: list[Session] = []

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        self.sessions.append(db)
        return frozenset(self.host_ids)


class RecordingTransaction(SqlAlchemySchedulingTransaction):
    """Records each scheduling transaction's session, to compare with the
    sessions the report was read in."""

    sessions: list[Session] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).sessions.append(self.db)


@pytest.fixture
def reported(services):
    """A scheduler whose unit of work reads a report of hosts taking delivery."""
    ledger, _, factory = services
    hosts = FakeDeliverableHosts({"kvm1", "kvm2"})
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    RecordingTransaction.sessions = []
    scheduler = PhysicalSettlementScheduler(
        pools,
        ledger,
        session_factory=factory,
        default_resource_kind="compute.gpu",
        host_requirement={"ansible": True},
        unit_of_work=SqlAlchemySchedulingUnitOfWork(
            factory, pools, ledger,
            transaction_type=RecordingTransaction,
            deliverable_hosts=hosts,
        ),
    )
    return ledger, scheduler, factory, hosts


def test_automatic_selection_never_places_a_declaration_whose_host_is_disabled(reported):
    ledger, scheduler, _, hosts = reported
    # Sorted first, so round-robin would reach it first if it were a candidate.
    _declare(ledger, "a-disabled", host_id="kvm-off")
    _declare(ledger, "b-hosted", host_id="kvm1")

    placed = {
        scheduler.schedule_resource(
            _request(_reserve(ledger, f"agreement-{n}")["capacity_reservation_id"])
        ).settlement_resource_id
        for n in range(3)
    }

    assert placed == {"b-hosted"}
    # One read per scheduling transaction, in that transaction's own session.
    assert len(hosts.sessions) == 3
    assert all(
        read is opened
        for read, opened in zip(hosts.sessions, RecordingTransaction.sessions, strict=True)
    )


@pytest.mark.parametrize(
    "host_id", ["kvm-off", "never-registered"], ids=["disabled", "unregistered"]
)
def test_a_constraint_naming_a_host_not_taking_delivery_is_refused(reported, host_id):
    ledger, scheduler, factory, _ = reported
    _declare(ledger, "a-hosted", host_id="kvm1")
    _declare(ledger, "b-undeliverable", host_id=host_id)
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    with pytest.raises(NoEligibleSettlementResourceError, match="b-undeliverable"):
        scheduler.schedule_resource(
            _request(capacity_reservation_id, resource_id="b-undeliverable")
        )

    with factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id) is None
        assert db.get(SchedulingCursor, "compute.gpu") is None
    # Not rebound: the hold stays on the declaration admission chose.
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "a-hosted"


def test_a_hold_whose_own_backing_lost_its_host_is_placed_elsewhere_and_rebound(reported):
    ledger, scheduler, _, hosts = reported
    _declare(ledger, "a-first", host_id="kvm1")
    _declare(ledger, "b-second", host_id="kvm2")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "a-first"

    hosts.host_ids.discard("kvm1")
    placed = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert (placed.settlement_resource_id, placed.host_id) == ("b-second", "kvm2")
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "b-second"
    available = {row["resource_id"]: row["available_units"] for row in ledger.list_resources()}
    assert available == {"a-first": 4, "b-second": 3}


def test_a_hold_whose_own_backing_lost_its_host_with_no_other_candidate_is_refused(reported):
    ledger, scheduler, factory, hosts = reported
    _declare(ledger, "a-only", host_id="kvm1")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    hosts.host_ids.discard("kvm1")
    with pytest.raises(NoEligibleSettlementResourceError):
        scheduler.schedule_resource(_request(capacity_reservation_id))

    with factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id) is None
        assert db.get(SchedulingCursor, "compute.gpu") is None
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "a-only"


def test_an_existing_assignment_whose_host_was_disabled_is_returned_unchanged(reported):
    ledger, scheduler, _, hosts = reported
    _declare(ledger, "a-hosted", host_id="kvm1")
    _declare(ledger, "b-other", host_id="kvm2")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]
    first = scheduler.schedule_resource(_request(capacity_reservation_id))
    assert first.settlement_resource_id == "a-hosted"

    hosts.host_ids.discard("kvm1")
    again = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert again == first
    assert again.host_id == "kvm1"


def test_with_no_requirement_the_report_is_not_read(services):
    ledger, _, factory = services
    hosts = FakeDeliverableHosts()
    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    scheduler = PhysicalSettlementScheduler(
        pools,
        ledger,
        session_factory=factory,
        default_resource_kind="compute.gpu",
        unit_of_work=SqlAlchemySchedulingUnitOfWork(
            factory, pools, ledger, deliverable_hosts=hosts
        ),
    )
    _declare(ledger, "a-named", host_id="kvm-off")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    placed = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert placed.settlement_resource_id == "a-named"
    assert hosts.sessions == []


def test_with_no_report_any_named_host_is_placed(services):
    """A unit of work supplying no report has nothing to judge a host by."""
    ledger, scheduler, _ = services
    _declare(ledger, "a-named", host_id="never-registered")
    capacity_reservation_id = _reserve(ledger, "agreement-1")["capacity_reservation_id"]

    placed = scheduler.schedule_resource(_request(capacity_reservation_id))

    assert (placed.settlement_resource_id, placed.host_id) == ("a-named", "never-registered")
