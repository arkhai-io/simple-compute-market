"""Settlement: issuance fulfillment orchestration + the settle job flow."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from domains.apitokens.settlement import fulfillment as fulfillment_module
from domains.apitokens.settlement.fulfillment import fulfill_api_tokens_obligation
from domains.apitokens.settlement.issuance import TokensServiceError

_BUYER = "0xBuyerAAAA0000000000000000000000000000ab"
_OFFER = {
    "kind": "api_tokens.v1",
    "service_name": "Acme Inference",
    "base_url": "https://api.acme.example",
    "resource_id": "svc-quota",
}


def _events():
    recorded = []

    def stage_event(stage, event, **fields):
        recorded.append((stage, event, fields))

    return recorded, stage_event


# ---------------------------------------------------------------------------
# fulfill_api_tokens_obligation
# ---------------------------------------------------------------------------

async def test_fulfillment_issues_and_returns_credentials_once(monkeypatch):
    issued = {}

    async def fake_issue(**kwargs):
        issued.update(kwargs)
        return {
            "key_id": "ak_new", "secret": "ak_new.s3cret",
            "quantity": kwargs["quantity"], "balance": 3,
            "allocation_id": kwargs.get("allocation_id"),
            "already_issued": False,
        }

    monkeypatch.setattr(fulfillment_module, "submit_token_issuance", fake_issue)
    events, stage_event = _events()

    result = await fulfill_api_tokens_obligation(
        client=None,  # simulated on-chain fulfillment
        escrow_uid="0xescrow1",
        offer_resource=_OFFER,
        quantity=3,
        buyer_wallet=_BUYER,
        listing_id="L-tok",
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
        held_allocation={"allocation_id": "alloc-7", "resource_id": "svc-quota"},
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
    assert issued["allocation_id"] == "alloc-7"
    assert issued["escrow_uid"] == "0xescrow1"
    assert [e[1] for e in events] == ["tokens_issued", "fulfilled"]


async def test_fulfillment_refusal_applies_failure_policy(monkeypatch):
    async def fake_issue(**kwargs):
        raise TokensServiceError("quota_exhausted", "no units", status_code=409)

    monkeypatch.setattr(fulfillment_module, "submit_token_issuance", fake_issue)
    events, stage_event = _events()
    policy_calls = []

    async def fake_policy(**kwargs):
        policy_calls.append(kwargs)

    result = await fulfill_api_tokens_obligation(
        client=None,
        escrow_uid="0xescrow2",
        offer_resource=_OFFER,
        quantity=3,
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
        apply_failure_policy=fake_policy,
        held_allocation={"allocation_id": "alloc-8"},
    )
    assert result["status"] == "error"
    assert "quota_exhausted" in result["message"]
    assert policy_calls and policy_calls[0]["reason"] == "quota_exhausted"
    assert policy_calls[0]["allocation_id"] == "alloc-8"
    assert [e[1] for e in events] == ["failed"]


async def test_chain_failure_after_issuance_rolls_back(monkeypatch):
    async def fake_issue(**kwargs):
        return {"key_id": "ak_new", "secret": "s", "quantity": 3, "balance": 3}

    async def fake_submit(**kwargs):
        raise RuntimeError("rpc down")

    rollbacks = []

    async def fake_rollback(**kwargs):
        rollbacks.append(kwargs)
        return {"rolled_back": True}

    monkeypatch.setattr(fulfillment_module, "submit_token_issuance", fake_issue)
    monkeypatch.setattr(fulfillment_module, "_submit_token_fulfillment", fake_submit)
    monkeypatch.setattr(fulfillment_module, "rollback_issuance", fake_rollback)
    events, stage_event = _events()

    result = await fulfill_api_tokens_obligation(
        client=object(),
        escrow_uid="0xescrow3",
        offer_resource=_OFFER,
        quantity=3,
        key_mode="new",
        service_url="http://tokens:8082",
        admin_key="k",
        stage_event=stage_event,
    )
    assert result["status"] == "error"
    assert rollbacks and rollbacks[0]["escrow_uid"] == "0xescrow3"
    assert rollbacks[0]["key_mode"] == "new"
    assert [e[1] for e in events] == ["tokens_issued", "failed_after_issuance"]


# ---------------------------------------------------------------------------
# start_settlement_job — fail-closed verification + credentials channel
# ---------------------------------------------------------------------------

@pytest.fixture
async def settled_db(tmp_path, monkeypatch):
    """A DB with an accepted token negotiation, via the real sync flow."""
    import market_policy.negotiation_thread as thread_module

    from apitokens_storefront.services import capacity_client as cc_module
    from apitokens_storefront.utils.sqlite_client import SQLiteClient
    from apitokens_storefront.utils.sync_negotiation import start_sync_negotiation
    from market_core.schemas import EscrowProposal, ProvisionTerms
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    class _Capacity:
        async def snapshot(self):
            return [{"resource_id": "svc-quota", "available_units": 100}]

        async def reserve(self, **kwargs):
            return None  # no hold; issuance reserves fresh

    monkeypatch.setattr(
        cc_module, "build_capacity_client", lambda factory: _Capacity(),
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
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": escrow_addr,
            "literal_fields": {"token": token},
            "rates": [{"field": "amount", "per": "token", "value": "100"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=None,
        seller="http://seller:8002",
    )
    response = await start_sync_negotiation(
        sqlite_client=client,
        our_listing_id="L-tok",
        buyer_address=_BUYER,
        proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address=escrow_addr,
            fields={"token": token, "amount": 300},
            literal_fields={"token": token},
            rates=[{"field": "amount", "per": "token", "value": "100"}],
            expiration_unix=1_800_000_000,
        ),
        provision_terms=ProvisionTerms(
            kind="api_tokens.v1",
            payload={"quantity": 3, "key": {"mode": "new"}},
        ),
        our_base_url="http://seller:8002",
        their_agent_url=_BUYER,
    )
    assert response["action"] == "accept"
    return client, response["negotiation_id"]


async def test_settlement_job_verifies_issues_and_stores_credentials(
    settled_db, monkeypatch,
):
    db, neg_id = settled_db
    from apitokens_storefront.services import fulfillment_service
    from apitokens_storefront.utils import config as config_module
    from apitokens_storefront.utils import settlement_jobs

    verified = {}

    async def fake_verify(**kwargs):
        verified.update(kwargs)

    async def fake_fulfill(**kwargs):
        return {
            "status": "fulfilled",
            "fulfillment_uid": "0xfulfill",
            "connection_details": json.dumps({"key_id": "ak_new"}),
            "tenant_credentials": {"key_id": "ak_new", "secret": "s3cret"},
        }

    monkeypatch.setattr(settlement_jobs, "verify_escrow_for_settlement", fake_verify)
    monkeypatch.setattr(fulfillment_service, "fulfill_token_obligation", fake_fulfill)
    monkeypatch.setitem(
        config_module.CHAINS, "anvil",
        SimpleNamespace(alkahest_address_config_path=None, rpc_url="http://x"),
    )
    try:
        result = await settlement_jobs.start_settlement_job(
            escrow_uid="0xdeal",
            negotiation_id=neg_id,
            sqlite_client=db,
            alkahest_client=object(),
            chain_name="anvil",
        )
    finally:
        pass
    assert result["status"] == "provisioning"
    assert verified["escrow_uid"] == "0xdeal"
    assert int(verified["agreed_price"]) == 300

    # Background task lands the credentials on the job row.
    for _ in range(50):
        job = await db.load_escrow(escrow_uid="0xdeal")
        if job and job.get("status") == "ready":
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "ready"
    assert json.loads(job["tenant_credentials"])["secret"] == "s3cret"

    # The fulfilled deal is registered with the claims engine.
    claim = await db.load_claim("0xdeal")
    assert claim is not None
    assert claim["fulfillment_ref"] == "0xfulfill"

    # Idempotent: a second settle returns the existing row.
    again = await settlement_jobs.start_settlement_job(
        escrow_uid="0xdeal",
        negotiation_id=neg_id,
        sqlite_client=db,
        alkahest_client=object(),
        chain_name="anvil",
    )
    assert again["status"] == "ready"


async def test_settlement_job_fails_closed_on_bad_escrow(settled_db, monkeypatch):
    db, neg_id = settled_db
    from core_storefront.escrow_verification import EscrowVerificationError

    from apitokens_storefront.utils import config as config_module
    from apitokens_storefront.utils import settlement_jobs

    async def fake_verify(**kwargs):
        raise EscrowVerificationError("amount mismatch")

    monkeypatch.setattr(settlement_jobs, "verify_escrow_for_settlement", fake_verify)
    monkeypatch.setitem(
        config_module.CHAINS, "anvil",
        SimpleNamespace(alkahest_address_config_path=None, rpc_url="http://x"),
    )
    with pytest.raises(EscrowVerificationError):
        await settlement_jobs.start_settlement_job(
            escrow_uid="0xbad",
            negotiation_id=neg_id,
            sqlite_client=db,
            alkahest_client=object(),
            chain_name="anvil",
        )
    assert await db.load_escrow(escrow_uid="0xbad") is None
