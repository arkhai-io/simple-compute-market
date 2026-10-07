"""Bare-metal agreement settlement and refunds through the canonical typed client.

The storefront app, its lifespan and authentication, and SQLite persistence are
real. Site capacity and provisioning are in-memory authorities, and the payments
service is the kit's fake injected at ``PaymentsClient`` through the settlement
composition. Settlement must start fulfillment itself once the receipt verifies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from arkhai_bare_metal import BareMetalListing, BareMetalMessage, BareMetalTerms
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(b"\x07" * 32)
IMPOSTOR = Ed25519Signer(b"\x08" * 32)
BUYER = Ed25519Signer(b"\x31" * 32)
SELLER = Ed25519Signer(b"\x32" * 32)
ADMIN = Ed25519Signer(b"\x33" * 32)
NEGOTIATION = "bm-payment-1"
LISTING = "bm-payment-listing"
SITE = "site-pay"


class Capacity:
    def __init__(self) -> None:
        self.reservation_sites: dict[str, str] = {}

    def site(self, site_id):
        assert site_id == SITE
        return self

    async def list_reservations(self):
        return []

    async def reserve(self, **request):
        self.reservation_sites["reservation-pay"] = request["site"]
        return {"capacity_reservation_id": "reservation-pay", "site": request["site"]}


class Provisioning:
    def __init__(self) -> None:
        self.begin_calls: list = []

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id="resource-pay",
            pool_id="pool-pay",
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "machine_id": "machine-pay",
                    "physical_host_id": "host-pay",
                }
            },
        )

    async def begin_fulfillment(self, request):
        self.begin_calls.append(request)
        return SimpleNamespace(
            fulfillment_id="fulfillment-pay",
            capacity_reservation_id="reservation-pay",
            state="dispatch_pending",
        )


def _option() -> SettlementOption:
    params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": False}
    body = {"mechanism": "arkhai.payments.v1", "asset": "USD/2", "rates": [], "params": params}
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def _composition(payments: FakePaymentsClient) -> BareMetalStorefrontSettlementComposition:
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "priority": ["arkhai.payments.v1"],
            "arkhai_payments": {
                "enabled": True,
                "service_url": "http://127.0.0.1:9",
                "service_identity": SERVICE.identity.model_dump(mode="json"),
                "fee_bps": 250,
                "dispute_authority": DISPUTE,
                "development_auth": True,
            },
        },
        payments_client_for_owner=payments,
    )


async def _seed(runtime: BareMetalStorefrontRuntime):
    stage = runtime.settlement_composition.arkhai_payments_stage()
    terms = BareMetalTerms(
        machine_id="machine-pay",
        physical_host_id="host-pay",
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 pay",
        listing_ref=LISTING,
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    agreement = Agreement(
        negotiation_id=NEGOTIATION,
        listing_id=LISTING,
        listing_hash="0" * 64,
        buyer=BUYER.identity.model_dump(mode="json"),
        seller=SELLER.identity.model_dump(mode="json"),
        settlement=_option(),
        settlement_params={"payer_account": PAYER},
        amount=100,
        asset="USD/2",
        duration_seconds=3600,
        start_utc=now,
        accepted_at=now,
        provision_terms=terms.model_dump(mode="json"),
    )
    raw = agreement.model_dump_json(exclude_none=True).encode()
    data = stage.settlement_data(json.loads(raw))
    await runtime.db.upsert_bare_metal_listing(
        listing_id=LISTING,
        status="open",
        created_at=now,
        updated_at=now,
        seller_principal=SELLER.identity,
        storefront_url="http://test",
        listing=BareMetalListing(
            machine_id="machine-pay", physical_host_id="host-pay", capabilities={"gpu_model": "H200"}
        ),
        accepted_escrows=[],
        settlement_options=[agreement.settlement.model_dump(mode="json")],
        site_id=SITE,
        pool_id="pool-pay",
        physical_resource_id="physical-pay",
    )
    await runtime.db.persist_bare_metal_opening(
        negotiation_id=NEGOTIATION,
        listing_id=LISTING,
        seller_principal=SELLER.identity,
        buyer_agent_id="buyer",
        buyer_principal=BUYER.identity,
        seller_reference_amount=100,
        strategy="test",
        message=BareMetalMessage(duration_seconds=3600, ssh_public_key="ssh-ed25519 pay"),
        proposal={},
        buyer_amount=100,
        seller_action="accept",
        seller_amount=100,
        terms=terms,
        agreed_amount=100,
        agreement_bytes=raw,
        accepted_at=now,
        settlement_data=data.to_wire(),
        settlement_mechanism="arkhai.payments.v1",
    )
    return data


class Harness(SimpleNamespace):
    def serve(self, signer=SERVICE):
        self.payments.serve(build_signed_receipt(signer=signer, mandate=self.data.mandate))

    async def settle(self):
        return await self.buyer.settle_agreement(NEGOTIATION)

    async def refund(self):
        return await self.seller.refund_settlement(NEGOTIATION)


@pytest.fixture
async def harness(tmp_path):
    payments = FakePaymentsClient()
    domain = get_market_domain_contract()
    provisioning = Provisioning()
    runtime = BareMetalStorefrontRuntime(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=SELLER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN.identity,)),
        storefront_url="http://test",
        marketplace_signer=SELLER,
        settlement_composition=_composition(payments),
        capacity_client=Capacity(),
        fulfillment_client=provisioning,
    )
    data = await _seed(runtime)
    app = build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=domain), runtime=runtime
    )
    publishers = TrustedIdentitySet(identities=(SELLER.identity,))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            StorefrontClient(
                "http://test", signer=BUYER, caller_role="buyer",
                expected_publishers=publishers, transport=transport,
            ) as buyer,
            StorefrontClient(
                "http://test", signer=SELLER, caller_role="seller",
                expected_publishers=publishers, transport=transport,
            ) as seller,
        ):
            yield Harness(
                runtime=runtime,
                payments=payments,
                provisioning=provisioning,
                data=data,
                buyer=buyer,
                seller=seller,
            )


async def _status_code(call) -> int:
    with pytest.raises(StorefrontClientError) as exc:
        await call()
    return exc.value.status_code


@pytest.mark.asyncio
async def test_a_verified_receipt_starts_fulfillment_once(harness):
    pending = await harness.settle()
    assert pending.pending and pending.retryable
    assert harness.provisioning.begin_calls == []

    harness.serve()
    started = await harness.settle()
    assert not started.pending
    assert started.settlement_ref == harness.data.transaction_id
    assert started.escrow_uid == NEGOTIATION
    await harness.settle()
    assert len(harness.provisioning.begin_calls) == 1


@pytest.mark.asyncio
async def test_an_impostor_receipt_is_refused_without_fulfillment(harness):
    harness.serve(signer=IMPOSTOR)
    assert await _status_code(harness.settle) == 409
    assert harness.provisioning.begin_calls == []
    record = await harness.runtime.db.load_bare_metal_settlement_record(
        negotiation_id=NEGOTIATION
    )
    assert record["status"] == "accepted"


@pytest.mark.asyncio
async def test_a_refund_before_delivery_blocks_fulfillment(harness):
    harness.serve()
    refunded = await harness.refund()
    assert refunded.status == "refunded"
    assert (await harness.settle()).status == "refunded"
    assert harness.provisioning.begin_calls == []
    assert harness.payments.count("reverse") == 1
