from __future__ import annotations

import pytest
from fastapi import HTTPException
from market_capacity_publication import PublicationBinding

import market_storefront.server  # noqa: F401 - initializes controller import order
from market_storefront.controllers.admin_controller import AdminController
from market_storefront.models.capacity_admin_models import InterruptDealRequest
from tests.fulfillment_fixtures import (
    BUYER_PRINCIPAL,
    SELLER_PRINCIPAL,
    VmLifecycleFixture,
    make_vm_lifecycle_fixture,
)


async def _commit_plan(lifecycle: VmLifecycleFixture, *, interruptible: bool) -> None:
    """Commit the deal's settlement plan, with or without the interruptible term."""
    service_terms = (
        {"interruptible": {"schema": "vms.interruptible.v1", "refund_authority": "seller_declared"}}
        if interruptible
        else {}
    )
    await lifecycle.db.commit_settlement_plan(
        negotiation_id="neg-1",
        settlement_plan={
            "obligations": [],
            "buyer_principal": BUYER_PRINCIPAL.model_dump(mode="json"),
            "seller_principal": SELLER_PRINCIPAL.model_dump(mode="json"),
            "service_terms": service_terms,
        },
        buyer_principal=BUYER_PRINCIPAL,
        seller_principal=SELLER_PRINCIPAL,
    )


class _FakeCapacity:
    def __init__(self) -> None:
        self.truncated: tuple[PublicationBinding, str, str] | None = None

    async def truncate_lease(
        self,
        binding: PublicationBinding,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, str]:
        self.truncated = (binding, capacity_reservation_id, lease_end_utc)
        return {
            "capacity_reservation_id": capacity_reservation_id,
            "state": "leased",
            "lease_end_utc": lease_end_utc,
            "site": binding.site_id,
        }


def _controller(
    lifecycle: VmLifecycleFixture,
    capacity: _FakeCapacity,
    monkeypatch,
) -> AdminController:
    async def capacity_binding_for_listing(repository, listing_id):
        assert repository is lifecycle.db
        assert listing_id == lifecycle.listing_binding.listing_id
        return lifecycle.capacity_binding

    monkeypatch.setattr(
        "market_storefront.services.capacity_client.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )
    ctl = AdminController(
        db=lifecycle.db,
        capacity_runtime=capacity,
        _key=None,
    )

    async def find_reservation(escrow_uid: str):
        assert escrow_uid == "escrow-1"
        return {
            "capacity_reservation_id": "alloc-1",
            "state": "leased",
            "resource_id": "machine-1",
            "site": lifecycle.thread_binding.site_id,
        }

    ctl._find_live_reservation_for_escrow = find_reservation  # type: ignore[method-assign]
    return ctl


@pytest.mark.asyncio
async def test_interrupt_deal_dry_run_does_not_truncate(
    tmp_path,
    monkeypatch,
) -> None:
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "interrupt-dry-run.db",
        status="ready",
    )
    await _commit_plan(lifecycle, interruptible=True)
    capacity = _FakeCapacity()
    ctl = _controller(lifecycle, capacity, monkeypatch)

    out = await ctl.interrupt_deal(
        "escrow-1",
        InterruptDealRequest(
            interrupted_at_utc="2026-06-24T10:11:12Z",
            dry_run=True,
        ),
    )

    assert out.status == "dry_run"
    assert out.lease_truncated is False
    assert out.capacity_reservation_id == "alloc-1"
    assert out.interrupted_at_utc == "2026-06-24 10:11"
    assert capacity.truncated is None
    escrow = await lifecycle.db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None
    assert escrow["reason"] is None


@pytest.mark.asyncio
async def test_interrupt_deal_truncates_capacity_lease(
    tmp_path,
    monkeypatch,
) -> None:
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "interrupt.db",
        status="ready",
        # The current listing does not decide: the committed plan does.
        interruptible=False,
    )
    await _commit_plan(lifecycle, interruptible=True)
    capacity = _FakeCapacity()
    ctl = _controller(lifecycle, capacity, monkeypatch)

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
    assert capacity.truncated == (
        lifecycle.capacity_binding,
        "alloc-1",
        "2026-06-24 10:11",
    )
    escrow = await lifecycle.db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None
    assert escrow["reason"] == "spot_preemption"


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", ["without_interruptible_term", "none"])
async def test_interrupt_deal_rejects_a_deal_its_plan_did_not_make_interruptible(
    tmp_path,
    monkeypatch,
    plan,
) -> None:
    """Refused even though the listing now says interruptible: a deal's
    interruptibility is a term of its committed plan."""
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "non-interruptible.db",
        status="ready",
        interruptible=True,
    )
    if plan != "none":
        await _commit_plan(lifecycle, interruptible=False)
    ctl = _controller(lifecycle, _FakeCapacity(), monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await ctl.interrupt_deal("escrow-1", InterruptDealRequest())

    assert exc_info.value.status_code == 409
    assert "not marked interruptible" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_interrupt_deal_unknown_escrow_returns_404(
    tmp_path,
    monkeypatch,
) -> None:
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "unknown-escrow.db",
        status="ready",
    )
    ctl = _controller(lifecycle, _FakeCapacity(), monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        await ctl.interrupt_deal("missing", InterruptDealRequest())

    assert exc_info.value.status_code == 404
