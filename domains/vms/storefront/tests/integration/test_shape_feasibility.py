"""The storefront's shape feasibility agrees with the site ledger's admission.

Publication judges a listing shape by building the claim its reservation would
send and matching it with the site's exported predicate, over a projected member
or a capacity bucket. These tests hold that judgement to the ledger's public
admission dry run, `CapacityLedgerService.probe`, run over a real ledger for the
same declarations and claims.

Admission checks more than resource feasibility: delivery mode, the provider's
host requirement, lease-window holds, and physical-host conflicts. The fixture
satisfies each of those for every pool, so the only thing that can differ is the
resource requirement, which is what feasibility judges. Declared capacity is
compared against a ledger holding nothing, and availability against one holding
part of a member.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools.db import Base as PoolBase, ResourcePool
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
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


def _ledger(*, held: bool) -> CapacityLedgerService:
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
    ledger = CapacityLedgerService(
        sessions, unit_claim_keys=VM_UNIT_CLAIM_KEYS, mirror_dimension=VM_MIRROR_DIMENSION
    )
    ledger.register_resource(
        resource_id="a-1", pool_id="gpu-a", host_id="h1",
        attributes={"gpu_model": "H100", "region": "us-east"},
        capacity={"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 2000})
    ledger.register_resource(
        resource_id="b-1", pool_id="hint-region", host_id="h2",
        attributes={"gpu_model": "H100"}, capacity={"gpu_count": 4, "ram_gb": 128})
    ledger.register_resource(
        resource_id="spec-1", pool_id="spec", host_id="h3",
        attributes={"gpu_model": "A100", "region": "eu"},
        capacity={"gpu_count": 2, "ram_gb": 64})
    if held:
        assert ledger.reserve(
            claim={"offering_mode": "vm", "resource_type": "compute.gpu", "resource_id": "a-1",
                   "dimensions": {"gpu_count": 6, "ram_gb": 400}},
            ttl_seconds=3600,
        )
    return ledger


@pytest.fixture(scope="module")
def unheld() -> CapacityLedgerService:
    return _ledger(held=False)


@pytest.fixture(scope="module")
def held() -> CapacityLedgerService:
    return _ledger(held=True)


def _member(ledger, resource_id):
    for pool in resource_pool_projection(ledger.list_resources()):
        for member in pool["resources"]:
            if member["physical_resource_id"] == resource_id:
                return pool["pool_id"], member
    raise AssertionError(resource_id)


def _listing(pool_id, *, model="H100", region="us-east", resource_id=None, **quantities):
    listing = {"pool_id": pool_id, "gpu_model": model, "region": region,
               "offering_mode": "vm", "capacity_backing": "backed", **quantities}
    if resource_id:
        listing["resource_id"] = resource_id
    return listing


def _admitted(ledger, listing) -> bool:
    return ledger.probe(claim=_JUDGE.claim(listing)) is not None


_CASES = [
    ("declared attributes, one dimension", "a-1", _listing("gpu-a", gpu_count=1)),
    ("declared attributes, every dimension", "a-1",
     _listing("gpu-a", gpu_count=1, vcpu_count=8, ram_gb=32, disk_gb=100)),
    ("memory beyond availability", "a-1", _listing("gpu-a", gpu_count=1, ram_gb=200)),
    ("GPUs beyond availability", "a-1", _listing("gpu-a", gpu_count=8)),
    ("more than is declared", "a-1", _listing("gpu-a", gpu_count=16)),
    ("a model the member lacks", "a-1", _listing("gpu-a", model="A100", gpu_count=1)),
    ("a region only in the pool hint", "b-1",
     _listing("hint-region", region="us-west", gpu_count=1)),
    ("a specific resource, which drops pool_id", "spec-1",
     _listing("spec", model="A100", region="eu", resource_id="spec-1", gpu_count=1, ram_gb=32)),
    ("a specific resource of another model", "spec-1",
     _listing("spec", model="H100", region="eu", resource_id="spec-1", gpu_count=1)),
]
_IDS = [case[0] for case in _CASES]


@pytest.mark.parametrize(("label", "resource_id", "listing"), _CASES, ids=_IDS)
def test_declared_feasibility_agrees_with_admission_when_nothing_is_held(
    unheld, label, resource_id, listing
):
    pool_id, member = _member(unheld, resource_id)

    assert _JUDGE.member_feasible(
        listing, pool_id=pool_id, member=member, use_available=False
    ) == _admitted(unheld, listing)


@pytest.mark.parametrize(("label", "resource_id", "listing"), _CASES, ids=_IDS)
def test_available_feasibility_agrees_with_admission_under_holds(
    held, label, resource_id, listing
):
    pool_id, member = _member(held, resource_id)

    assert _JUDGE.member_feasible(
        listing, pool_id=pool_id, member=member, use_available=True
    ) == _admitted(held, listing)


_FUNGIBLE = [case for case in _CASES if "resource_id" not in case[2]]


@pytest.mark.parametrize(
    ("label", "resource_id", "listing"), _FUNGIBLE, ids=[case[0] for case in _FUNGIBLE]
)
def test_a_capacity_bucket_stands_in_for_its_fungible_members(
    held, label, resource_id, listing
):
    buckets = [
        bucket for bucket in capacity_bucket_projection(held.list_resources())
        if bucket["pool_id"] == listing["pool_id"]
    ]

    assert any(
        _JUDGE.bucket_feasible(listing, bucket=bucket) for bucket in buckets
    ) == _admitted(held, listing)


def test_the_cases_cover_both_outcomes(unheld, held):
    # Agreement is only evidence if both answers occur on each ledger.
    for ledger in (unheld, held):
        outcomes = {_admitted(ledger, listing) for _, _, listing in _CASES}
        assert outcomes == {True, False}


def test_the_adapter_invents_no_resource_type():
    # A member that states no kind is not given one; reconciliation holds it
    # before it would reach this check.
    member = {"physical_resource_id": "m", "capacity": {"gpu_count": 1},
              "attributes": {"gpu_model": "H100", "region": "us-east"}}

    assert member_snapshot_row("pool", member, use_available=False)["resource_type"] is None
    assert not _JUDGE.member_feasible(
        _listing("pool", gpu_count=1), pool_id="pool", member=member, use_available=False
    )
