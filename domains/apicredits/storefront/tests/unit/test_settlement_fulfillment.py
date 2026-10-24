"""Settlement: issuance fulfillment and shared-runtime composition."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_alkahest import RECIPIENT_RELEASE
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from market_core import SettlementEvidence
from market_identity import Ed25519Signer

from arkhai_api.issuance import IssuanceRequest, issuance_result_model
from arkhai_api_client import AuthorityError
from arkhai_api_selling.evidence_store import (
    IssuanceEvidenceRepository,
    IssuanceEvidenceService,
    PrivateResultRepository,
)
from arkhai_api_selling.issuance import (
    MissingQuotaResource,
    delivery,
    fulfill,
    issuance_subject,
    project_progress,
)
from arkhai_api_selling.settlement_composition import (
    fulfill_settlement,
    persist_settlement_outcome,
    prepare_settlement,
    reserve_settlement,
)
from arkhai_apicredits.label import API_CREDITS_LABEL
from apicredits_storefront.container import SELLING_CONTRIBUTIONS
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.utils.migrations import _migrate_issuance_evidence
from tests.integration.credit_negotiation import FakeCapacity
from tests.listing_bindings import upsert_bound_listing

IssuanceResult = issuance_result_model(API_CREDITS_LABEL)
_BUYER_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_OFFER = {
    "kind": "api_credits.v1",
    "service_name": "Acme Inference",
    "base_url": "https://api.acme.example",
    "resource_id": "svc-quota",
    "capacity_site_id": "tokens",
    "offering_mode": "api_credits",
}


def _evidence(reference="neg-purchase", *, quantity=3, mechanism="opaque.future.v1", status="verified", offer=None):
    return SettlementEvidence(
        reference, mechanism, reference, status,
        {"kind": "api_credits.settlement-evidence.v1", "schema_version": 1,
         "agreement_digest": "a" * 64, "source": {"verified_source": "fixture", "funding_expiration_unix": 1_800_000_000, "obligation_ref": "accepted-obligation"},
         "delivery": {"owner": _BUYER_PRINCIPAL.model_dump(mode="json"),
                      "listing_resource": dict(_OFFER if offer is None else offer),
                      "quantity": quantity, "key_mode": "new", "key_id": None, "listing_id": "L-tok"}},
    )


class _FakeAuthority:
    """The family client as a stage sees it, scripted per test."""

    def __init__(self, issue, rollback=None):
        self._issue = issue
        self._rollback = rollback

    async def submit_issuance(self, request):
        return await self._issue(request)

    async def rollback_issuance(self, **kwargs):
        return await self._rollback(**kwargs)


def _issuance_result(
    request: IssuanceRequest,
    *,
    secret: str | None = "ak_new.s3cret",
    already_issued: bool = False,
) -> IssuanceResult:
    return IssuanceResult(
        fulfillment_id=request.fulfillment_id,
        grant_id=request.fulfillment_id,
        negotiation_id=request.negotiation_id,
        owner=request.owner,
        service=request.service,
        resource_id=request.resource_id,
        quantity=request.quantity,
        key_mode=request.key.mode,
        key_id=request.key.key_id or "ak_new",
        balance=request.quantity,
        request_digest=request.request_digest,
        committed_at_unix=1_790_000_000,
        capacity_reservation_id=request.capacity_reservation_id,
        already_issued=already_issued,
        secret=secret,
    )


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


def _private_results(tmp_path):
    db_path = tmp_path / "hosted-private-results.db"
    with sqlite3.connect(db_path) as connection:
        _migrate_issuance_evidence(connection)
    return PrivateResultRepository(db_path, SELLING_CONTRIBUTIONS)


# ---------------------------------------------------------------------------
# API-credit issuance through the selling library
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chain_error", "rolled_back"),
    [("execution reverted", True), ("rpc down", False)],
)
async def test_an_attestation_failure_rolls_back_only_when_nothing_reached_the_chain(
    tmp_path, chain_error, rolled_back,
):
    """A reverted submission created no attestation; an unexplained failure may
    have been mined, so the grant stands for an operator to reconcile."""
    from apicredits_storefront import settlement_stages
    from market_identity import TrustedIdentitySet

    async def fake_issue(request):
        return _issuance_result(request, secret="ak_new.secret")

    rollbacks = []
    async def fake_rollback(**kwargs):
        rollbacks.append(kwargs)
        return {"rolled_back": True}
    async def fake_submit(*args):
        raise RuntimeError(chain_error)
    authority = _FakeAuthority(fake_issue, fake_rollback)
    signer = Ed25519Signer(bytes.fromhex("22"*32))
    path = tmp_path / "evidence.db"
    with sqlite3.connect(path) as connection:
        _migrate_issuance_evidence(connection)
    evidence_service = IssuanceEvidenceService(
        IssuanceEvidenceRepository(path, SELLING_CONTRIBUTIONS),
        contributions=SELLING_CONTRIBUTIONS, signer=signer,
        trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
        clock=lambda: 2_000_000_000,
    )
    events, stage_event = _events()
    evidence = _evidence("neg-chain", mechanism="alkahest.v1")
    result = await fulfill(
        SELLING_CONTRIBUTIONS, evidence=evidence, credits_client=authority, stage_event=stage_event,
    )
    composition = SimpleNamespace(
        local_principal=signer.identity, evidence_service=evidence_service, credits_client=authority,
        contributions=SELLING_CONTRIBUTIONS,
    )
    result = await settlement_stages.AlkahestSellerStage(
        fulfils_through_capacity=True, release_models=frozenset({RECIPIENT_RELEASE})
    ).continue_delivery(
        result, evidence=evidence, client=SimpleNamespace(string_obligation=SimpleNamespace(do_obligation=fake_submit)),
        composition=composition,
    )
    assert result["status"] == "error"
    assert [e[1] for e in events] == ["credits_issued", "fulfilled"]
    if rolled_back:
        assert rollbacks[0]["settlement_ref"] == "neg-chain" and rollbacks[0]["key_mode"] == "new"
        assert "grant_unknown" not in result
    else:
        assert rollbacks == []
        assert result["grant_unknown"] is True and "operator" in result["message"]


async def test_the_fulfillment_hook_issues_under_this_storefronts_bundle(monkeypatch):
    from apicredits_storefront.services import fulfillment_service

    captured = {}

    async def fake_fulfill(contributions, **kwargs):
        captured.update(kwargs, contributions=contributions)
        return {"status": "fulfilled", "fulfillment_uid": "fulfill-1"}

    monkeypatch.setattr(fulfillment_service, "fulfill_from_hold", fake_fulfill)
    db = SimpleNamespace()
    result = await fulfillment_service.fulfill_credit_obligation(
        evidence=_evidence("neg-payment"), db=db, credits_client="client",
    )

    assert result["status"] == "fulfilled"
    assert captured["contributions"] is SELLING_CONTRIBUTIONS
    assert (captured["db"], captured["credits_client"]) == (db, "client")
    accepted = delivery(SELLING_CONTRIBUTIONS, captured["evidence"])
    assert accepted.listing_resource["service_name"] == _OFFER["service_name"]
    assert accepted.listing_resource["resource_id"] == _OFFER["resource_id"]


def test_the_api_credit_projection_names_its_service_quota_and_endpoint():
    subject = issuance_subject(SELLING_CONTRIBUTIONS, _OFFER)
    assert (subject.service, subject.resource_id, subject.endpoint) == (
        "Acme Inference", "svc-quota", "https://api.acme.example",
    )
    without_quota = {key: value for key, value in _OFFER.items() if key != "resource_id"}
    with pytest.raises(MissingQuotaResource, match="names no quota resource"):
        issuance_subject(SELLING_CONTRIBUTIONS, without_quota, listing_id="L-tok")


async def test_fulfillment_service_rejects_invalid_domain_listing():
    from apicredits_storefront.services import fulfillment_service

    class _NoIssuance:
        async def submit_issuance(self, _request):
            raise AssertionError("issuance should not be called")

    with pytest.raises(ValueError, match="a service and a quota resource"):
        await fulfillment_service.fulfill_credit_obligation(
            evidence=_evidence("neg-invalid", offer={**_OFFER, "service_name": " "}),
            db=SimpleNamespace(), credits_client=_NoIssuance(),
        )


async def test_the_failure_policy_dispatches_this_storefronts_configured_actions_in_order(
    monkeypatch,
):
    from apicredits_storefront.services import fulfillment_service

    events, stage_event = _events()
    monkeypatch.setattr(fulfillment_service, "stage_event", stage_event)
    monkeypatch.setattr(
        fulfillment_service,
        "_configured_failure_actions",
        lambda: ("emit_event", "webhook"),
    )
    monkeypatch.setattr(fulfillment_service, "_failure_webhook_target", lambda: ("", 5.0))

    result = await fulfillment_service.build_api_credit_failure_policy().apply(
        object(),
        {
            "settlement_ref": "payment-failed",
            "negotiation_id": "neg-failed",
            "state": None,
            "reopened_listing_ids": [],
        },
    )

    assert [action["status"] for action in result.actions] == ["succeeded", "skipped"]
    assert [(stage, event) for stage, event, _ in events] == [("fulfillment", "failed")]
    assert result.context["state"] is None


async def test_payment_refusal_releases_hold_using_negotiation_not_transaction(
    tmp_path, monkeypatch,
):
    from apicredits_storefront import container
    from apicredits_storefront.services import fulfillment_service
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

    db = SQLiteClient(str(tmp_path / "failure.db"))
    now = datetime.now().isoformat()
    await upsert_bound_listing(
        db,
        listing_id="L-tok", status="closed", closed_by="seller", created_at=now,
        updated_at=now, listing_resource=dict(_OFFER), fulfillment_resource=None, max_duration_seconds=None,
        storefront_url="http://seller:8002", seller_principal=_SELLER_PRINCIPAL,
    )
    await db.save_capacity_hold(
        negotiation_id="neg-refused", listing_id="L-tok",
        capacity_reservation_id="alloc-refused",
        payload={"capacity_reservation_id": "alloc-refused", "resource_id": "svc-quota"},
    )
    capacity = SimpleNamespace(
        release=AsyncMock(return_value={
            "capacity_reservation_id": "alloc-refused", "resource_id": "svc-quota",
        }),
        availability=AsyncMock(return_value={"svc-quota": 100}),
    )
    reopen = AsyncMock(return_value=["L-tok"])
    events, stage_event = _events()
    monkeypatch.setattr(fulfillment_service, "build_capacity_runtime", lambda _factory: capacity)
    monkeypatch.setattr(fulfillment_service, "reopen_token_listings_after_capacity_change", reopen)
    monkeypatch.setattr(fulfillment_service, "get_sqlite_client", lambda: db)
    monkeypatch.setattr(fulfillment_service, "stage_event", stage_event)
    monkeypatch.setattr(fulfillment_service, "_configured_failure_actions", lambda: ("release_capacity", "emit_event"))
    monkeypatch.setattr(container, "resolved_failure_policy", fulfillment_service.build_api_credit_failure_policy())
    credits = SimpleNamespace(submit_issuance=AsyncMock(
        side_effect=AuthorityError("quota_exhausted", "no units", status_code=409),
    ))

    result = await fulfillment_service.fulfill_credit_obligation(
        evidence=replace(_evidence("neg-refused"), settlement_ref="payment-transaction"),
        db=db, credits_client=credits,
    )

    assert result["status"] == "error"
    release_args = capacity.release.await_args
    assert release_args.kwargs["capacity_reservation_id"] == "alloc-refused"
    assert release_args.kwargs["deal_ref"] == {"negotiation_id": "neg-refused"}
    assert release_args.kwargs["failure_reason"] == "quota_exhausted"
    assert await db.load_capacity_hold(negotiation_id="neg-refused") is None
    reopen.assert_awaited_once()
    failure = next(fields for stage, event, fields in events if stage == "fulfillment" and event == "failed")
    assert failure["settlement_ref"] == "payment-transaction"
    assert failure["negotiation_id"] == "neg-refused"
    assert result["settlement_ref"] == "payment-transaction"


# ---------------------------------------------------------------------------
# Settlement coordinator — exact obligation + credentials channel
# ---------------------------------------------------------------------------


@pytest.fixture
async def settled_db(tmp_path, monkeypatch):
    """A DB with an accepted token negotiation, via the real sync flow."""
    import market_policy.negotiation_thread as thread_module
    from apicredits_storefront import negotiation_runtime as negotiation_module
    from apicredits_storefront.domain_runtime import get_market_domain_contract
    from apicredits_storefront.utils import config as config_module
    from apicredits_storefront.utils.sqlite_client import SQLiteClient
    from market_core.schemas import EscrowProposal, ProvisionTerms
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    class _Capacity:
        def site(self, site_id):
            return FakeCapacity().site(site_id)

        async def snapshot(self):
            return [{"resource_id": "svc-quota", "available_units": 100}]

        async def reserve(self, **kwargs):
            return None  # no hold; issuance reserves fresh

    monkeypatch.setattr(
        negotiation_module,
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
    condition = {
        "chain_name": "anvil",
        "arbiter": "0x" + "33" * 20,
        "demand_data": {"recipient": "0x" + "22" * 20},
    }
    await upsert_bound_listing(
        client,
        listing_id="L-tok",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource=dict(_OFFER),
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": escrow_addr,
                "literal_fields": {"token": token},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        # The address book's recipient arbiter paying the seller wallet.
        demands=[condition],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://seller:8002",
        seller_principal=_SELLER_PRINCIPAL,
    )
    response = await negotiation_module.build_api_credit_negotiation_runtime(
        get_market_domain_contract()
    ).start(
        repository=client,
        listing_id="L-tok",
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address=escrow_addr,
            fields={"token": token, "amount": 300},
            literal_fields={"token": token},
            rates=[{"field": "amount", "per": "token", "value": "100"}],
            demand=condition,
            expiration_unix=1_800_000_000,
        ),
        terms=ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={"quantity": 3, "key": {"mode": "new"}},
        ),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=_BUYER_PRINCIPAL,
    )
    assert response["action"] == "accept"
    assert response.get("settlement_plan"), response
    return client, response["negotiation_id"]


def _build_settlement_composition(db, *, on_outcome=None, credits_client=None):
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
    from apicredits_storefront.domain_runtime import get_market_domain_contract
    from market_identity import TrustedIdentitySet
    signer = Ed25519Signer(bytes.fromhex("22"*32))
    composition = SimpleNamespace(
        domain=get_market_domain_contract(), local_principal=signer.identity,
        credits_client=credits_client, contributions=SELLING_CONTRIBUTIONS,
        evidence_service=IssuanceEvidenceService(
            IssuanceEvidenceRepository(db.db_path, SELLING_CONTRIBUTIONS),
            contributions=SELLING_CONTRIBUTIONS, signer=signer,
            trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
            clock=lambda: 2_000_000_000,
        ),
    )
    async def persist(prepared, outcome):
        await persist_settlement_outcome(db, prepared, outcome)
        if on_outcome is not None:
            on_outcome()
    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=partial(
            prepare_settlement,
            SELLER_STAGES,
            sqlite_client=db,
            local_principal=_SELLER_PRINCIPAL,
            composition=composition,
        ),
        reserve_start=partial(
            reserve_settlement,
            db,
            settlement_runtime=runtime,
            wake_servicing=worker.wake,
        ),
        fulfill=partial(fulfill_settlement, SELLER_STAGES),
        persist_outcome=persist,
        wake_servicing=worker.wake,
    )
    return runtime, worker, coordinator


async def test_settlement_coordinator_verifies_issues_and_stores_credentials(settled_db, monkeypatch):
    db, neg_id = settled_db
    from apicredits_storefront import settlement_stages
    verified = []
    issued = []

    async def verify(**kwargs):
        verified.append(kwargs)
        return 0

    async def issue(request):
        issued.append(request)
        return _issuance_result(request)

    attested = []
    async def attest(payload, escrow_uid):
        attested.append((json.loads(payload), escrow_uid))
        return "0xfulfill"
    monkeypatch.setattr(settlement_stages, "verify_escrow_for_settlement", verify)
    client = SimpleNamespace(string_obligation=SimpleNamespace(do_obligation=attest))
    completed = asyncio.Event()
    runtime, worker, coordinator = _build_settlement_composition(
        db, on_outcome=completed.set, credits_client=_FakeAuthority(issue),
    )
    result = await coordinator.start(
        escrow_uid="0xdeal", negotiation_id=neg_id, mechanism_client=client, chain_name="anvil",
        request=_settlement_request(neg_id),
    )
    assert result["status"] == "provisioning"
    await asyncio.wait_for(completed.wait(), timeout=5)
    progress = await db.load_issuance_progress(reference="0xdeal")
    assert progress["status"] == "ready"
    projection = await project_progress(SELLING_CONTRIBUTIONS, db, progress, owner=_BUYER_PRINCIPAL)
    assert projection["tenant_credentials"]["secret"] == "ak_new.s3cret"
    assert len(verified) == 1
    assert int(verified[0]["agreed_price"]) == 300
    assert all(call["escrow_uid"] == "0xdeal" for call in verified)
    assert issued[0].negotiation_id == neg_id
    escrow = await db.load_escrow(escrow_uid="0xdeal")
    assert escrow["tenant_credentials"] is None
    assert "s3cret" not in json.dumps(progress)
    evidence = await db.load_settlement_evidence(negotiation_id=neg_id)
    assert evidence.status == "verified"
    assert "s3cret" not in json.dumps(evidence.to_dict())
    assert attested[0][0]["body"]["fulfillment_id"] == issued[0].fulfillment_id

    status = await runtime.get_status(neg_id)
    assert status.obligations[0].fulfillment_ref == "0xfulfill"
    assert await worker.run_once() == 1
    serviced = await runtime.get_status(neg_id)
    assert serviced.obligations[0].collection_state == "succeeded"

    again = await coordinator.start(
        escrow_uid="0xdeal", negotiation_id=neg_id, mechanism_client=client, chain_name="anvil",
        request=_settlement_request(neg_id),
    )
    assert again["status"] == "ready"
    assert len(issued) == 1


async def test_a_listing_changed_after_acceptance_issues_what_the_buyer_accepted(settled_db, monkeypatch):
    """The service and accepted escrows change in place under the same quota
    resource, which the source check cannot see; the escrow is verified and
    issuance runs against the listing the buyer accepted."""
    db, neg_id = settled_db
    from apicredits_storefront import settlement_stages

    verified = []

    async def verify(**kwargs):
        verified.append(kwargs)
        return 0

    issued = []

    async def issue(request):
        issued.append(request)
        return _issuance_result(request)

    async def attest(_payload, _escrow_uid):
        return "0xfulfill"

    monkeypatch.setattr(settlement_stages, "verify_escrow_for_settlement", verify)
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    listing = await db.load_listing(listing_id=thread["our_listing_id"])
    stored = listing["listing_resource"]
    resource = json.loads(stored) if isinstance(stored, str) else dict(stored)
    accepted_escrows = listing["accepted_escrows"]
    await db.update_listing(
        listing_id=thread["our_listing_id"],
        listing_resource={**resource, "service_name": "Another Service", "base_url": "https://other.example"},
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "99" * 20}],
    )
    completed = asyncio.Event()
    _runtime, _worker, coordinator = _build_settlement_composition(
        db, on_outcome=completed.set, credits_client=_FakeAuthority(issue),
    )

    await coordinator.start(
        escrow_uid="0xdeal", negotiation_id=neg_id,
        mechanism_client=SimpleNamespace(string_obligation=SimpleNamespace(do_obligation=attest)),
        chain_name="anvil", request=_settlement_request(neg_id),
    )
    await asyncio.wait_for(completed.wait(), timeout=5)

    assert verified[0]["listing"]["accepted_escrows"] == (
        json.loads(accepted_escrows) if isinstance(accepted_escrows, str) else accepted_escrows
    )
    assert (issued[0].service, issued[0].resource_id) == (resource["service_name"], resource["resource_id"])
    progress = await db.load_issuance_progress(reference="0xdeal")
    assert json.loads(progress["public_result"]["connection_details"])["service_name"] == resource["service_name"]


async def test_an_agreement_naming_another_listing_than_its_thread_is_refused(settled_db, monkeypatch):
    db, neg_id = settled_db
    from apicredits_storefront import settlement_stages
    from market_core.schemas import Agreement

    async def verify(**_kwargs):
        return 0

    issued = []

    async def issue(request):
        issued.append(request)
        return _issuance_result(request)

    monkeypatch.setattr(settlement_stages, "verify_escrow_for_settlement", verify)
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    raw = thread["agreement_bytes"]
    agreement = Agreement.model_validate_json(raw.tobytes() if isinstance(raw, memoryview) else raw)
    elsewhere = agreement.model_copy(update={"listing_id": "listing-elsewhere"})
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE negotiation_threads SET agreement_bytes = ? WHERE negotiation_id = ?",
            (elsewhere.model_dump_json(exclude_none=True).encode(), neg_id),
        )
    _runtime, _worker, coordinator = _build_settlement_composition(db, credits_client=_FakeAuthority(issue))

    with pytest.raises(ValueError, match="listing differs from negotiation"):
        await coordinator.start(
            escrow_uid="0xdeal", negotiation_id=neg_id, mechanism_client=object(),
            chain_name="anvil", request=_settlement_request(neg_id),
        )
    assert issued == []
    assert await db.load_settlement_evidence(negotiation_id=neg_id) is None
    assert await db.load_escrow(escrow_uid="0xdeal") is None


async def test_verified_prepare_delivers_when_further_chain_reads_are_unavailable(
    settled_db, monkeypatch,
):
    db, neg_id = settled_db
    from apicredits_storefront import settlement_stages

    chain_reads = []
    issued = []

    async def verify(**kwargs):
        chain_reads.append(kwargs)
        if len(chain_reads) > 1:
            raise ConnectionError("chain transport unavailable after verification")
        return 0

    async def issue(request):
        issued.append(request)
        return _issuance_result(request)

    async def attest(_payload, _escrow_uid):
        return "0xfulfill"

    monkeypatch.setattr(settlement_stages, "verify_escrow_for_settlement", verify)
    completed = asyncio.Event()
    _, _, coordinator = _build_settlement_composition(
        db, on_outcome=completed.set, credits_client=_FakeAuthority(issue),
    )
    await coordinator.start(
        escrow_uid="0xverified", negotiation_id=neg_id,
        mechanism_client=SimpleNamespace(string_obligation=SimpleNamespace(do_obligation=attest)),
        chain_name="anvil", request=_settlement_request(neg_id),
    )
    await asyncio.wait_for(completed.wait(), timeout=5)

    assert (await db.load_issuance_progress(reference="0xverified"))["status"] == "ready"
    assert (await db.load_escrow(escrow_uid="0xverified"))["status"] == "ready"
    assert (await db.load_settlement_evidence(negotiation_id=neg_id)).status == "verified"
    assert len(issued) == 1
    assert len(chain_reads) == 1


async def test_ready_progress_recovers_into_shared_servicing(
    settled_db,
    monkeypatch,
):
    db, neg_id = settled_db
    from apicredits_storefront import settlement_stages as escrow_verification

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

    await db.save_issuance_progress(
        negotiation_id=neg_id, public_ref="0xlegacy-ready", status="ready",
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
    from apicredits_storefront import settlement_stages as escrow_verification
    from market_alkahest.escrow_verification import EscrowVerificationError

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


def test_a_stored_listing_row_is_projected_before_the_domain_validates_it():
    """A stored row carries bookkeeping columns the domain listing forbids; the
    selling library narrows it to the listing schema, and the raw row stays refused."""
    from arkhai_api_selling.quota_listing import domain_listing
    from arkhai_apicredits.domain_runtime import _normalize_listing
    from arkhai_apicredits.schema import ApiCreditsListing
    from pydantic import ValidationError

    resource = {
        "service_name": "weather-api",
        "resource_id": "weather-quota",
        "price_per_token": "1",
        "token": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
        "chain": "anvil",
        "base_url": "http://sample-app:8085",
        "capacity_site_id": "default",
    }
    row = {
        "kind": "api_credits.v1",
        "listing_resource": json.dumps(resource),
        "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0x1111"}],
        "settlement_options": [],
        "demands": [],
        "listing_id": "d6f4e4dc-06de-4a2f-a4df-b2f1bf64abab",
        "agent_url": "http://credits-storefront:8000/",
        "oracle_address": None,
        "paused": False,
        "publication_clauses": None,
        "seller_principal": {"scheme": "eip191", "identifier": "0x90f7"},
        "status": "open",
        "registry_status": "published",
        "created_at": "2026-09-14T00:00:00+00:00",
        "updated_at": "2026-09-14T00:00:00+00:00",
        "max_duration_seconds": 3600,
    }

    with pytest.raises(ValidationError):
        _normalize_listing(row)

    projected = domain_listing(SELLING_CONTRIBUTIONS, row)
    assert set(projected) <= set(ApiCreditsListing.model_fields)

    listing = _normalize_listing(projected)
    assert listing.listing_resource.service_name == "weather-api"
    assert listing.listing_resource.resource_id == "weather-quota"
    assert listing.accepted_escrows == row["accepted_escrows"]


async def test_a_stage_without_seller_refunds_refuses_the_route_and_skips_the_action():
    from apicredits_storefront.settlement_stages import AlkahestSellerStage, SettlementRefusal

    stage = AlkahestSellerStage(
        fulfils_through_capacity=True, release_models=frozenset({RECIPIENT_RELEASE})
    )
    with pytest.raises(SettlementRefusal) as refused:
        await stage.refund(db=None, composition=None, negotiation_id="neg-alkahest")
    assert refused.value.status_code == 409
    skipped = await stage.refund_before_delivery(db=None, composition=None, negotiation_id="neg-alkahest")
    assert skipped == {"action": "refund", "status": "skipped", "reason": "refund_not_supported"}
