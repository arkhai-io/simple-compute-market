"""The storefront's shape feasibility agrees with the site ledger's own step.

Publication judges a listing shape by building the claim its reservation would
send and matching it with the site's exported predicate over a projected member
or capacity bucket. These tests hold that judgement to the resource-requirement
step inside the ledger's admission, run over a real ledger, for the same
declarations and claims. Admission's other checks (delivery mode, host
requirement, lease-window holds, physical-host conflicts) are deliberately not
part of feasibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools.db import Base as PoolBase, ResourcePool
from market_site.db import Base as SiteBase, CapacityBucket
from market_site.ledger import (
    CapacityLedgerService,
    _requested_dimensions,
    _resource_capacity,
    _resource_feasibility_view,
    _split_claim_requirement,
    resource_satisfies_requirement,
)
from market_site.projections import capacity_bucket_projection, resource_pool_projection

from market_storefront.services.capacity_client import (
    VM_MIRROR_DIMENSION,
    VM_UNIT_CLAIM_KEYS,
)
from market_storefront.services.shape_feasibility import (
    SiteShapeFeasibility,
    member_snapshot_row,
)

_JUDGE = SiteShapeFeasibility()
_TAGS = {"deliverable_modes": ["vm"], "advertisable_modes": ["vm"], "capacity_backing": "backed"}


@pytest.fixture
def ledger() -> CapacityLedgerService:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SiteBase.metadata.create_all(bind=engine)
    PoolBase.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db, db.begin():
        for pool_id in ("gpu-a", "hint-region", "spec"):
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", enabled=True,
                                policy_tags=dict(_TAGS)))
    service = CapacityLedgerService(
        sessions, unit_claim_keys=VM_UNIT_CLAIM_KEYS, mirror_dimension=VM_MIRROR_DIMENSION
    )
    service.register_resource(
        resource_id="a-1", pool_id="gpu-a", host_id="h1",
        attributes={"gpu_model": "H100", "region": "us-east"},
        capacity={"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 2000})
    service.register_resource(
        resource_id="b-1", pool_id="hint-region", host_id="h2",
        attributes={"gpu_model": "H100"}, capacity={"gpu_count": 4, "ram_gb": 128})
    service.register_resource(
        resource_id="spec-1", pool_id="spec", host_id="h3",
        attributes={"gpu_model": "A100", "region": "eu"},
        capacity={"gpu_count": 2, "ram_gb": 64})
    # Hold part of a-1, so declared and available capacity differ.
    assert service.reserve(
        claim={"offering_mode": "vm", "resource_type": "compute.gpu", "resource_id": "a-1",
               "dimensions": {"gpu_count": 6, "ram_gb": 400}},
        ttl_seconds=3600,
    )
    return service


def _ledger_step(ledger, claim, resource_id, *, available: bool) -> bool:
    """The requirement step inside the ledger's admission, for one resource."""
    kind, attributes = _split_claim_requirement(claim, unit_claim_keys=VM_UNIT_CLAIM_KEYS)
    requested = _requested_dimensions(
        claim, unit_claim_keys=VM_UNIT_CLAIM_KEYS, mirror_dimension=VM_MIRROR_DIMENSION
    )
    now = datetime.now(timezone.utc)
    with ledger._session_factory() as db:
        bucket = db.query(CapacityBucket).filter_by(backing_resource_id=resource_id).one()
        capacity = _resource_capacity(bucket, VM_MIRROR_DIMENSION)
        if available:
            held = ledger._held_dimensions(db, resource_id, now, now + timedelta(microseconds=1))
            capacity = {key: value - held.get(key, 0) for key, value in capacity.items()}
        return resource_satisfies_requirement(
            resource=_resource_feasibility_view(bucket, capacity, VM_MIRROR_DIMENSION),
            required_resource_kind=kind,
            required_dimensions=requested,
            required_attributes=attributes,
        )


def _member(ledger, resource_id):
    for pool in resource_pool_projection(ledger.list_resources()):
        for member in pool["resources"]:
            if member["physical_resource_id"] == resource_id:
                return pool["resource_pool_id"], member
    raise AssertionError(resource_id)


def _listing(pool_id, *, model="H100", region="us-east", resource_id=None, **quantities):
    listing = {"pool_id": pool_id, "gpu_model": model, "region": region,
               "offering_mode": "vm", "capacity_backing": "backed", **quantities}
    if resource_id:
        listing["resource_id"] = resource_id
    return listing


_CASES = [
    ("declared attributes, one dimension", "a-1", _listing("gpu-a", gpu_count=1)),
    ("declared attributes, every dimension", "a-1",
     _listing("gpu-a", gpu_count=1, vcpu_count=8, ram_gb=32, disk_gb=100)),
    ("memory beyond availability", "a-1", _listing("gpu-a", gpu_count=1, ram_gb=200)),
    ("GPUs beyond availability", "a-1", _listing("gpu-a", gpu_count=8)),
    ("a model the member lacks", "a-1", _listing("gpu-a", model="A100", gpu_count=1)),
    ("a region only in the pool hint", "b-1",
     _listing("hint-region", region="us-west", gpu_count=1)),
    ("a specific resource, which drops pool_id", "spec-1",
     _listing("spec", model="A100", region="eu", resource_id="spec-1", gpu_count=1, ram_gb=32)),
    ("a specific resource of another model", "spec-1",
     _listing("spec", model="H100", region="eu", resource_id="spec-1", gpu_count=1)),
]


@pytest.mark.parametrize(("label", "resource_id", "listing"), _CASES, ids=[c[0] for c in _CASES])
@pytest.mark.parametrize("use_available", [False, True], ids=["declared", "available"])
def test_a_projected_member_is_judged_as_the_ledger_judges_it(
    ledger, label, resource_id, listing, use_available
):
    pool_id, member = _member(ledger, resource_id)
    claim = _JUDGE.claim(listing)

    assert _JUDGE.member_feasible(
        listing, pool_id=pool_id, member=member, use_available=use_available
    ) == _ledger_step(ledger, claim, resource_id, available=use_available)


@pytest.mark.parametrize(("label", "resource_id", "listing"), _CASES[:6], ids=[c[0] for c in _CASES[:6]])
def test_a_capacity_bucket_stands_in_for_its_fungible_members(ledger, label, resource_id, listing):
    buckets = [
        bucket for bucket in capacity_bucket_projection(ledger.list_resources())
        if bucket["resource_pool_id"] == listing["pool_id"]
    ]
    claim = _JUDGE.claim(listing)

    assert any(_JUDGE.bucket_feasible(listing, bucket=b) for b in buckets) == _ledger_step(
        ledger, claim, resource_id, available=True
    )


def test_the_hint_only_region_is_refused_by_both(ledger):
    pool_id, member = _member(ledger, "b-1")
    listing = _listing("hint-region", region="us-west", gpu_count=1)

    assert not _JUDGE.member_feasible(listing, pool_id=pool_id, member=member, use_available=False)


def test_the_adapter_invents_no_resource_type():
    # A member that states no kind is not given one; reconciliation holds it
    # before it would reach this check.
    row = member_snapshot_row(
        "pool", {"physical_resource_id": "m", "capacity": {"gpu_count": 1}}, use_available=False
    )
    assert row["resource_type"] is None
    assert not _JUDGE.member_feasible(
        _listing("pool", gpu_count=1), pool_id="pool",
        member={"physical_resource_id": "m", "capacity": {"gpu_count": 1},
                "attributes": {"gpu_model": "H100", "region": "us-east"}},
        use_available=False,
    )
