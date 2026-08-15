from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet

from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.deal_event_sink import (
    StorefrontLifecycleEventSink,
    notify_storefront_capacity_released,
)


def _authority(principal):
    return SimpleNamespace(
        active_principals=lambda role: TrustedIdentitySet(
            identities=(principal,)
        )
    )


@pytest.mark.parametrize(
    ("service", "storefront_signer"),
    (
        (Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)),
        (Eip191Signer(b"\x21" * 32), Eip191Signer(b"\x22" * 32)),
    ),
)
@pytest.mark.asyncio
async def test_release_event_uses_service_signer_site_and_storefront_pin(
    service,
    storefront_signer,
):
    storefront = MagicMock()
    storefront.notify_capacity_released = AsyncMock(return_value={})
    storefront.close = AsyncMock()
    identity = ProvisioningIdentityContext(
        signer=service,
        storefront_principal=storefront_signer.identity,
        admin_principal=Ed25519Signer(b"\x13" * 32).identity,
        storefront_site_id="site-west",
    )
    sink = StorefrontLifecycleEventSink(
        SimpleNamespace(storefront_url="https://configured.example/"),
        identity,
        _authority(storefront_signer.identity),
    )
    reservation = {
        "capacity_reservation_id": "alloc-7",
        "executor_kind": "vm",
        "released_at": "2026-07-13T12:00:00+00:00",
        "deal_ref": {"storefront_url": "https://untrusted.example/"},
    }
    event_id = "capacity_released:alloc-7:2026-07-13T12:00:00+00:00"
    request_id = "capacity-release-" + hashlib.sha256(event_id.encode()).hexdigest()

    with patch("storefront_client.StorefrontClient", return_value=storefront) as client:
        delivered = await notify_storefront_capacity_released(
            SimpleNamespace(storefront_url="https://configured.example/"),
            reservation,
            sink=sink,
        )
        await sink.close()

    assert delivered is True
    client.assert_called_once_with(
        base_url="https://configured.example",
        signer=service,
        caller_role="service",
        expected_publishers=TrustedIdentitySet(
            identities=(storefront_signer.identity,)
        ),
    )
    storefront.notify_capacity_released.assert_awaited_once_with(
        "alloc-7",
        site_id="site-west",
        released_at="2026-07-13T12:00:00+00:00",
        request_id=request_id,
    )
    storefront.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_uncertain_ack_retry_reuses_the_same_client_and_request_identity():
    service = Ed25519Signer(b"\x11" * 32)
    storefront_signer = Ed25519Signer(b"\x12" * 32)
    storefront = MagicMock()
    storefront.notify_capacity_released = AsyncMock(
        side_effect=[RuntimeError("ack lost"), {}]
    )
    identity = ProvisioningIdentityContext(
        signer=service,
        storefront_principal=storefront_signer.identity,
        admin_principal=Ed25519Signer(b"\x13" * 32).identity,
        storefront_site_id="default",
    )
    sink = StorefrontLifecycleEventSink(
        SimpleNamespace(storefront_url="https://configured.example"),
        identity,
        _authority(storefront_signer.identity),
    )
    reservation = {
        "capacity_reservation_id": "alloc-7",
        "executor_kind": "vm",
        "released_at": "2026-07-13T12:00:00+00:00",
    }

    with patch("storefront_client.StorefrontClient", return_value=storefront) as client:
        assert await notify_storefront_capacity_released(
            SimpleNamespace(storefront_url="ignored"), reservation, sink=sink
        ) is False
        assert await notify_storefront_capacity_released(
            SimpleNamespace(storefront_url="ignored"), reservation, sink=sink
        ) is True

    client.assert_called_once()
    first, second = storefront.notify_capacity_released.await_args_list
    assert first.kwargs["request_id"] == second.kwargs["request_id"]
    assert first.kwargs["site_id"] == second.kwargs["site_id"] == "default"
