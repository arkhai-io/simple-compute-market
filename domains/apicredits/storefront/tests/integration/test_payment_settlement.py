"""API-credit agreement settlement and refunds through the canonical typed client.

Routes, authentication and response-signing middleware, SQLite persistence, the
payment settlement service and the failure policy are real. The credits issuance
authority is a controlled fake, and the payments service is the kit's fake
injected at ``PaymentsClient`` through the seller stage.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentSellerStage, servicing_stage
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

import apicredits_storefront.container as _container
from apicredits_storefront.controllers.settle_controller import router, settlements_router
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.services.fulfillment_service import build_api_credit_failure_policy
from apicredits_storefront.services.payment_settlement_service import (
    ApiCreditPaymentSettlementService,
)
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(b"\x07" * 32)
IMPOSTOR = Ed25519Signer(b"\x08" * 32)
BUYER = Ed25519Signer(b"\x41" * 32)
SELLER = Ed25519Signer(b"\x42" * 32)
NEGOTIATION = "credits-payment-1"
LISTING = "credits-listing"


class Issuer:
    """Controlled credits authority: issues once, or fails through the failure policy."""

    def __init__(self, db) -> None:
        self.db = db
        self.issued: list[str] = []
        self.fail = False
        # When set, issuance pauses after starting until ``release`` is set.
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def fulfill(self, **request):
        if self.started is not None and self.release is not None:
            self.started.set()
            await self.release.wait()
        if self.fail:
            await build_api_credit_failure_policy().apply(
                self.db,
                {"escrow_uid": request["escrow_uid"], "reason": "issuance_refused"},
            )
            return {"status": "failed", "message": "issuance refused"}
        self.issued.append(request["negotiation_id"])
        return {
            "status": "fulfilled",
            "fulfillment_uid": "grant-1",
            "connection_details": "credits issued",
            "tenant_credentials": {"api_key": "k-1"},
        }


def _option() -> SettlementOption:
    params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": False}
    body = {"mechanism": "arkhai.payments.v1", "asset": "USD/2", "rates": [], "params": params}
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


async def _seed(db: SQLiteClient, stage: PaymentSellerStage):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    agreement = Agreement(
        negotiation_id=NEGOTIATION,
        listing_id=LISTING,
        listing_hash="0" * 64,
        buyer=BUYER.identity.model_dump(mode="json"),
        seller=SELLER.identity.model_dump(mode="json"),
        settlement=_option(),
        settlement_params={"payer_account": PAYER},
        amount=300,
        asset="USD/2",
        duration_seconds=0,
        start_utc=now,
        accepted_at=now,
        provision_terms={"kind": "api_credits.v1", "version": 1, "payload": {"quantity": 3}},
    )
    raw = agreement.model_dump_json(exclude_none=True).encode()
    data = stage.settlement_data(json.loads(raw))
    await db.upsert_listing(
        listing_id=LISTING,
        status="open",
        created_at=now,
        updated_at=now,
        listing_resource={"service": "sample", "unit": "credit"},
        accepted_escrows=[],
        fulfillment_resource=None,
        max_duration_seconds=None,
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
    )
    await db.commit_agreed_terms(
        negotiation_id=NEGOTIATION,
        agreed_price=300,
        agreed_duration_seconds=0,
        agreement_bytes=raw,
        accepted_at=now,
        agreed_start_utc=now,
        settlement_data=data.to_wire(),
    )
    await db.update_negotiation_thread_terminal(negotiation_id=NEGOTIATION, terminal_state="success")
    await db.save_credit_terms(negotiation_id=NEGOTIATION, quantity=3, key_mode="new")
    return data


@pytest.fixture
async def harness(tmp_path):
    async def build(*, actions=("emit_event",), enabled=True):
        db = SQLiteClient(db_path=str(tmp_path / "credits.db"))
        payments = FakePaymentsClient()
        config = ArkhaiPaymentsConfig(
            enabled=enabled,
            service_url="http://127.0.0.1:9",
            service_identity=SERVICE.identity,
            fee_bps=250,
            dispute_authority=DISPUTE,
            development_auth=True,
        )
        stage = servicing_stage(config, client_for_owner=payments)
        data = await _seed(db, stage)
        issuer = Issuer(db)
        composition = SimpleNamespace(domain=SimpleNamespace(fulfillment=issuer))
        composition.payment_service = lambda store: ApiCreditPaymentSettlementService(
            db=store, composition=composition, stage=stage
        )
        _container.resolved_sqlite_client = db
        _container.resolved_marketplace_signer = SELLER
        _container.resolved_settlement_composition = composition
        app = FastAPI()
        app.include_router(router)
        app.include_router(settlements_router)
        app.middleware("http")(authenticate_response)
        transport = httpx.ASGITransport(app=app)
        publishers = TrustedIdentitySet(identities=(SELLER.identity,))
        built = SimpleNamespace(
            db=db,
            data=data,
            payments=payments,
            issuer=issuer,
            buyer=StorefrontClient("http://test", signer=BUYER, caller_role="buyer",
                                   expected_publishers=publishers, transport=transport),
            seller=StorefrontClient("http://test", signer=SELLER, caller_role="seller",
                                    expected_publishers=publishers, transport=transport),
        )
        built.serve = lambda signer=SERVICE: payments.serve(
            build_signed_receipt(signer=signer, mandate=data.mandate)
        )
        built.actions = list(actions)
        made.append(built)
        return built

    made: list = []
    with settings_overrides(
        **{
            "identity.scheme": "ed25519",
            "identity.identifier": SELLER.identity.identifier,
        }
    ):
        yield build
    for built in made:
        await built.buyer.close()
        await built.seller.close()
    _container.resolved_sqlite_client = None
    _container.resolved_marketplace_signer = None
    _container.resolved_settlement_composition = None


async def _status_code(call) -> int:
    with pytest.raises(StorefrontClientError) as exc:
        await call()
    return exc.value.status_code


async def test_a_verified_receipt_issues_credits_once(harness):
    h = await harness()
    pending = await h.buyer.settle_agreement(NEGOTIATION)
    assert pending.pending and pending.retryable
    assert h.issuer.issued == []
    assert await h.db.load_escrow(escrow_uid=NEGOTIATION) is None

    h.serve()
    ready = await h.buyer.settle_agreement(NEGOTIATION)
    assert ready.status == "ready"
    assert ready.settlement_ref == h.data.transaction_id
    await h.buyer.settle_agreement(NEGOTIATION)
    assert h.issuer.issued == [NEGOTIATION]


async def test_an_impostor_receipt_is_refused_without_a_grant(harness):
    h = await harness()
    h.serve(signer=IMPOSTOR)
    assert await _status_code(lambda: h.buyer.settle_agreement(NEGOTIATION)) == 409
    assert h.issuer.issued == []


async def test_a_refund_before_issuance_blocks_later_settlement(harness):
    h = await harness()
    h.serve()
    refunded = await h.seller.refund_settlement(NEGOTIATION)
    assert refunded.status == "refunded"
    assert (await h.buyer.settle_agreement(NEGOTIATION)).status == "refunded"
    assert h.issuer.issued == []


async def test_a_failed_issuance_keeps_the_payment_unless_refund_is_enabled(harness):
    h = await harness()
    h.issuer.fail = True
    h.serve()
    with settings_overrides(**{"fulfillment.failure_policy.actions": ["emit_event"]}):
        failed = await h.buyer.settle_agreement(NEGOTIATION)
    assert failed.status == "failed"
    assert h.payments.count("reverse") == 0


async def test_the_refund_action_reverses_a_failed_issuance(harness):
    h = await harness()
    h.issuer.fail = True
    h.serve()
    with settings_overrides(**{"fulfillment.failure_policy.actions": ["emit_event", "refund"]}):
        result = await h.buyer.settle_agreement(NEGOTIATION)
    assert result.status == "refunded"
    assert h.payments.count("reverse") == 1


async def test_an_accepted_deal_issues_and_refunds_after_payments_is_disabled(harness):
    h = await harness(enabled=False)
    h.serve()
    assert (await h.buyer.settle_agreement(NEGOTIATION)).status == "ready"
    assert (await h.seller.refund_settlement(NEGOTIATION)).status == "refunded"


async def test_a_refund_recorded_before_issuance_start_stops_issuance(harness):
    h = await harness()
    gate = asyncio.Event()
    claim = h.db.claim_delivery_start

    async def gated_claim(**kwargs):
        await gate.wait()
        return await claim(**kwargs)

    h.db.claim_delivery_start = gated_claim
    h.serve()
    settling = asyncio.create_task(h.buyer.settle_agreement(NEGOTIATION))
    await asyncio.sleep(0.05)
    assert (await h.seller.refund_settlement(NEGOTIATION)).status == "refunded"
    gate.set()
    assert (await settling).status == "refunded"
    assert h.issuer.issued == []


async def test_a_refund_after_issuance_start_records_both(harness):
    h = await harness()
    h.issuer.started, h.issuer.release = asyncio.Event(), asyncio.Event()
    h.serve()
    settling = asyncio.create_task(h.buyer.settle_agreement(NEGOTIATION))
    await h.issuer.started.wait()
    assert (await h.seller.refund_settlement(NEGOTIATION)).status == "refunded"
    h.issuer.release.set()
    assert (await settling).status == "refunded"
    escrow = await h.db.load_escrow(escrow_uid=NEGOTIATION)
    assert h.issuer.issued == [NEGOTIATION]
    assert escrow["status"] == "refunded" and escrow["fulfillment_uid"] == "grant-1"


def _restart(tmp_path, h, *, approved: bool):
    """A fresh composition over the same SQLite file, as after a process restart."""
    db = SQLiteClient(db_path=str(tmp_path / "credits.db"))
    payments = FakePaymentsClient()
    if approved:
        payments.serve(build_signed_receipt(signer=SERVICE, mandate=h.data.mandate))
    config = ArkhaiPaymentsConfig(
        enabled=True,
        service_url="http://127.0.0.1:9",
        service_identity=SERVICE.identity,
        fee_bps=250,
        dispute_authority=DISPUTE,
        development_auth=True,
    )
    stage = servicing_stage(config, client_for_owner=payments)
    issuer = Issuer(db)
    composition = SimpleNamespace(domain=SimpleNamespace(fulfillment=issuer))
    composition.payment_service = lambda store: ApiCreditPaymentSettlementService(
        db=store, composition=composition, stage=stage
    )
    _container.resolved_sqlite_client = db
    _container.resolved_settlement_composition = composition
    return SimpleNamespace(db=db, issuer=issuer)


async def test_an_approved_payment_converges_after_restart_without_the_buyer(harness, tmp_path):
    """The buyer approved, never settled, and the storefront restarted: the seller issues credits."""
    from apicredits_storefront.lifecycle_steps import payment_reconciliation_step

    h = await harness()
    restarted = _restart(tmp_path, h, approved=True)

    # The registered step: what the timer loop and an operator's step run.
    done = await payment_reconciliation_step()

    assert (done["attempted"], done["failed"]) == (1, 0)
    assert restarted.issuer.issued == [NEGOTIATION]
    escrow = await restarted.db.load_escrow(escrow_uid=NEGOTIATION)
    assert escrow["status"] == "ready"

    again = await payment_reconciliation_step()
    assert again["attempted"] == 0
    assert restarted.issuer.issued == [NEGOTIATION]


async def test_reconciliation_leaves_an_unapproved_payment_pending(harness, tmp_path):
    from apicredits_storefront.lifecycle_steps import payment_reconciliation_step

    h = await harness()
    restarted = _restart(tmp_path, h, approved=False)

    done = await payment_reconciliation_step()

    assert (done["attempted"], done["failed"]) == (1, 0)
    assert restarted.issuer.issued == []
    assert await restarted.db.load_escrow(escrow_uid=NEGOTIATION) is None

def _clone_row(db_path: str, table: str, source: str, new_id: str, **columns) -> None:
    """Copy one negotiation-keyed row under a new negotiation ID, overriding columns."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS temp.clone")
        conn.execute(f"CREATE TEMP TABLE clone AS SELECT * FROM {table} WHERE negotiation_id = ?", (source,))
        assignments = ", ".join(f"{name} = ?" for name in ("negotiation_id", *columns))
        conn.execute(f"UPDATE clone SET {assignments}", (new_id, *columns.values()))
        conn.execute(f"INSERT INTO {table} SELECT * FROM clone")
        conn.commit()
    finally:
        conn.close()


