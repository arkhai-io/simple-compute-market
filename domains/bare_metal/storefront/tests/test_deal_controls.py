"""The deal-control routes, through the canonical storefront client.

Each route is the kit's contract bound to bare metal's hooks; these tests drive
them as an administrator, or as the site, would, over the production app.
"""

from __future__ import annotations

import sqlite3
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

from site_trust import seeded_sites


def _client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


# A second site authority's development key; never used on any public network.
SITE_B_SIGNER = Eip191Signer(bytes.fromhex("56" * 32))


async def _runtime(tmp_path, *, verifier=None, provisioning=None, authorities=None):
    async def accept(**_kwargs):
        return 1

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"), verifier or accept
    )
    capacity = _CapacityClient()
    # The site's callbacks verify against its service peer, seeded as startup
    # seeds it.
    bindings, trust = seeded_sites(
        runtime.db.db_path, authorities or {"site-a": SITE_SIGNER.identity}
    )
    runtime = replace(
        runtime,
        capacity_client=capacity,
        fulfillment_client=provisioning or _ProvisioningClient(),
        site_bindings=bindings,
        service_peer_trust=trust,
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
    class Provisioning(_ProvisioningClient):
        state = "dispatching"

        async def get_fulfillment_status(self, fulfillment_id, **request):
            status = await super().get_fulfillment_status(fulfillment_id, **request)
            status.state = self.state
            return status

    provisioning = Provisioning()
    runtime, negotiation_id, capacity = await _runtime(
        tmp_path, provisioning=provisioning
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            await admin.admin_pause_lifecycle_loops()
            before = await admin.wait_for_settlement(ESCROW_UID, timeout=0.1)
            async with _buyer(app) as buyer:
                await buyer.settle_evm(
                    ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )
            pending = await admin.wait_for_settlement(ESCROW_UID, timeout=0.1)
            provisioning.state = "active"
            after = await admin.wait_for_settlement(ESCROW_UID, timeout=1.0)
            observed = await runtime.db.load_bare_metal_fulfillment_lifecycle(
                negotiation_id=negotiation_id
            )
            assert observed["state"] == "active"
            assert not observed.get("lease_ready_evidence_digest")
            serviced = await admin.admin_run_lifecycle_cycle("settlement-servicing")

    assert before.ready is False
    assert pending.ready is False and pending.status == "settlement_verified"
    assert after.ready is True and after.status == "ready"
    assert serviced["processed"] == 1
    assert len(capacity.reserve_calls) == len(provisioning.begin_calls) == 1


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


async def test_admin_reserve_refuses_a_listing_no_authority_stands_behind(tmp_path) -> None:
    runtime, _negotiation_id, capacity = await _runtime(tmp_path)
    # A binding recorded unbacked: bare metal publishes none today, so the
    # durable record is written directly past its immutability trigger.
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute("DROP TRIGGER storefront_listing_binding_immutable")
        conn.execute(
            "UPDATE storefront_listing_bindings SET capacity_backing='unbacked' "
            "WHERE listing_id='listing-1'"
        )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.admin_reserve_capacity(
                    required_attributes={}, listing_id="listing-1"
                )

    assert refused.value.status_code == 409
    assert capacity.reserve_calls == []


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

    # An impostor fails the site's authentication; the site's own report of a
    # reservation the storefront does not hold is not found; and a report naming
    # an unconfigured site is refused with the trust's reason, before any handler.
    assert forged.value.status_code == 403
    assert unknown.value.status_code == 404
    assert other_site.value.status_code == 403
    assert "exactly one configured service peer" in str(other_site.value)


async def test_one_configured_sites_authority_cannot_report_anothers_release(
    tmp_path,
) -> None:
    """Two configured sites, each with its own peer. Site B's authority signing a
    report that names site A fails site A's authentication (403); signing one
    that names itself authenticates, and the reservation, held at site A, is
    then not found as site B's (404)."""
    runtime, negotiation_id, _capacity = await _runtime(
        tmp_path,
        authorities={"site-a": SITE_SIGNER.identity, "site-b": SITE_B_SIGNER.identity},
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
        async with _client(app, SITE_B_SIGNER, "service") as site_b:
            with pytest.raises(StorefrontClientError) as as_site_a:
                await site_b.notify_capacity_released("reservation-a", site_id="site-a")
            with pytest.raises(StorefrontClientError) as as_itself:
                await site_b.notify_capacity_released("reservation-a", site_id="site-b")
        async with _client(app, SITE_SIGNER, "service") as site_a:
            released = await site_a.notify_capacity_released("reservation-a", site_id="site-a")

    assert as_site_a.value.status_code == 403
    assert as_itself.value.status_code == 404
    assert "belongs to another site" in str(as_itself.value)
    assert released == {"capacity_reservation_id": "reservation-a", "state": "released"}


async def test_a_recorded_release_is_a_stage_event_and_a_refused_one_is_not(
    tmp_path,
) -> None:
    runtime, negotiation_id, _capacity = await _runtime(tmp_path)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
        async with _client(app, SITE_SIGNER, "service") as site:
            with pytest.raises(StorefrontClientError):
                await site.notify_capacity_released("reservation-x", site_id="site-a")
            await site.notify_capacity_released("reservation-a", site_id="site-a")
        async with _client(app, ADMIN_SIGNER, "admin") as admin:
            events = await admin.get_events(stage="fulfillment")

    released = [event for event in events.events if event.event == "capacity_released"]
    assert len(released) == 1, events.events
    assert released[0].data["capacity_reservation_id"] == "reservation-a"
    assert released[0].data["negotiation_id"] == negotiation_id
    assert released[0].data["site_id"] == "site-a"
