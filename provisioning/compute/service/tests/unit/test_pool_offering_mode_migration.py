from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_executor_identities_and_pool_modes,
)
from compute_provisioning_service.db.models import AnsibleJob, AnsiblePoolConfig
from market_fulfillment.db import SettlementRecord
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from market_site.db import (
    CapacityBucket,
    CapacityReservation,
    CapacityReservationDebit,
)


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path="/playbooks/vm-operations.yaml",
        default_inventory_group="kvm_hosts",
    )
    return engine


def test_pool_mode_derivation_is_exact_includes_default_and_is_idempotent():
    engine = _engine()
    with Session(engine) as db, db.begin():
        db.add(
            ResourcePool(
                id="unconfigured",
                label="Unconfigured",
                provider="ansible",
                enabled=True,
                policy_tags={"deliverable_modes": ["bare_metal", "vm"]},
            )
        )
        db.add(
            ResourcePool(
                id="vm-pool",
                label="VM Pool",
                provider="ansible",
                enabled=True,
                policy_tags={"region": "test"},
            )
        )
        db.add(
            AnsiblePoolConfig(
                pool_id="vm-pool",
                playbook_path="/playbooks/vm-operations.yaml",
                requirement_delegate="vm_management_v1",
                inventory_group="kvm_hosts",
                extra_vars={},
            )
        )

    _migrate_executor_identities_and_pool_modes(engine)
    with Session(engine) as db:
        default = db.get(ResourcePool, DEFAULT_POOL_ID)
        vm_pool = db.get(ResourcePool, "vm-pool")
        unconfigured = db.get(ResourcePool, "unconfigured")
        first = {
            pool.id: dict(pool.policy_tags)
            for pool in (default, vm_pool, unconfigured)
        }
        assert default.policy_tags["deliverable_modes"] == ["vm"]
        assert vm_pool.policy_tags == {
            "deliverable_modes": ["vm"],
            "region": "test",
        }
        assert unconfigured.policy_tags["deliverable_modes"] == []

    _migrate_executor_identities_and_pool_modes(engine)
    with Session(engine) as db:
        second = {
            pool.id: dict(pool.policy_tags)
            for pool in db.query(ResourcePool).order_by(ResourcePool.id)
        }
    assert second == first


def test_legacy_executor_identity_backfills_proof_and_quarantines_unknown_rows():
    engine = _engine()
    with Session(engine) as db, db.begin():
        proved_bucket = CapacityBucket(
            capacity_bucket_id="bucket-proved",
            backing_resource_id="resource-proved",
            pool_id=DEFAULT_POOL_ID,
            resource_type="compute.gpu",
            total_units=1,
            capacity={"gpu_count": 1},
            attributes={"vm_host": "kvm1"},
            enabled=True,
        )
        unknown_bucket = CapacityBucket(
            capacity_bucket_id="bucket-unknown",
            backing_resource_id="resource-unknown",
            pool_id=DEFAULT_POOL_ID,
            resource_type="opaque",
            total_units=1,
            capacity={"units": 1},
            attributes={},
            enabled=True,
        )
        db.add_all((proved_bucket, unknown_bucket))
        db.add_all(
            (
                CapacityReservation(
                    capacity_reservation_id="reservation-proved",
                    units=1,
                    dimensions={"gpu_count": 1},
                    state="reserved",
                    deal_ref={},
                ),
                CapacityReservation(
                    capacity_reservation_id="reservation-unknown",
                    units=1,
                    dimensions={"units": 1},
                    state="leased",
                    deal_ref={},
                ),
            )
        )
        db.add_all(
            (
                CapacityReservationDebit(
                    capacity_reservation_id="reservation-proved",
                    capacity_bucket_id="bucket-proved",
                    dimensions={"gpu_count": 1},
                ),
                CapacityReservationDebit(
                    capacity_reservation_id="reservation-unknown",
                    capacity_bucket_id="bucket-unknown",
                    dimensions={"units": 1},
                ),
            )
        )
        db.add(
            SettlementRecord(
                capacity_reservation_id="reservation-proved",
                market="vms",
                scheduling_requirements={
                    "resource_kind": "compute.gpu",
                    "dimensions": {"gpu_count": "1"},
                    "attributes": {},
                },
                settlement_resource_id="resource-proved",
                pool_id=DEFAULT_POOL_ID,
                provider="ansible",
                resource_attributes={"vm_host": "kvm1"},
                provider_metadata={},
                state="assigned",
            )
        )
        db.add_all(
            (
                AnsibleJob(
                    id="job-proved",
                    status="queued",
                    params={"vm_host": "kvm1", "vm_action": "create"},
                    capacity_reservation_id="reservation-proved",
                ),
                AnsibleJob(
                    id="job-unknown",
                    status="running",
                    params={"vm_action": "unknown"},
                ),
            )
        )

    _migrate_executor_identities_and_pool_modes(engine)

    with Session(engine) as db:
        proved = db.get(CapacityReservation, "reservation-proved")
        unknown = db.get(CapacityReservation, "reservation-unknown")
        settlement = db.get(SettlementRecord, "reservation-proved")
        proved_job = db.get(AnsibleJob, "job-proved")
        unknown_job = db.get(AnsibleJob, "job-unknown")

        assert proved.executor_kind == "vm"
        assert settlement.scheduling_requirements["executor_kind"] == "vm"
        assert proved_job.executor_kind == "vm"
        assert proved_job.params["executor_kind"] == "vm"

        assert unknown.executor_kind is None
        assert unknown.state == "unmanaged"
        assert unknown.failure_reason == "legacy_executor_identity_quarantined"
        assert unknown_job.executor_kind is None
        assert unknown_job.status == "failed"
        assert "quarantined" in unknown_job.error

    # The migration is a deterministic no-op over already-derived/backfilled rows.
    _migrate_executor_identities_and_pool_modes(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM capacity_reservations "
                "WHERE executor_kind='vm'"
            )
        ).scalar_one() == 1
