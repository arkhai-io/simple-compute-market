"""Two-phase reserve: acceptance places the hold, settlement commits it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from market_storefront.services.vm_fulfillment_service import _commit_capacity_hold
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils.sync_negotiation import _place_capacity_hold


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
        "allocation_id": "alloc-1",
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
        held_allocation=_hold(),
        escrow_uid="0xesc",
        duration_seconds=3600,
        stage_event=stage_event,
    )

    assert reserved["allocation_id"] == "alloc-1"
    assert capacity.reserve_calls == []  # no fresh reserve raced
    commit = capacity.commit_calls[0]
    assert commit["allocation_id"] == "alloc-1"
    assert commit["idempotency_ref"] == "0xesc"
    assert captured[0][1] == "capacity_hold_committed"


@pytest.mark.asyncio
async def test_lapsed_hold_falls_back_to_fresh_reserve():
    capacity = FakeCapacity()
    _, stage_event = _events()

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert await _commit_capacity_hold(
        capacity=capacity,
        held_allocation=_hold(hold_expires_at=past),
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
        held_allocation=_hold(),
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
        held_allocation=None,
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
    """Listing.model_validate mutates the row it validates, replacing
    offer_resource with a ComputeResource instance — the accept paths run
    after such a validation, and an un-pinned claim makes the hold grab
    whatever resource is first in line (the e2e caught this as a deal
    provisioned on the wrong machine)."""
    from domains.vms.listings.models import Listing
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    row = {
        "listing_id": "lst-1",
        "status": "open",
        "seller": "http://seller:8001",
        "offer_resource": {
            "resource_id": "res-pin", "gpu_model": "H200", "gpu_count": 2,
            "sla": 99.0, "region": "California, US",
        },
        "accepted_escrows": [],
    }
    pinned = compute_capacity_claim_from_order(row)
    Listing.model_validate(row)
    assert not isinstance(row["offer_resource"], dict)  # the mutation
    assert compute_capacity_claim_from_order(row) == pinned
    assert pinned["resource_id"] == "res-pin"


@pytest.mark.asyncio
async def test_acceptance_places_and_records_the_hold(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"))
    capacity = FakeCapacity(reserve_result=_hold())

    with patch(
        "market_storefront.utils.config.settings", _settings(900),
    ), patch(
        "market_storefront.services.capacity_client.build_capacity_client",
        return_value=capacity,
    ):
        await _place_capacity_hold(
            db, negotiation_id="neg-1", listing_id="lst-1", order_dict=ORDER,
        )

    reserve = capacity.reserve_calls[0]
    assert reserve["ttl_seconds"] == 900
    assert reserve["claim"]["gpu_model"] == "H200"
    assert reserve["deal_ref"]["negotiation_id"] == "neg-1"

    hold = await db.load_capacity_hold(negotiation_id="neg-1")
    assert hold["allocation_id"] == "alloc-1"
    assert hold["payload"]["resource_id"] == "res-1"


@pytest.mark.asyncio
async def test_acceptance_survives_hold_refusal_and_zero_ttl(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "hold.db"))

    # No capacity: acceptance proceeds, nothing recorded.
    refused = FakeCapacity(reserve_result=None)
    with patch(
        "market_storefront.utils.config.settings", _settings(900),
    ), patch(
        "market_storefront.services.capacity_client.build_capacity_client",
        return_value=refused,
    ):
        await _place_capacity_hold(
            db, negotiation_id="neg-2", listing_id="lst-1", order_dict=ORDER,
        )
    assert await db.load_capacity_hold(negotiation_id="neg-2") is None

    # ttl 0 disables the feature entirely.
    disabled = FakeCapacity(reserve_result=_hold())
    with patch(
        "market_storefront.utils.config.settings", _settings(0),
    ), patch(
        "market_storefront.services.capacity_client.build_capacity_client",
        return_value=disabled,
    ):
        await _place_capacity_hold(
            db, negotiation_id="neg-3", listing_id="lst-1", order_dict=ORDER,
        )
    assert disabled.reserve_calls == []
