"""Two-phase reserve: acceptance places the hold, settlement commits it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from market_storefront.services.vm_fulfillment_service import (
    _commit_capacity_hold,
    _commit_fresh_reservation,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from market_identity import Ed25519Signer
from market_negotiation_runtime import Acceptance, AgreementTerms, NegotiationTerms
from market_storefront.negotiation_runtime import _place_capacity_hold



_BUYER = Ed25519Signer(b"\x61" * 32).identity
_SELLER = Ed25519Signer(b"\x62" * 32).identity


async def _place_hold(
    repository,
    *,
    negotiation_id,
    listing_id,
    order_dict,
):
    await _place_capacity_hold(
        repository,
        Acceptance(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            listing=order_dict,
            listing_record=order_dict,
            terms=NegotiationTerms(decoded=None, wire=None),
            pinned_proposal=None,
            agreed_amount=1,
            agreement=AgreementTerms(3600),
            uses_scalar_amount=True,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
        ),
    )

class FakeCapacity:
    def __init__(self, *, reserve_result=None, commit_error=None) -> None:
        self.reserve_result = reserve_result
        self.commit_error = commit_error
        self.reserve_calls: list[dict] = []
        self.commit_calls: list[dict] = []

    async def reserve(self, **kw):
        self.reserve_calls.append(kw)
        return self.reserve_result

    async def commit(self, **kw):
        self.commit_calls.append(kw)
        if self.commit_error is not None:
            raise self.commit_error


def _events():
    captured = []

    def stage_event(stage, event, **fields):
        captured.append((stage, event, fields))

    return captured, stage_event


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()


def _hold(**overrides) -> dict:
    base = {
        "capacity_reservation_id": "alloc-1",
        "resource_id": "res-1",
        "vm_host": "kvm1",
        "hold_expires_at": _future(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Settlement half: commit the hold before provisioning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_hold_commits_before_provisioning():
    capacity = FakeCapacity()
    captured, stage_event = _events()

    reserved = await _commit_capacity_hold(
        capacity=capacity,
        held_reservation=_hold(),
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    )

    assert reserved["capacity_reservation_id"] == "alloc-1"
    assert capacity.reserve_calls == []  # no fresh reserve raced
    commit = capacity.commit_calls[0]
    assert commit["capacity_reservation_id"] == "alloc-1"
    assert commit["idempotency_ref"] == "0xesc"
    assert captured[0][1] == "capacity_hold_committed"


@pytest.mark.asyncio
async def test_fresh_reservation_commits_before_provisioning():
    capacity = FakeCapacity()
    captured, stage_event = _events()

    await _commit_fresh_reservation(
        capacity=capacity,
        reserved=_hold(),
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    )

    commit = capacity.commit_calls[0]
    assert commit["capacity_reservation_id"] == "alloc-1"
    assert commit["resource_id"] == "res-1"
    assert commit["idempotency_ref"] == "0xesc"
    assert captured[0][1] == "capacity_reservation_committed"


@pytest.mark.asyncio
async def test_fresh_reservation_commit_failure_is_not_ignored():
    capacity = FakeCapacity(commit_error=RuntimeError("409 conflict"))
    _, stage_event = _events()

    with pytest.raises(RuntimeError, match="409 conflict"):
        await _commit_fresh_reservation(
            capacity=capacity,
            reserved=_hold(),
            escrow_uid="0xesc",
            duration_seconds=3600,
            stage_event=stage_event,
        )


@pytest.mark.asyncio
async def test_lapsed_hold_falls_back_to_fresh_reserve():
    capacity = FakeCapacity()
    _, stage_event = _events()

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert await _commit_capacity_hold(
        capacity=capacity,
        held_reservation=_hold(hold_expires_at=past),
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    ) is None
    assert capacity.commit_calls == []


@pytest.mark.asyncio
async def test_ledger_refusal_falls_back_to_fresh_reserve():
    """The ledger may have swept the hold between our check and the
    commit — a refused commit means reserve fresh, not fail the deal."""
    capacity = FakeCapacity(commit_error=RuntimeError("409 conflict"))
    _, stage_event = _events()

    assert await _commit_capacity_hold(
        capacity=capacity,
        held_reservation=_hold(),
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    ) is None


@pytest.mark.asyncio
async def test_no_hold_means_no_commit():
    capacity = FakeCapacity()
    _, stage_event = _events()
    assert await _commit_capacity_hold(
        capacity=capacity,
        held_reservation=None,
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    ) is None
    assert capacity.commit_calls == []


# ---------------------------------------------------------------------------
# Acceptance half: place the hold and remember it
# ---------------------------------------------------------------------------

def _settings(ttl: float):
    return SimpleNamespace(capacity=SimpleNamespace(hold_ttl_seconds=ttl))


ORDER = {
    "listing_id": "lst-1",
    "offer_resource": {
        "resource_id": "res-1", "gpu_model": "H200", "gpu_count": 2,
    },
}


def test_claim_survives_listing_model_validation():
    """Listing validation preserves the caller's wire mapping.

    Accept paths derive the same pinned resource claim before and after model
    validation rather than silently selecting whichever resource is first.
    """
    from domains.vms.listings.models import Listing
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-1",
        "status": "open",
        "storefront_url": "http://seller:8001",
        "seller_principal": {
            "scheme": "eip191",
            "identifier": "0x2222222222222222222222222222222222222222",
        },
        "offer_resource": {
            "resource_id": "res-pin", "gpu_model": "H200", "gpu_count": 2,
            "sla": 99.0, "region": "California, US",
        },
        "accepted_escrows": [],
    }
    pinned = compute_capacity_claim_from_order(row)
    Listing.model_validate(row)
    assert isinstance(row["offer_resource"], dict)
    assert compute_capacity_claim_from_order(row) == pinned
    assert pinned["resource_id"] == "res-pin"


def test_claim_prefers_resource_id_over_pool_id():
    """A listing carrying both pool_id and resource_id is an intentionally
    specific-resource listing: resource_id wins and pool_id is dropped from
    the claim, rather than requiring both to match."""
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-both",
        "offer_resource": {
            "pool_id": "pool-A", "resource_id": "res-pin", "gpu_model": "H200",
            "gpu_count": 2, "sla": 99.0, "region": "California, US",
        },
    }
    claim = compute_capacity_claim_from_order(row)
    assert claim["resource_id"] == "res-pin"
    assert "pool_id" not in claim


# ----------------------------------------------------------------------
# multidimensional claim building
# ----------------------------------------------------------------------

def test_claim_carries_dimensions_when_listing_declares_a_shape():
    """gpu_count/vcpu_count/ram_gb/disk_gb move into a dimensions map,
    checked with full held/available accounting -- not required_attributes
    exact-match, which would incorrectly demand every future claim declare
    the identical quantity rather than merely fit within it."""
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-shaped",
        "offer_resource": {
            "resource_id": "res-shaped", "gpu_model": "H200", "gpu_count": 2,
            "sla": 99.0, "region": "California, US",
            "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500,
        },
    }
    claim = compute_capacity_claim_from_order(row)
    assert claim["dimensions"] == {
        "gpu_count": 2, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500,
    }
    # gpu_count moved off the top level entirely -- it's a dimensions-only
    # key now, not also an exact-match attribute.
    assert "gpu_count" not in claim
    assert claim["resource_id"] == "res-shaped"


def test_claim_omits_undeclared_dimensions_for_older_listings():
    """A listing published before vcpu_count/ram_gb/disk_gb existed (or
    that simply never set them) still produces a valid claim -- gpu_count
    alone, the same shape any claim without a declared multidimensional
    shape produces."""
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-unshaped",
        "offer_resource": {
            "resource_id": "res-unshaped", "gpu_model": "H200", "gpu_count": 1,
            "sla": 99.0, "region": "California, US",
        },
    }
    claim = compute_capacity_claim_from_order(row)
    assert claim["dimensions"] == {"gpu_count": 1}


@pytest.mark.parametrize("order", [None, {}])
def test_claim_raises_when_order_is_missing(order):
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    with pytest.raises(ValueError, match="without a settlement order"):
        compute_capacity_claim_from_order(order)


@pytest.mark.parametrize("identity", ["", "   ", "bad/id", "bad id"])
def test_claim_rejects_invalid_legacy_identity(identity):
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-invalid",
        "offer_resource": {
            "resource_id": identity,
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.0,
            "region": "California, US",
        },
    }
    with pytest.raises(ValueError):
        compute_capacity_claim_from_order(row)


def test_claim_raises_when_neither_pool_id_nor_resource_id_present():
    """An under-specified claim (no pool_id, no resource_id) must fail
    loudly rather than silently matching on shape attributes alone — the
    listing-creation guard is expected to prevent this shape from being
    published at all; this is the backstop for anything that reaches
    claim-building anyway."""
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-under-specified",
        "offer_resource": {
            "gpu_model": "H200", "gpu_count": 2,
            "sla": 99.0, "region": "California, US",
        },
    }
    with pytest.raises(ValueError, match="lst-under-specified"):
        compute_capacity_claim_from_order(row)


@pytest.mark.asyncio
async def test_acceptance_places_and_records_the_hold(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    capacity = FakeCapacity(reserve_result=_hold())

    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(900),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=capacity,
    ):
        await _place_hold(db, negotiation_id="neg-1", listing_id="lst-1", order_dict=ORDER,)

    reserve = capacity.reserve_calls[0]
    assert reserve["ttl_seconds"] == 900
    assert reserve["claim"]["gpu_model"] == "H200"
    assert reserve["deal_ref"]["negotiation_id"] == "neg-1"

    hold = await db.load_capacity_hold(negotiation_id="neg-1")
    assert hold["capacity_reservation_id"] == "alloc-1"
    assert hold["payload"]["resource_id"] == "res-1"


@pytest.mark.asyncio
async def test_acceptance_hold_pins_to_the_listings_mapped_site(tmp_path):
    """A listing already mapped to a site (derived_compute_listings)
    must place its acceptance-time hold there -- proves site_id
    resolution reaches _place_capacity_hold's reserve() call, not just
    that reserve() itself honors a site kwarg when given one."""
    from domains.vms.listings.reconciler import record_derived_listing

    db = SQLiteClient(db_path=str(tmp_path / "hold.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    record_derived_listing(
        db.db_path, listing_id="lst-1", site_id="dc-mapped",
        resource_id="res-1", gpu_count=2,
    )
    capacity = FakeCapacity(reserve_result=_hold())

    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(900),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=capacity,
    ):
        await _place_hold(db, negotiation_id="neg-mapped", listing_id="lst-1", order_dict=ORDER,)

    assert capacity.reserve_calls[0]["site"] == "dc-mapped"


@pytest.mark.asyncio
async def test_acceptance_survives_hold_refusal_and_zero_ttl(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))

    # No capacity: acceptance proceeds, nothing recorded.
    refused = FakeCapacity(reserve_result=None)
    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(900),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=refused,
    ):
        await _place_hold(db, negotiation_id="neg-2", listing_id="lst-1", order_dict=ORDER,)
    assert await db.load_capacity_hold(negotiation_id="neg-2") is None

    # ttl 0 disables the feature entirely.
    disabled = FakeCapacity(reserve_result=_hold())
    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(0),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=disabled,
    ):
        await _place_hold(db, negotiation_id="neg-3", listing_id="lst-1", order_dict=ORDER,)
    assert disabled.reserve_calls == []


@pytest.mark.asyncio
async def test_acceptance_hold_ttl_is_capped_by_the_listings_mapped_pool_preference(
    tmp_path,
):
    """The full acceptance-hold sequence as one real orchestration:
    lookup_pool_policy_tags -> capped_hold_seconds -> reserve(ttl_seconds=...),
    not just each piece proven independently. A requested TTL of 900s,
    capped by a mapped pool's max_reservation_hold_seconds=30, must reach
    reserve() as 30, not 900.
    """
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    capacity = FakeCapacity(reserve_result=_hold())

    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(900),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=capacity,
    ), patch(
        "market_storefront.negotiation_runtime.lookup_pool_policy_tags",
        return_value={"max_reservation_hold_seconds": 30},
    ):
        await _place_hold(db, negotiation_id="neg-capped", listing_id="lst-1", order_dict=ORDER,)

    assert capacity.reserve_calls[0]["ttl_seconds"] == 30.0


@pytest.mark.asyncio
async def test_acceptance_hold_ttl_unchanged_when_no_pool_preference(tmp_path):
    """The other side of the same sequence: an empty/absent policy_tags
    result (the ordinary case -- no mapped pool, or one with no hold
    preference) must leave the storefront's own configured TTL untouched,
    not silently zero it or something else unintended."""
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    capacity = FakeCapacity(reserve_result=_hold())

    with patch(
        "market_storefront.negotiation_runtime.settings", _settings(900),
    ), patch(
        "market_storefront.negotiation_runtime.build_capacity_client",
        return_value=capacity,
    ), patch(
        "market_storefront.negotiation_runtime.lookup_pool_policy_tags",
        return_value={},
    ):
        await _place_hold(db, negotiation_id="neg-uncapped", listing_id="lst-1", order_dict=ORDER,)

    assert capacity.reserve_calls[0]["ttl_seconds"] == 900