async def test_completed_deals_never_crowd_out_an_unsettled_one(harness):
    """More completed payment deals than the pass limit still leave room for the stranded one."""
    h = await harness()
    for index in range(3):
        completed = f"completed-{index}"
        _clone_row(
            h.db.db_path, "negotiation_threads", NEGOTIATION, completed,
            created_at=f"2000-01-01T00:00:0{index}",
        )
        await h.db.insert_escrow(
            escrow_uid=completed, negotiation_id=completed, chain_name=None,
            escrow_address=None, is_primary=True, status="ready",
        )
    h.serve()

    service = _container.resolved_settlement_composition.payment_service(h.db)
    done = await service.reconcile_once(limit=1)

    assert (done.attempted, done.failed) == (1, 0)
    assert h.issuer.issued == [NEGOTIATION]


async def test_a_malformed_agreement_never_stops_reconciliation(harness):
    """One corrupt accepted thread is skipped; the stranded deal still converges."""
    h = await harness()
    _clone_row(
        h.db.db_path, "negotiation_threads", NEGOTIATION, "corrupt",
        created_at="2000-01-01T00:00:00", agreement_bytes=b"{not json",
    )
    h.serve()

    service = _container.resolved_settlement_composition.payment_service(h.db)
    done = await service.reconcile_once(limit=1)

    assert (done.attempted, done.failed) == (1, 0)
    assert h.issuer.issued == [NEGOTIATION]
