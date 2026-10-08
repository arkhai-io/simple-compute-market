"""The deal-control routes, through the canonical storefront client.

Each route is the kit's contract bound to bare metal's hooks; these tests drive
them as an administrator, or as the site, would, over the production app.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from market_identity import Eip191Signer, TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError
from test_http_settlement import (
    ADMIN_SIGNER,
    BUYER,
    ESCROW_UID,
    SELLER_SIGNER,
    SITE_SIGNER,
    _accepted_runtime,
    _app,
    _buyer,
    _CapacityClient,
    _ProvisioningClient,
)

from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding


def _client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _runtime(tmp_path, *, verifier=None, provisioning=None):
    async def accept(**_kwargs):
        return 1

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"), verifier or accept
    )
    capacity = _CapacityClient()
    runtime = replace(
        runtime,
        capacity_client=capacity,
        fulfillment_client=provisioning or _ProvisioningClient(),
        site_bindings=(
            BareMetalSiteBinding(
                site_id="site-a",
                authority_url="http://site-a",
                authority_principal=SITE_SIGNER.identity,
            ),
        ),
    )
    return runtime, negotiation_id, capacity


async def test_verify_reads_the_escrow_against_a_listing_and_writes_nothing(
    tmp_path,
) -> None:
    calls = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 1

    runtime, negotiation_id, _capacity = await _runtime(tmp_path, verifier=verifier)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            valid = await admin.verify_settle(
                ESCROW_UID,
                seller_wallet="0x3333333333333333333333333333333333333333",
                agreed_price=100,
                agreed_duration_seconds=3600,
                listing_id="listing-1",
            )
            unknown_chain = await admin.verify_settle(
                ESCROW_UID,
                seller_wallet="0x3333333333333333333333333333333333333333",
                agreed_price=100,
                agreed_duration_seconds=3600,
                listing_id="listing-1",
                chain_name="mainnet",
            )
            with pytest.raises(StorefrontClientError) as missing:
                await admin.verify_settle(
                    ESCROW_UID,
                    seller_wallet="0x3333333333333333333333333333333333333333",
                    agreed_price=100,
                    agreed_duration_seconds=3600,
                    listing_id="no-such-listing",
                )

    assert valid == {"escrow_uid": ESCROW_UID, "valid": True, "reason": None}
    assert unknown_chain["valid"] is False
    assert missing.value.status_code == 404
    assert len(calls) == 1 and calls[0]["agreed_price"] == 100
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None
    assert (await runtime.settlement_runtime.get_status(negotiation_id)).obligations == []


async def test_evaluate_previews_the_reservation_settlement_would_make(tmp_path) -> None:
    runtime, _negotiation_id, capacity = await _runtime(tmp_path)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            preview = await admin.evaluate_settle(ESCROW_UID, listing_id="listing-1")

    assert preview["would_submit"] is True
    assert preview["host_id"] == "machine-1"
    assert preview["site_id"] == "site-a"
    assert preview["required_attributes"]["resource_id"] == "resource-1"
    assert preview["required_attributes"]["dimensions"] == {"units": 1}
    assert capacity.reserve_calls == []


async def test_wait_returns_once_the_settled_lease_is_active(tmp_path) -> None:
    runtime, negotiation_id, _capacity = await _runtime(tmp_path)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            before = await admin.wait_for_settlement(ESCROW_UID, timeout=0.1)
            async with _buyer(app) as buyer:
                await buyer.settle(
                    ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )
            # Settlement stepped the worker, which began the fulfillment; the
            # status read records it active.
            await runtime.fulfillment_service().status(
                negotiation_id=negotiation_id,
                buyer_principal=(await runtime.settlement_runtime.get_status(
                    negotiation_id
                )).obligations[1].payer_principal,
            )
            after = await admin.wait_for_settlement(ESCROW_UID, timeout=1.0)

    assert before.ready is False
    assert after.ready is True and after.status == "ready"


async def test_admin_reserve_takes_the_listings_machine(tmp_path) -> None:
    runtime, _negotiation_id, capacity = await _runtime(tmp_path)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            reserved = await admin.admin_reserve_capacity(
                required_attributes={}, listing_id="listing-1"
            )
            with pytest.raises(StorefrontClientError) as refused:
                await admin.admin_reserve_capacity(
                    required_attributes={"gpu_model": "a different model"},
                    listing_id="listing-1",
                )

    assert reserved.capacity_reservation_id == "reservation-a"
    [call] = capacity.reserve_calls
    assert call["site"] == "site-a"
    assert call["claim"]["resource_id"] == "resource-1"
    assert call["deal_ref"] == {"listing_id": "listing-1", "reserved_by": "admin"}
    assert refused.value.status_code == 409


async def test_only_the_named_sites_authority_may_report_a_release(tmp_path) -> None:
    runtime, _negotiation_id, _capacity = await _runtime(tmp_path)
    impostor = Eip191Signer(bytes.fromhex("55" * 32))
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, impostor, "service") as other:
            with pytest.raises(StorefrontClientError) as forged:
                await other.notify_capacity_released("reservation-a", site_id="site-a")
        async with _client(app, SITE_SIGNER, "service") as site:
            with pytest.raises(StorefrontClientError) as unknown:
                await site.notify_capacity_released("reservation-x", site_id="site-a")
            with pytest.raises(StorefrontClientError) as other_site:
                await site.notify_capacity_released("reservation-a", site_id="site-b")

    assert forged.value.status_code == 403
    assert unknown.value.status_code == 404
    assert other_site.value.status_code == 403
