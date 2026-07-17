from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.deal_event_sink import notify_storefront_capacity_released


@pytest.mark.asyncio
async def test_release_event_routes_to_allocation_recorded_storefront_owner():
    storefront = MagicMock()
    storefront.__aenter__ = AsyncMock(return_value=storefront)
    storefront.__aexit__ = AsyncMock(return_value=False)
    storefront.notify_capacity_released = AsyncMock(return_value={})
    allocation = {
        "allocation_id": "alloc-7",
        "resource_id": "resource-2",
        "released_at": "2026-07-13T12:00:00+00:00",
        "deal_ref": {
            "listing_id": "listing-7",
            "escrow_uid": "escrow-7",
            "storefront_url": "https://owner.example/",
        },
    }

    with patch("storefront_client.StorefrontClient", return_value=storefront) as client:
        delivered = await notify_storefront_capacity_released(
            SimpleNamespace(
                storefront_url="https://default.example",
                storefront_admin_key="admin-key",
            ),
            allocation,
        )

    assert delivered is True
    client.assert_called_once_with(
        base_url="https://owner.example",
        admin_key="admin-key",
    )
    storefront.notify_capacity_released.assert_awaited_once_with(
        "alloc-7",
        resource_id="resource-2",
        released_at="2026-07-13T12:00:00+00:00",
    )
