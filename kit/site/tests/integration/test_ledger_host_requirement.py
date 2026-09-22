"""Admission applies the pool provider's host requirement.

The suite's default pool names provider ``"test"``. Each case supplies the
requirement the composition would, and declares capacity with or without a
host, to prove that a declaration naming no host is simply not a candidate in a
pool whose provider needs one.
"""

from __future__ import annotations

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools.db import Base as ResourcePoolBase
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from market_site.db import Base
from market_site.ledger import CapacityConflictError, CapacityLedgerService


def _make_ledger(*, host_requirement):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="test",
                enabled=True,
                policy_tags={"deliverable_modes": ["vm"]},
            )
        )
    return CapacityLedgerService(
        session_factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        host_requirement=host_requirement,
    )

VM_CLAIM = {"offering_mode": "vm", "gpu_count": 1}


def _declare(ledger, resource_id: str, *, host_id: str | None = None, units: int = 4):
    ledger.register_resource(
        resource_id=resource_id,
        total_units=units,
        pool_id="default",
        host_id=host_id,
    )


def _no_hold_exists(ledger) -> bool:
    return all(
        row["available_units"] == row["value"] for row in ledger.snapshot()
    )


def test_a_declaration_naming_no_host_is_not_admitted_where_the_provider_needs_one():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "no-host")

    assert ledger.probe(claim=VM_CLAIM) is None
    assert ledger.reserve(claim=VM_CLAIM, deal_ref={}) is None
    assert _no_hold_exists(ledger)


def test_the_claim_falls_through_to_a_declaration_naming_a_host():
    ledger = _make_ledger(host_requirement={"test": True})
    # Registered first, so it would be the first candidate if it were one.
    _declare(ledger, "no-host")
    _declare(ledger, "hosted", host_id="kvm1")

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved is not None
    assert reserved["resource_id"] == "hosted"


def test_a_provider_the_requirement_does_not_name_needs_a_host():
    ledger = _make_ledger(host_requirement={"some-other-provider": False})
    _declare(ledger, "no-host")

    assert ledger.probe(claim=VM_CLAIM) is None


@pytest.mark.parametrize("host_requirement", [None, {"test": False}])
def test_a_declaration_naming_no_host_is_admitted_where_no_host_is_needed(
    host_requirement,
):
    ledger = _make_ledger(host_requirement=host_requirement)
    _declare(ledger, "no-host")

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved is not None
    assert reserved["resource_id"] == "no-host"


def test_an_unregistered_named_host_is_not_admissions_concern():
    """The ledger knows no host registry; dispatch refuses an unregistered host."""
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "named", host_id="not-registered-anywhere")

    assert ledger.reserve(claim=VM_CLAIM, deal_ref={}) is not None


def test_resize_applies_the_same_rule():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "hosted", host_id="kvm1", units=2)
    _declare(ledger, "no-host", units=8)
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    resized = ledger.resize_reservation(
        old_capacity_reservation_id=reserved["capacity_reservation_id"],
        new_claim={"offering_mode": "vm", "gpu_count": 4},
    )

    # Only the declaration naming no host could hold four, so nothing changes.
    assert resized is None
    snapshot = {row["resource_id"]: row for row in ledger.snapshot()}
    assert snapshot["hosted"]["available_units"] == 1
    assert snapshot["no-host"]["available_units"] == 8


def test_assignment_refuses_a_destination_naming_no_host():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "hosted", host_id="kvm1")
    _declare(ledger, "no-host")
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    with pytest.raises(CapacityConflictError, match="names no host"):
        ledger.assign_settlement_resource(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="no-host",
        )
