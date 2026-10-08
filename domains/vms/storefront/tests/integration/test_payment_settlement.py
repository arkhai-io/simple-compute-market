"""Agreement settlement and seller refunds through the canonical typed client.

The storefront app, its authentication middleware, SQLite persistence, and the
domain registry are real. The payments service is replaced at ``PaymentsClient``,
the code that wraps it, by the kit's fake; receipts come from the kit's
vector-pinned fixture. VM delivery is a controlled domain hook so each test can
observe exactly whether delivery started.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from arkhai_vms import make_vm_provision_terms
from core_storefront.domain_registry import StorefrontThreadBinding
from fastapi import FastAPI
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    PaymentSellerStage,
    PaymentSettlementData,
    servicing_stage,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_core import ImmutableFulfillmentCapability
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import router, settlements_router
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.failure_actions import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.payment_settlement import VmPaymentsCoordinator
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(b"\x07" * 32)
IMPOSTOR = Ed25519Signer(b"\x08" * 32)
BUYER = Ed25519Signer(b"\x21" * 32)
SELLER = Ed25519Signer(b"\x22" * 32)
NEGOTIATION = "payment-neg-1"
LISTING = "vm-payment-listing"


class Delivery:
    """Controlled VM delivery that records every start and can fail before delivering."""

    def __init__(self) -> None:
        self.starts: list[str] = []
        self.fail = False
        # When set, delivery pauses after starting until ``release`` is set.
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def __call__(self, *, context):
        self.starts.append(context.negotiation_id)
        if self.started is not None and self.release is not None:
            self.started.set()
            await self.release.wait()
        result = {
            "negotiation_id": context.negotiation_id,
            "escrow_uid": context.escrow_uid,
            "site_id": context.site_id,
        }
        if self.fail:
            # The production VM hook applies the failure policy itself when
            # provisioning fails; this hook does the same.
            await apply_fulfillment_failure_policy(
                context.ports.repository,
                FulfillmentFailureContext(
                    escrow_uid=context.escrow_uid,
                    reason="provisioning_failed",
                    message="controlled failure",
                    source="settlement_provisioning",
                ),
            )
            return result | {"state": "failed", "failure_reason": "provisioning_failed"}
        return result | {
            "state": "fulfilled",
            "fulfillment_id": "vm-fulfillment-1",
            "domain_result": {"connection_details": "controlled VM"},
        }


def _config(**overrides) -> ArkhaiPaymentsConfig:
    values = {
        "enabled": True,
        "service_url": "http://127.0.0.1:9",
        "service_identity": SERVICE.identity,
        "fee_bps": 250,
        "dispute_authority": DISPUTE,
        "development_auth": True,
    }
    values.update(overrides)
    return ArkhaiPaymentsConfig(**values)


def _option(*, deposit: bool) -> SettlementOption:
    params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": deposit}
    body = {"mechanism": "arkhai.payments.v1", "asset": "USD/2", "rates": [], "params": params}
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


async def _seed(db: SQLiteClient, stage: PaymentSellerStage, *, deposit: bool):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    provision = make_vm_provision_terms(
        duration_seconds=3600, ssh_public_key="ssh-ed25519 test"
    ).model_dump(mode="json")
    agreement = Agreement(
        negotiation_id=NEGOTIATION,
        listing_id=LISTING,
        listing_hash="0" * 64,
        buyer=BUYER.identity.model_dump(mode="json"),
        seller=SELLER.identity.model_dump(mode="json"),
        settlement=_option(deposit=deposit),
        settlement_params={"payer_account": PAYER},
        amount=100,
        asset="USD/2",
        duration_seconds=3600,
        start_utc=now,
        accepted_at=now,
        provision_terms=provision,
    )
    raw = agreement.model_dump_json(exclude_none=True).encode()
    data = stage.settlement_data(json.loads(raw))
    binding = prepare_vm_listing_binding(
        listing_id=LISTING,
        candidate={
            "capacity_backing": "backed",
            "site_id": "site-test",
            "pool_id": "pool-test",
            "resource_id": "resource-test",
            "listing_shape": {"gpu": {"count": 1, "model": "H200"}},
        },
    )
    await db.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at=now,
        updated_at=now,
        listing_resource={"gpu_model": "H200", "gpu_count": 1, "offering_mode": "vm"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://test",
        seller_principal=SELLER.identity,
    )
    await db.create_negotiation_thread(
        negotiation_id=NEGOTIATION,
        our_listing_id=LISTING,
        their_listing_id="",
        our_agent_id="seller",
        their_agent_id="buyer",
        buyer_principal=BUYER.identity,
        seller_principal=SELLER.identity,
        owner_id="seller",
        requested_duration_seconds=3600,
        provision_terms=provision,
        binding=StorefrontThreadBinding(
            negotiation_id=NEGOTIATION,
            listing_id=LISTING,
            site_id="site-test",
            binding=binding.binding,
        ),
    )
    await db.commit_agreed_terms(
        negotiation_id=NEGOTIATION,
        agreed_price=100,
        agreed_duration_seconds=3600,
        agreement_bytes=raw,
        accepted_at=now,
        agreed_start_utc=now,
        settlement_data=data.to_wire(),
    )
    await db.update_negotiation_thread_terminal(
        negotiation_id=NEGOTIATION, terminal_state="success"
    )
    return data


def _client(signer, role, transport):
    return StorefrontClient(
        "http://test",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=transport,
    )


class Harness(SimpleNamespace):
    async def settle(self):
        return await self.buyer.settle_agreement(NEGOTIATION)

    async def refund(self):
        return await self.seller.refund_settlement(NEGOTIATION)

    async def delivered(self):
        task = self.coordinator.tasks.get(NEGOTIATION)
        if task is not None:
            await task

    def serve(self, signer=SERVICE, data: PaymentSettlementData | None = None):
        mandate = (data or self.data).mandate
        self.payments.serve(build_signed_receipt(signer=signer, mandate=mandate))


async def _harness(tmp_path, *, deposit=False, actions=("emit_event",)):
    delivery = Delivery()
    domain = replace(
        build_vm_storefront_domain(),
        fulfillment=ImmutableFulfillmentCapability(fulfill=delivery),
    )
    registry = build_vm_storefront_registry(domain)
    db = SQLiteClient(str(tmp_path / "storefront.db"), registry=registry)
    payments = FakePaymentsClient()
    stage = PaymentSellerStage(_config(), client_for_owner=payments)
    data = await _seed(db, stage, deposit=deposit)
    coordinator = VmPaymentsCoordinator(domain=domain, db=db, stage=stage)
    _container.resolved_sqlite_client = db
    _container.resolved_domain_registry = registry
    _container.resolved_marketplace_signer = SELLER
    _container.resolved_settlement_composition = SimpleNamespace(
        payments_coordinator=coordinator,
        local_principal=SELLER.identity,
        arkhai_payments_stage=stage,
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(settlements_router)
    app.middleware("http")(listing_lifecycle_middleware)
    transport = httpx.ASGITransport(app=app)
    return Harness(
        db=db,
        payments=payments,
        data=data,
        delivery=delivery,
        coordinator=coordinator,
        actions=list(actions),
        transport=transport,
        buyer=_client(BUYER, "buyer", transport),
        seller=_client(SELLER, "seller", transport),
    )


@pytest_asyncio.fixture
async def make(tmp_path):
    made = []

    async def build(**kwargs):
        harness = await _harness(tmp_path, **kwargs)
        made.append(harness)
        overrides = settings_overrides(**{"fulfillment.failure_policy.actions": harness.actions})
        overrides.__enter__()
        harness.overrides = overrides
        return harness

    yield build
    for harness in made:
        await harness.coordinator.stop()
        await harness.buyer.close()
        await harness.seller.close()
        harness.overrides.__exit__(None, None, None)
    _container.resolved_sqlite_client = None
    _container.resolved_domain_registry = None
    _container.resolved_marketplace_signer = None
    _container.resolved_settlement_composition = None


async def _status_code(call) -> int:
    with pytest.raises(StorefrontClientError) as exc:
        await call()
    return exc.value.status_code


@pytest.mark.asyncio
async def test_settlement_is_pending_until_a_verified_receipt_then_delivers_once(make):
    h = await make()
    pending = await h.settle()
    assert pending.pending and pending.retryable
    assert pending.settlement_ref == h.data.transaction_id
    assert pending.escrow_uid == NEGOTIATION
    assert h.delivery.starts == []

    h.serve()
    started = await h.settle()
    assert started.status == "provisioning"
    await h.delivered()
    repeated = await h.settle()
    assert repeated.status == "ready"
    assert h.delivery.starts == [NEGOTIATION]


@pytest.mark.asyncio
async def test_an_impostor_receipt_is_refused_without_delivery_or_state(make):
    h = await make()
    h.serve(signer=IMPOSTOR)
    assert await _status_code(h.settle) == 409
    assert h.delivery.starts == []
    assert await h.db.load_vm_payment_record(negotiation_id=NEGOTIATION) is None


@pytest.mark.asyncio
async def test_a_receipt_for_another_mandate_is_refused(make):
    h = await make()
    other_terms = json.loads(
        (await h.db.load_negotiation_thread_row(negotiation_id=NEGOTIATION))["agreement_bytes"]
    )
    other_terms["amount"] = "999"
    h.serve(data=PaymentSettlementData.for_agreement(other_terms, _config()))
    assert await _status_code(h.settle) == 409
    assert h.delivery.starts == []


@pytest.mark.asyncio
async def test_an_unreachable_payments_service_is_retryable(make):
    h = await make()
    h.payments.unavailable = True
    assert await _status_code(h.settle) == 503
    assert h.delivery.starts == []


@pytest.mark.asyncio
async def test_an_advertised_deposit_happens_before_delivery(make):
    h = await make(deposit=True)
    h.serve()
    h.payments.attach_unavailable = True
    assert await _status_code(h.settle) == 503
    assert h.delivery.starts == []

    h.payments.attach_unavailable = False
    await h.settle()
    await h.delivered()
    assert len(h.payments.attachments) == 1
    assert h.delivery.starts == [NEGOTIATION]


@pytest.mark.asyncio
async def test_a_refund_before_delivery_blocks_later_settlement(make):
    h = await make()
    h.serve()
    refunded = await h.refund()
    assert refunded.status == "refunded"
    assert refunded.settlement_ref == h.data.transaction_id
    assert (await h.settle()).status == "refunded"
    assert h.delivery.starts == []


@pytest.mark.asyncio
async def test_a_repeated_refund_reverses_once(make):
    h = await make()
    h.serve()
    await h.refund()
    await h.refund()
    assert h.payments.count("reverse") == 1


@pytest.mark.asyncio
async def test_refund_outcomes_without_held_funds_are_conflicts(make):
    h = await make()
    assert await _status_code(h.refund) == 409
    h.serve()
    h.payments.reverse_error = "hold_matured"
    assert await _status_code(h.refund) == 409


@pytest.mark.asyncio
async def test_a_buyer_cannot_refund(make):
    h = await make()
    h.serve()
    buyer_as_seller = StorefrontClient(
        "http://test",
        signer=BUYER,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity, BUYER.identity)),
        transport=h.transport,
    )
    try:
        with pytest.raises(StorefrontClientError):
            await buyer_as_seller.refund_settlement(NEGOTIATION)
    finally:
        await buyer_as_seller.close()
    assert h.payments.count("reverse") == 0


@pytest.mark.asyncio
async def test_the_refund_failure_action_reverses_a_failed_payment_deal(make):
    h = await make(actions=("emit_event", "refund"))
    h.delivery.fail = True
    h.serve()
    await h.settle()
    await h.delivered()
    assert h.payments.count("reverse") == 1
    escrow = await h.db.load_escrow(escrow_uid=NEGOTIATION)
    # The provisioning task's own failed write must not overwrite the refund.
    assert escrow["status"] == "refunded"


@pytest.mark.asyncio
async def test_without_the_refund_action_a_failed_deal_keeps_its_payment(make):
    h = await make()
    h.delivery.fail = True
    h.serve()
    await h.settle()
    await h.delivered()
    assert h.payments.count("reverse") == 0
    assert (await h.db.load_escrow(escrow_uid=NEGOTIATION))["status"] == "failed"


# --- Accepted deals outlive configuration changes -----------------------------


def _replace_stage(h, config: ArkhaiPaymentsConfig) -> None:
    stage = servicing_stage(config, client_for_owner=h.payments)
    h.coordinator.stage = stage
    _container.resolved_settlement_composition.arkhai_payments_stage = stage


@pytest.mark.asyncio
async def test_an_accepted_deal_settles_after_fee_and_dispute_policy_change(make):
    h = await make()
    _replace_stage(h, _config(fee_bps=0, dispute_authority=PAYER))
    h.serve()
    started = await h.settle()
    assert started.settlement_ref == h.data.transaction_id
    await h.delivered()
    assert h.delivery.starts == [NEGOTIATION]


@pytest.mark.asyncio
async def test_an_accepted_deal_settles_and_refunds_after_payments_is_disabled(make):
    h = await make()
    _replace_stage(h, _config(enabled=False))
    h.serve()
    await h.settle()
    await h.delivered()
    assert h.delivery.starts == [NEGOTIATION]
    assert (await h.refund()).status == "refunded"


# --- Refund and delivery start are totally ordered ----------------------------


@pytest.mark.asyncio
async def test_a_refund_recorded_before_delivery_start_stops_delivery(make):
    h = await make()
    gate = asyncio.Event()
    claim = h.db.claim_delivery_start

    async def gated_claim(**kwargs):
        await gate.wait()
        return await claim(**kwargs)

    h.db.claim_delivery_start = gated_claim
    h.serve()
    await h.settle()
    assert (await h.refund()).status == "refunded"
    gate.set()
    await h.delivered()
    assert h.delivery.starts == []
    assert (await h.db.load_escrow(escrow_uid=NEGOTIATION))["status"] == "refunded"


@pytest.mark.asyncio
async def test_a_refund_after_delivery_start_records_both(make):
    h = await make()
    h.delivery.started, h.delivery.release = asyncio.Event(), asyncio.Event()
    h.serve()
    await h.settle()
    await h.delivery.started.wait()
    assert (await h.refund()).status == "refunded"
    h.delivery.release.set()
    await h.delivered()
    escrow = await h.db.load_escrow(escrow_uid=NEGOTIATION)
    assert h.delivery.starts == [NEGOTIATION]
    assert escrow["status"] == "refunded"
    assert escrow["fulfillment_uid"] == "vm-fulfillment-1"


@pytest.mark.asyncio
async def test_an_interrupted_refund_completes_on_the_next_call(make):
    h = await make()
    h.serve()
    # State left by a crash after the service reversed but before the local write.
    await h.db.record_refund_intent(escrow_uid=NEGOTIATION, negotiation_id=NEGOTIATION)
    h.payments.reversed = True
    h.payments.reverse_error = "hold_not_reversible"
    assert (await h.refund()).status == "refunded"
    assert (await h.db.load_escrow(escrow_uid=NEGOTIATION))["status"] == "refunded"


@pytest.mark.asyncio
async def test_an_operator_fault_is_a_server_error_not_a_retryable_outage(make):
    h = await make()
    h.payments.read_error = (401, "authentication_required")
    assert await _status_code(h.settle) == 500
    assert h.delivery.starts == []
