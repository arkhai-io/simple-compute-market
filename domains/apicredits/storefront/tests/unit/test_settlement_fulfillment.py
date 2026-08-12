"""Settlement: issuance fulfillment and shared-runtime composition."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from functools import partial
from types import SimpleNamespace

import pytest

from domains.apicredits.settlement import fulfillment as fulfillment_module
from domains.apicredits.settlement.credits_client import (
    CreditsServiceClient,
    CreditsServiceError,
)
from domains.apicredits.settlement.fulfillment import fulfill_api_credits_obligation
from market_core import ImmutableFulfillmentCapability
from market_identity import Ed25519Signer
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest

_BUYER_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_OFFER = {
    "kind": "api_credits.v1",
    "service_name": "Acme Inference",
    "base_url": "https://api.acme.example",
    "resource_id": "svc-quota",
}


def _settlement_request(negotiation_id: str) -> ApiCreditsSettleRequest:
    return ApiCreditsSettleRequest(
        negotiation_id=negotiation_id,
        buyer_principal=_BUYER_PRINCIPAL,
        buyer_evm_address="0x" + "33" * 20,
        chain_name="anvil",
    )


def _events():
    recorded = []

    def stage_event(stage, event, **fields):
        recorded.append((stage, event, fields))

    return recorded, stage_event


# ---------------------------------------------------------------------------
# fulfill_api_credits_obligation
# ---------------------------------------------------------------------------


async def test_fulfillment_issues_and_returns_credentials_once(monkeypatch):
    issued = {}

    async def fake_issue(self, **kwargs):
        issued.update(kwargs)
        return {
            "key_id": "ak_new",
            "secret": "ak_new.s3cret",
            "quantity": kwargs["quantity"],
            "balance": 3,
            "capacity_reservation_id": kwargs.get("capacity_reservation_id"),
            "already_issued": False,
        }

    monkeypatch.setattr(CreditsServiceClient, "submit_credit_issuance", fake_issue)
    events, stage_event = _events()

    result = await fulfill_api_credits_obligation(
        client=None,  # simulated on-chain fulfillment
        escrow_uid="0xescrow1",
        offer_resource=_OFFER,
        quantity=3,
        buyer_principal=_BUYER_PRINCIPAL,
        listing_id="L-tok",
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
        held_reservation={
            "capacity_reservation_id": "alloc-7",
            "resource_id": "svc-quota",
        },
    )

    assert result["status"] == "fulfilled"
    assert result["tenant_credentials"]["secret"] == "ak_new.s3cret"
    assert result["tenant_credentials"]["key_id"] == "ak_new"
    # The on-chain payload is public: key id and quantity, never the secret.
    payload = json.loads(result["connection_details"])
    assert payload["key_id"] == "ak_new"
    assert payload["quantity"] == 3
    assert "secret" not in payload

    # The negotiation-time hold rode the issuance call.
    assert issued["capacity_reservation_id"] == "alloc-7"
    assert issued["escrow_uid"] == "0xescrow1"
    assert [e[1] for e in events] == ["credits_issued", "fulfilled"]


async def test_fulfillment_refusal_applies_failure_policy(monkeypatch):
    async def fake_issue(self, **kwargs):
        raise CreditsServiceError("quota_exhausted", "no units", status_code=409)

    monkeypatch.setattr(CreditsServiceClient, "submit_credit_issuance", fake_issue)
    events, stage_event = _events()
    policy_calls = []

    async def fake_policy(**kwargs):
        policy_calls.append(kwargs)

    result = await fulfill_api_credits_obligation(
        client=None,
        escrow_uid="0xescrow2",
        offer_resource=_OFFER,
        quantity=3,
        buyer_principal=_BUYER_PRINCIPAL,
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
        apply_failure_policy=fake_policy,
        held_reservation={"capacity_reservation_id": "alloc-8"},
    )
    assert result["status"] == "error"
    assert "quota_exhausted" in result["message"]
    assert policy_calls and policy_calls[0]["reason"] == "quota_exhausted"
    assert policy_calls[0]["capacity_reservation_id"] == "alloc-8"
    assert [e[1] for e in events] == ["failed"]


async def test_chain_failure_after_issuance_rolls_back(monkeypatch):
    async def fake_issue(self, **kwargs):
        return {"key_id": "ak_new", "secret": "s", "quantity": 3, "balance": 3}

    async def fake_submit(**kwargs):
        raise RuntimeError("rpc down")

    rollbacks = []

    async def fake_rollback(self, **kwargs):
        rollbacks.append(kwargs)
        return {"rolled_back": True}

    monkeypatch.setattr(CreditsServiceClient, "submit_credit_issuance", fake_issue)
    monkeypatch.setattr(fulfillment_module, "_submit_token_fulfillment", fake_submit)
    monkeypatch.setattr(CreditsServiceClient, "rollback_issuance", fake_rollback)
    events, stage_event = _events()

    result = await fulfill_api_credits_obligation(
        client=object(),
        escrow_uid="0xescrow3",
        offer_resource=_OFFER,
        quantity=3,
        buyer_principal=_BUYER_PRINCIPAL,
        key_mode="new",
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
    )
    assert result["status"] == "error"
    assert rollbacks and rollbacks[0]["escrow_uid"] == "0xescrow3"
    assert rollbacks[0]["key_mode"] == "new"
    assert [e[1] for e in events] == ["credits_issued", "failed_after_issuance"]


async def test_fulfillment_service_normalizes_order_through_domain_runtime(
    monkeypatch,
):
    from apicredits_storefront.services import fulfillment_service

    captured = {}

    async def fake_fulfill(**kwargs):
        captured.update(kwargs)
        return {"status": "fulfilled", "fulfillment_uid": "fulfill-1"}

    monkeypatch.setattr(
        fulfillment_service,
        "fulfill_api_credits_obligation",
        fake_fulfill,
    )

    result = await fulfillment_service.fulfill_credit_obligation(
        client=None,
        escrow_uid="0xescrow-runtime",
        order={"offer_resource": dict(_OFFER)},
        quantity=3,
        buyer_principal=_BUYER_PRINCIPAL,
    )

    assert result["status"] == "fulfilled"
    assert captured["offer_resource"]["kind"] == "api_credits.v1"
    assert captured["offer_resource"]["service_name"] == _OFFER["service_name"]
    assert captured["offer_resource"]["resource_id"] == _OFFER["resource_id"]


async def test_fulfillment_service_rejects_invalid_domain_listing(monkeypatch):
    from apicredits_storefront.services import fulfillment_service

    async def fake_fulfill(**kwargs):
        raise AssertionError("issuance should not be called")

    monkeypatch.setattr(
        fulfillment_service,
        "fulfill_api_credits_obligation",
        fake_fulfill,
    )

    with pytest.raises(ValueError, match="service_name"):
        await fulfillment_service.fulfill_credit_obligation(
            client=None,
            escrow_uid="0xescrow-invalid",
            order={
                "offer_resource": {
                    "kind": "api_credits.v1",
                    "service_name": " ",
                    "resource_id": "svc-quota",
                },
            },
            quantity=3,
            buyer_principal=_BUYER_PRINCIPAL,
        )


async def test_failure_policy_injects_ordered_quota_event_and_webhook_handlers(
    monkeypatch,
):
    from apicredits_storefront.services import fulfillment_service

    calls: list[str] = []

    async def release(_store, context):
        calls.append("release_capacity")
        context["state"] = "released"
        context["reopened_listing_ids"] = ["listing-1"]
        return {"status": "succeeded"}

    async def emit(_store, context):
        calls.append("emit_event")
        assert context["state"] is None
        return {"status": "succeeded"}

    async def webhook(_store, context):
        calls.append("webhook")
        assert context["reopened_listing_ids"] == []
        return {"status": "sent", "status_code": 204}

    monkeypatch.setattr(
        fulfillment_service,
        "_configured_failure_actions",
        lambda: ("release_capacity", "emit_event", "webhook"),
    )
    monkeypatch.setattr(
        fulfillment_service,
        "_release_capacity_handler",
        release,
    )
    monkeypatch.setattr(
        fulfillment_service,
        "_emit_failure_event_handler",
        emit,
    )
    monkeypatch.setattr(
        fulfillment_service,
        "_failure_webhook_handler",
        webhook,
    )

    result = await fulfillment_service.build_api_credit_failure_policy().apply(
        object(),
        {
            "escrow_uid": "0xfailed",
            "state": None,
            "reopened_listing_ids": [],
        },
    )

    assert calls == [
        "release_capacity",
        "emit_event",
        "webhook",
    ]
    assert [action["status"] for action in result.actions] == [
        "succeeded",
        "succeeded",
        "sent",
    ]
    assert result.context["state"] is None


# ---------------------------------------------------------------------------
# Settlement coordinator — exact obligation + credentials channel
# ---------------------------------------------------------------------------


@pytest.fixture
async def settled_db(tmp_path, monkeypatch):
    """A DB with an accepted token negotiation, via the real sync flow."""
    import market_policy.negotiation_thread as thread_module

    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.utils.sqlite_client import SQLiteClient
    from apicredits_storefront.utils.sync_negotiation import start_sync_negotiation
    from apicredits_storefront.utils import config as config_module
    from market_core.schemas import EscrowProposal, ProvisionTerms
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    class _Capacity:
        async def snapshot(self):
            return [{"resource_id": "svc-quota", "available_units": 100}]

        async def reserve(self, **kwargs):
            return None  # no hold; issuance reserves fresh

    monkeypatch.setattr(
        cc_module,
        "build_capacity_client",
        lambda factory: _Capacity(),
    )

    monkeypatch.setattr(
        config_module.settings.wallet,
        "address",
        "0x" + "22" * 20,
    )
    address_config = tmp_path / "alkahest-addresses.json"
    address_config.write_text(
        json.dumps(
            {
                "arbiters_addresses": {
                    "recipient_arbiter": "0x" + "33" * 20,
                }
            }
        )
    )
    monkeypatch.setitem(
        config_module.CHAINS,
        "anvil",
        SimpleNamespace(
            alkahest_address_config_path=str(address_config),
            rpc_url="http://x",
        ),
    )
    client = SQLiteClient(db_path=str(tmp_path / "settle.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8002"),
    )
    token = "0x" + "01" * 20
    escrow_addr = "0x" + "11" * 20
    await client.upsert_listing(
        listing_id="L-tok",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=dict(_OFFER),
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": escrow_addr,
                "literal_fields": {"token": token},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://seller:8002",
        seller_principal=_SELLER_PRINCIPAL,
    )
    response = await start_sync_negotiation(
        sqlite_client=client,
        our_listing_id="L-tok",
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address=escrow_addr,
            fields={"token": token, "amount": 300},
            literal_fields={"token": token},
            rates=[{"field": "amount", "per": "token", "value": "100"}],
            expiration_unix=1_800_000_000,
        ),
        provision_terms=ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={"quantity": 3, "key": {"mode": "new"}},
        ),
        our_base_url="http://seller:8002",
        their_agent_url="http://buyer:9000",
    )
    assert response["action"] == "accept"
    assert response.get("settlement_plan"), response
    return client, response["negotiation_id"]


def _build_settlement_composition(db):
    from apicredits_storefront.domain_runtime import (
        fulfill_api_credit_settlement,
        persist_api_credit_settlement_outcome,
        prepare_api_credit_settlement,
        reserve_api_credit_settlement,
    )
    from market_settlement_runtime import (
        ConditionOutcome,
        EffectOutcome,
        SettlementJobCoordinator,
        SettlementRuntime,
        SettlementServicingWorker,
        SettlementSQLiteRepository,
        StatusOutcome,
    )

    class ReadyEscrowClient:
        async def get_status(self, _obligation, **kwargs):
            return StatusOutcome(
                status="ready",
                mechanism_ref=kwargs["mechanism_ref"],
            )

        async def check(self, _obligation, **_kwargs):
            return ConditionOutcome(decision="ready")

        async def collect(self, _obligation, **_kwargs):
            return EffectOutcome(receipt={"tx": "collected"})

    repository = SettlementSQLiteRepository(db.db_path, apply_migrations=False)
    runtime = SettlementRuntime(
        repository,
        {"alkahest.v1": ReadyEscrowClient()},
    )
    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="api-credit-test",
        interval_seconds=30,
    )
    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=partial(
            prepare_api_credit_settlement,
            sqlite_client=db,
            local_principal=_SELLER_PRINCIPAL,
        ),
        reserve_start=partial(
            reserve_api_credit_settlement,
            db,
            settlement_runtime=runtime,
            wake_servicing=worker.wake,
        ),
        fulfill=fulfill_api_credit_settlement,
        persist_outcome=partial(persist_api_credit_settlement_outcome, db),
        wake_servicing=worker.wake,
    )
    return runtime, worker, coordinator


async def test_settlement_coordinator_verifies_issues_and_stores_credentials(
    settled_db,
    monkeypatch,
):
    db, neg_id = settled_db
    from apicredits_storefront import domain_runtime
    from core_storefront import escrow_verification

    verified = {}
    fulfillment_calls: list[dict] = []

    async def fake_verify(**kwargs):
        verified.update(kwargs)
        return 0

    async def fake_fulfill(**kwargs):
        fulfillment_calls.append(kwargs)
        return {
            "status": "fulfilled",
            "fulfillment_uid": "0xfulfill",
            "connection_details": json.dumps({"key_id": "ak_new"}),
            "tenant_credentials": {"key_id": "ak_new", "secret": "s3cret"},
        }

    monkeypatch.setattr(
        escrow_verification,
        "verify_escrow_for_settlement",
        fake_verify,
    )
    monkeypatch.setattr(
        domain_runtime,
        "APICREDITS_STOREFRONT_DOMAIN",
        replace(
            domain_runtime.APICREDITS_STOREFRONT_DOMAIN,
            fulfillment=ImmutableFulfillmentCapability(fulfill=fake_fulfill),
        ),
    )
    mechanism_client = object()
    runtime, worker, coordinator = _build_settlement_composition(db)

    result = await coordinator.start(
        escrow_uid="0xdeal",
        negotiation_id=neg_id,
        mechanism_client=mechanism_client,
        chain_name="anvil",
        request=_settlement_request(neg_id),
    )
    assert result["status"] == "provisioning"
    assert domain_runtime.serialize_api_credit_settlement_start(result) == {
        "escrow_uid": "0xdeal",
        "negotiation_id": neg_id,
        "status": "provisioning",
    }
    assert verified["escrow_uid"] == "0xdeal"
    assert int(verified["agreed_price"]) == 300
    assert verified["agreed_duration_seconds"] == 0

    for _ in range(50):
        job = await db.load_escrow(escrow_uid="0xdeal")
        if job and job.get("status") == "ready":
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "ready"
    assert json.loads(job["tenant_credentials"])["secret"] == "s3cret"
    assert job["obligation_index"] == 0
    assert job["obligation_ref"]
    serialized = domain_runtime.serialize_api_credit_settlement(job)
    assert serialized["tenant_credentials"]["secret"] == "s3cret"
    assert json.loads(serialized["connection_details"])["key_id"] == "ak_new"

    status = await runtime.get_status(neg_id)
    obligation = status.obligations[0]
    assert obligation.fulfillment_ref == "0xfulfill"

    processed = 0
    for _ in range(50):
        processed = await worker.run_once()
        if processed:
            break
        await asyncio.sleep(0.02)
    assert processed == 1
    serviced = await runtime.get_status(neg_id)
    assert serviced.obligations[0].collection_state == "succeeded"
    assert obligation.mechanism_ref == "0xdeal"
    assert "s3cret" not in json.dumps(obligation.model_dump(mode="json"))

    again = await coordinator.start(
        escrow_uid="0xdeal",
        negotiation_id=neg_id,
        mechanism_client=mechanism_client,
        chain_name="anvil",
        request=_settlement_request(neg_id),
    )
    assert again["status"] == "ready"
    assert len(fulfillment_calls) == 1


async def test_legacy_ready_row_recovers_into_shared_servicing(
    settled_db,
    monkeypatch,
):
    db, neg_id = settled_db
    from core_storefront import escrow_verification

    async def fake_verify(**_kwargs):
        return 0

    monkeypatch.setattr(
        escrow_verification,
        "verify_escrow_for_settlement",
        fake_verify,
    )
    assert await db.insert_escrow(
        escrow_uid="0xlegacy-ready",
        negotiation_id=neg_id,
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        status="provisioning",
    )
    await db.update_escrow(
        escrow_uid="0xlegacy-ready",
        status="ready",
        fulfillment_uid="0xlegacy-fulfillment",
    )

    runtime, worker, coordinator = _build_settlement_composition(db)
    result = await coordinator.start(
        escrow_uid="0xlegacy-ready",
        negotiation_id=neg_id,
        mechanism_client=object(),
        chain_name="anvil",
        request=_settlement_request(neg_id),
    )

    assert result["status"] == "ready"
    status = await runtime.get_status(neg_id)
    assert status.obligations[0].fulfillment_ref == "0xlegacy-fulfillment"
    assert await worker.run_once() == 1
    serviced = await runtime.get_status(neg_id)
    assert serviced.obligations[0].collection_state == "succeeded"


async def test_settlement_coordinator_fails_closed_on_bad_escrow(
    settled_db,
    monkeypatch,
):
    db, neg_id = settled_db
    from core_storefront import escrow_verification
    from core_storefront.escrow_verification import EscrowVerificationError

    async def fake_verify(**kwargs):
        raise EscrowVerificationError("amount mismatch")

    monkeypatch.setattr(
        escrow_verification,
        "verify_escrow_for_settlement",
        fake_verify,
    )
    _, _, coordinator = _build_settlement_composition(db)
    with pytest.raises(EscrowVerificationError):
        await coordinator.start(
            escrow_uid="0xbad",
            negotiation_id=neg_id,
            mechanism_client=object(),
            chain_name="anvil",
            request=_settlement_request(neg_id),
        )
    assert await db.load_escrow(escrow_uid="0xbad") is None
