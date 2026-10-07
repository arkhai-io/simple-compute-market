from __future__ import annotations

import pytest

from market_capacity_publication import (
    CapacityAdminRouteError,
    CapacityAdminRouteService,
    CapacityBindingError,
)


def _service(*, reserve=None, released=None) -> CapacityAdminRouteService:
    async def default_reserve(listing_id, claim, deal_ref):
        return {"capacity_reservation_id": "res-1", "claim": dict(claim), "deal_ref": dict(deal_ref)}

    async def default_released(event):
        return {"capacity_reservation_id": event["capacity_reservation_id"], "state": "released"}

    return CapacityAdminRouteService(
        reserve=reserve or default_reserve, released=released or default_released
    )


async def test_reserve_passes_the_claim_and_an_admin_deal_reference() -> None:
    reserved = await _service().reserve(
        {"listing_id": "listing-1", "escrow_uid": "uid-1", "required_attributes": {"gpu_count": 1}}
    )

    assert reserved["claim"] == {"gpu_count": 1}
    assert reserved["deal_ref"] == {
        "listing_id": "listing-1",
        "reserved_by": "admin",
        "escrow_uid": "uid-1",
    }


@pytest.mark.parametrize(
    ("raised", "status"),
    [
        (LookupError("listing has no binding"), 404),
        (CapacityBindingError("site not configured"), 500),
        (ConnectionError("refused"), 502),
    ],
)
async def test_reserve_maps_refusals(raised: Exception, status: int) -> None:
    async def failing(*_args):
        raise raised

    with pytest.raises(CapacityAdminRouteError) as refused:
        await _service(reserve=failing).reserve({"listing_id": "listing-1"})
    assert refused.value.status_code == status


async def test_reserve_without_capacity_conflicts() -> None:
    async def nothing(*_args):
        return None

    with pytest.raises(CapacityAdminRouteError) as refused:
        await _service(reserve=nothing).reserve({"listing_id": "listing-1"})
    assert refused.value.status_code == 409


async def test_reserve_needs_a_listing() -> None:
    with pytest.raises(CapacityAdminRouteError) as refused:
        await _service().reserve({})
    assert refused.value.status_code == 400


async def test_capacity_released_records_through_the_domain_hook() -> None:
    recorded = await _service().capacity_released({"capacity_reservation_id": "res-1"})

    assert recorded == {"capacity_reservation_id": "res-1", "state": "released"}


async def test_capacity_released_for_an_unknown_reservation_is_not_found() -> None:
    async def unknown(_event):
        raise LookupError("reservation 'res-9' not found")

    with pytest.raises(CapacityAdminRouteError) as refused:
        await _service(released=unknown).capacity_released({"capacity_reservation_id": "res-9"})
    assert refused.value.status_code == 404
    with pytest.raises(CapacityAdminRouteError):
        await _service().capacity_released({})
