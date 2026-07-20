from __future__ import annotations

from datetime import datetime, timezone

import pytest
from arkhai_bare_metal import BareMetalLeaseCreate
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import (
    ALLOCATION_MODE_EXCLUSIVE,
    CapacityLedgerService,
)
from compute_provisioning_service.db.models import Base
from bare_metal_provisioning_adapter.services.bare_metal_lease_service import (
    BareMetalLeaseService,
)
from compute_provisioning.lease_lifecycle import LeaseNotFoundError
from market_site.authority import LedgerSiteAuthority


@pytest.fixture
def ledger() -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # resource_pools must exist before Base's ansible_pool_configs FK resolves.
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    svc = CapacityLedgerService(session_factory)
    svc.register_resource(
        resource_id="bare-metal-1",
        total_units=1,
        attributes={
            "machine_id": "bm-node-1",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )
    return svc


def test_register_bare_metal_lease_attaches_executor_metadata(
    ledger: CapacityLedgerService,
):
    reserved = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    )
    assert reserved is not None
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    svc = BareMetalLeaseService(LedgerSiteAuthority(ledger))

    lease = svc.register_lease(
        BareMetalLeaseCreate(
            allocation_id=reserved["allocation_id"],
            escrow_uid="0xbm",
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            access_ref={"ssh_user": "tenant-a"},
            lease_start_utc=datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc),
            lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
            create_job_id="grant-1",
        ),
    )

    assert lease["state"] == "leased"
    assert lease["executor_kind"] == "bare_metal"
    assert lease["executor_target"] == "bm-node-1"
    assert lease["executor_ref"] == {
        "physical_host_id": "host-physical-1",
        "ssh_user": "tenant-a",
    }
    assert lease["vm_host"] is None
    assert lease["vm_target"] is None
    assert lease["create_job_id"] == "grant-1"


def test_register_bare_metal_lease_by_escrow_when_allocation_id_omitted(
    ledger: CapacityLedgerService,
):
    reserved = ledger.reserve(
        claim={"allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        deal_ref={"escrow_uid": "0xbm"},
    )
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
    )
    svc = BareMetalLeaseService(LedgerSiteAuthority(ledger))

    lease = svc.register_lease(
        BareMetalLeaseCreate(
            allocation_id=None,
            escrow_uid="0xbm",
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
        ),
    )

    assert lease["allocation_id"] == reserved["allocation_id"]
    assert lease["executor_kind"] == "bare_metal"
    assert lease["executor_target"] == "bm-node-1"


def test_register_bare_metal_lease_missing_allocation_raises(
    ledger: CapacityLedgerService,
):
    svc = BareMetalLeaseService(LedgerSiteAuthority(ledger))

    with pytest.raises(LeaseNotFoundError):
        svc.register_lease(
            BareMetalLeaseCreate(
                allocation_id="missing",
                escrow_uid="0xmissing",
                machine_id="bm-node-1",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
            ),
        )
