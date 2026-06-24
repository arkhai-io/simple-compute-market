from __future__ import annotations

import pytest
from fastapi import HTTPException

from domains.vms.provisioning.storefront_models import InterruptDealRequest
import market_storefront.server  # noqa: F401 - initializes controller import order
from market_storefront.controllers.admin_controller import AdminController


class _FakeDb:
    def __init__(self, *, interruptible: bool = True) -> None:
        self.reason: str | None = None
        self.interruptible = interruptible

    async def load_escrow(self, *, escrow_uid: str):
        if escrow_uid == "missing":
            return None
        return {
            "escrow_uid": escrow_uid,
            "negotiation_id": "neg-1",
            "status": "ready",
        }

    async def get_listing_id_by_escrow_uid(self, *, escrow_uid: str):
        return "listing-1"

    async def load_listing(self, *, listing_id: str):
        return {
            "listing_id": listing_id,
            "offer_resource": {
                "gpu_model": "A100",
                "interruptible": self.interruptible,
            },
        }

    async def load_negotiation_thread_row(self, *, negotiation_id: str):
        return {
            "negotiation_id": negotiation_id,
            "buyer_escrow_proposal": None,
        }

    async def update_escrow(self, *, escrow_uid: str, reason: str | None = None, **_):
        self.reason = reason


class _FakeCapacity:
    def __init__(self) -> None:
        self.truncated: tuple[str, str] | None = None

    async def truncate_lease(self, *, allocation_id: str, lease_end_utc: str):
        self.truncated = (allocation_id, lease_end_utc)
        return {
            "allocation_id": allocation_id,
            "state": "leased",
            "lease_end_utc": lease_end_utc,
        }


def _controller(db: _FakeDb, capacity: _FakeCapacity) -> AdminController:
    ctl = AdminController(db=db, _key=None)
    ctl._capacity = lambda: capacity  # type: ignore[method-assign]
    ctl._find_live_allocation_for_escrow = _find_allocation  # type: ignore[method-assign]
    return ctl


async def _find_allocation(_escrow_uid: str):
    return {
        "allocation_id": "alloc-1",
        "state": "leased",
        "resource_id": "machine-1",
    }


@pytest.mark.asyncio
async def test_interrupt_deal_dry_run_does_not_truncate() -> None:
    db = _FakeDb()
    capacity = _FakeCapacity()
    ctl = _controller(db, capacity)

    out = await ctl.interrupt_deal(
        "escrow-1",
        InterruptDealRequest(
            interrupted_at_utc="2026-06-24T10:11:12Z",
            dry_run=True,
        ),
    )

    assert out.status == "dry_run"
    assert out.lease_truncated is False
    assert out.allocation_id == "alloc-1"
    assert out.interrupted_at_utc == "2026-06-24 10:11"
    assert capacity.truncated is None
    assert db.reason is None


@pytest.mark.asyncio
async def test_interrupt_deal_truncates_capacity_lease() -> None:
    db = _FakeDb()
    capacity = _FakeCapacity()
    ctl = _controller(db, capacity)

    out = await ctl.interrupt_deal(
        "escrow-1",
        InterruptDealRequest(
            interrupted_at_utc="2026-06-24T10:11:12Z",
            reason="spot_preemption",
            seller_amount=7,
            refund_amount=3,
        ),
    )

    assert out.status == "interrupted"
    assert out.lease_truncated is True
    assert out.settlement_action == "splitter_declaration_pending"
    assert capacity.truncated == ("alloc-1", "2026-06-24 10:11")
    assert db.reason == "spot_preemption"


@pytest.mark.asyncio
async def test_interrupt_deal_rejects_non_interruptible_listing() -> None:
    ctl = _controller(_FakeDb(interruptible=False), _FakeCapacity())

    with pytest.raises(HTTPException) as exc_info:
        await ctl.interrupt_deal("escrow-1", InterruptDealRequest())

    assert exc_info.value.status_code == 409
    assert "not marked interruptible" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_interrupt_deal_unknown_escrow_returns_404() -> None:
    ctl = _controller(_FakeDb(), _FakeCapacity())

    with pytest.raises(HTTPException) as exc_info:
        await ctl.interrupt_deal("missing", InterruptDealRequest())

    assert exc_info.value.status_code == 404
