"""Scheduling applies the pool provider's host requirement.

The ledger here supplies no requirement, so it admits a declaration that names
no host. That isolates the scheduler's own recheck: each execution layer must
refuse on its own rather than rely on an earlier one having refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    FulfillmentBase,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    SchedulingCursor,
    SettlementRecord,
)
from market_resource_pools import PoolCreate, ResourcePoolService
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

    def delete_config(self, db, pool_id):
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
        policy_tags={"deliverable_modes": ["vm"]},
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
