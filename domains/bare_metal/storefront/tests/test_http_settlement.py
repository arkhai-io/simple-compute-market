from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import json
import sqlite3
import time
import uuid
import copy

from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from arkhai_bare_metal_storefront.models import BareMetalSettleRequest
from arkhai_bare_metal_storefront.fulfillment_service import BareMetalFulfillmentError
from market_identity import Ed25519Signer
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)

import httpx
import pytest
from fastapi.testclient import TestClient
from storefront_client import StorefrontClient, StorefrontClientError
from storefront_client.models import SettleResponse, SettleStatusResponse
from market_core.schemas import Agreement, EscrowProposal, SettlementPlan
from market_core import VersionedEnvelope
from arkhai_bare_metal_storefront.settlement_stages import legacy_alkahest_option
from datetime import datetime, timezone
from market_settlement_runtime import derive_obligation_ref
from market_identity import (
    EMPTY_BODY,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)

from arkhai_bare_metal import BareMetalMessage, BareMetalTerms
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from loopback import serving
from seeded_threads import seed_thread
from settlement_compositions import ChainClient, EscrowOnChain, alkahest_composition


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )


PRIVATE_KEY = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
BUYER_SIGNER = Eip191Signer(PRIVATE_KEY)
BUYER = BUYER_SIGNER.identity.identifier
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
SITE_SIGNER = Eip191Signer(bytes.fromhex("44" * 32))
ESCROW_ADDRESS = "0x1111111111111111111111111111111111111111"
ESCROW_UID = "0x" + "ab" * 32
OTHER_ESCROW_UID = "0x" + "cd" * 32
TOKEN = "0x2222222222222222222222222222222222222222"


def _buyer(app) -> StorefrontClient:
    """The canonical storefront client, as the buyer, over the in-process app."""
    return StorefrontClient(
        "http://seller",
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


def _settled(response: SettleResponse | SettleStatusResponse) -> dict:
    """A typed settle or status response as the wire object it was read from."""
    return {
        "escrow_uid": response.escrow_uid,
        "status": response.status,
        "buyer_principal": response.buyer_principal.model_dump(mode="json"),
        "seller_principal": response.seller_principal.model_dump(mode="json"),
        **response.extra,
    }


def _settle_body(negotiation_id: str) -> dict:
    return {
        "negotiation_id": negotiation_id,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_evm_address": BUYER,
    }


def _headers(
    operation: str,
    resource_id: str,
    body: dict | None = None,
    *,
    method: str = "POST",
) -> dict[str, str]:
    timestamp = int(time.time())
    signed = sign_request(
        signer=BUYER_SIGNER,
        envelope=RequestEnvelope(
            role="buyer",
            principal=BUYER_SIGNER.identity,
            method=method,
            operation=operation,
            resource=resource_id,
            request_id=f"test-{uuid.uuid4().hex}",
            timestamp=timestamp,
            body_hash=canonical_body_hash(EMPTY_BODY if body is None else body),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }


def _plan(**kwargs):
    expiration_unix = (
        kwargs["proposal"]["expiration_unix"]
        if isinstance(kwargs["proposal"], dict)
        else kwargs["proposal"].expiration_unix
    )
    return {
        "settlement_plan": {
            "buyer_principal": kwargs["buyer_principal"].model_dump(mode="json"),
            "seller_principal": kwargs["seller_principal"].model_dump(mode="json"),
            "obligations": [
                {
                    "payer": "seller",
                    "claimant": "buyer",
                    "amount": 25,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "payer_principal": kwargs["seller_principal"].model_dump(
                        mode="json"
                    ),
                    "claimant_principal": kwargs["buyer_principal"].model_dump(
                        mode="json"
                    ),
                    "params": {"chain_name": "anvil", "kind": "seller-bond"},
                },
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": 100,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "params": {"chain_name": "anvil", "kind": "primary-payment"},
                    "payer_principal": kwargs["buyer_principal"].model_dump(
                        mode="json"
                    ),
                    "claimant_principal": kwargs["seller_principal"].model_dump(
                        mode="json"
                    ),
                },
            ],
            "service_terms": {},
        }
    }


def _alkahest(escrow: EscrowOnChain | None = None):
    """The production Alkahest composition over the chain boundary's doubles."""
    return alkahest_composition(
        SELLER_SIGNER,
        wallet="0x3333333333333333333333333333333333333333",
        chain_clients={"anvil": ChainClient()},
        escrow=escrow or EscrowOnChain(),
    )


async def _accepted_runtime(
    path: str, verifier, *, commit_plan: bool = True
) -> tuple[BareMetalStorefrontRuntime, str]:
    domain = get_market_domain_contract()
    db = SQLiteClient(path, domain=domain)
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(
            identities=(ADMIN_SIGNER.identity,),
        ),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address="0x3333333333333333333333333333333333333333",
        plan_builder=_plan,
        settlement_composition=_alkahest(),
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    await db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="now",
        updated_at="now",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
    )
    negotiation_id = "neg-accepted"
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address=ESCROW_ADDRESS,
        fields={"amount": "100"},
        expiration_unix=int(time.time()) + 3600,
    )
    message = BareMetalMessage(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 persisted-key",
    )
    settlement = legacy_alkahest_option(
        proposal,
        _plan(
            proposal=proposal,
            buyer_principal=BUYER_SIGNER.identity,
            seller_principal=SELLER_SIGNER.identity,
        )["settlement_plan"],
    )
    now = datetime.now(timezone.utc).isoformat()
    agreement = Agreement(
        negotiation_id=negotiation_id,
        listing_id="listing-1",
        listing_hash="0" * 64,
        buyer=BUYER_SIGNER.identity.model_dump(mode="json"),
        seller=SELLER_SIGNER.identity.model_dump(mode="json"),
        settlement=settlement,
        settlement_params={},
        amount=100,
        asset=settlement.asset,
        duration_seconds=3600,
        start_utc=now,
        provision_terms=message.model_dump(mode="json", exclude_none=True),
        accepted_at=now,
    )
    await seed_thread(
        db,
        negotiation_id=negotiation_id,
        listing_id="listing-1",
        buyer_principal=BUYER_SIGNER.identity,
        seller_principal=runtime.seller_principal,
        message=message,
        proposal=proposal.model_dump(mode="json"),
        amount=100,
        terms=BareMetalTerms(
            host_id="machine-1",
            physical_host_id="host-1",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 persisted-key",
            listing_ref="listing-1",
        ),
        agreement_bytes=agreement.model_dump_json(exclude_none=True).encode(),
        settlement_plan=(
            _plan(
                proposal=proposal,
                buyer_principal=BUYER_SIGNER.identity,
                seller_principal=SELLER_SIGNER.identity,
            )["settlement_plan"]
            if commit_plan
            else None
        ),
    )
    return runtime, negotiation_id


async def test_settlement_is_verified_idempotently_without_fulfillment_claims(
    tmp_path,
) -> None:
    calls = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    app = _app(runtime)
    body = _settle_body(negotiation_id)

    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            first = await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
            retry = await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
            with pytest.raises(StorefrontClientError) as conflict:
                await buyer.settle_evm(
                    OTHER_ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )

    restarted_domain = get_market_domain_contract()
    restarted = BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=restarted_domain),
        domain=restarted_domain,
        seller_principal=runtime.seller_principal,
        admin_principals=runtime.admin_principals,
        storefront_url=runtime.storefront_url,
        marketplace_signer=runtime.marketplace_signer,
        seller_evm_address=runtime.seller_evm_address,
        plan_builder=_plan,
        settlement_composition=_alkahest(),
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    restarted_app = _app(restarted)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with _buyer(restarted_app) as buyer:
            restart_retry = await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
            status = await buyer.get_settle_status(ESCROW_UID)

    obligation_ref = first.extra.get("obligation_ref")
    assert isinstance(obligation_ref, str) and len(obligation_ref) == 64
    expected = {
        "escrow_uid": ESCROW_UID,
        "negotiation_id": negotiation_id,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "seller_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "status": "settlement_verified",
        "fulfillment_available": True,
        "obligation_ref": obligation_ref,
    }
    assert _settled(first) == expected
    assert _settled(retry) == expected
    assert _settled(status) == expected
    assert conflict.value.status_code == 409
    assert "negotiation already has a primary escrow" in str(conflict.value)
    # Status re-checks the accepted escrow on chain before reporting it verified.
    assert len(calls) == 2
    assert (
        calls[1]["alkahest_client"]
        is restarted.settlement_composition.resources["clients"]["anvil"]
    )
    assert calls[0]["agreed_duration_seconds"] == 3600
    assert calls[0]["agreed_price"] == 100
    assert "ssh_public_key" not in body
    assert (first.provisioning_job_id, first.fulfillment_id) == (None, None)
    assert not ({"tenant_credentials", "receipt", "result"} & first.extra.keys())
    assert _settled(restart_retry) == expected
    # The restarted process services the obligation through the same
    # composition the first one verified it with.
    assert set(restarted.settlement_runtime._clients) == {"alkahest.v1"}
    aggregate = await restarted.settlement_runtime.get_status(negotiation_id)
    expiration_unix = aggregate.obligations[1].obligation["expiration_unix"]
    obligations = SettlementPlan.model_validate(
        _plan(
            proposal={"expiration_unix": expiration_unix},
            buyer_principal=BUYER_SIGNER.identity,
            seller_principal=SELLER_SIGNER.identity,
        )["settlement_plan"]
    ).model_dump(mode="json")["obligations"]
    assert aggregate.status == "active"
    assert len(aggregate.obligations) == 2
    assert aggregate.obligations[0].mechanism_ref is None
    verified = aggregate.obligations[1]
    assert verified.obligation_ref == derive_obligation_ref(
        negotiation_id,
        1,
        obligations[1],
    )
    assert verified.mechanism_ref == ESCROW_UID
    assert verified.materialization_state == "materialized"
    assert verified.mechanism_status == "ready"
    assert verified.mechanism_state == {}
    # The worker's status step, run once by verification, anchors the
    # condition on the escrow; with no site configured here nothing is delivered.
    assert verified.condition_anchor == ESCROW_UID
    assert verified.fulfillment_ref is None
    assert verified.condition_state == "pending"
    assert verified.collection_state == "pending"
    assert all(item.fulfillment_ref is None for item in aggregate.obligations)

    conn = sqlite3.connect(path)
    try:
        operations = conn.execute(
            "SELECT operation, state FROM settlement_operations "
            "ORDER BY obligation_ref, operation"
        ).fetchall()
        legacy_claim_table = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'settlement_claims'"
        ).fetchone()
        legacy_claims = (
            conn.execute("SELECT COUNT(*) FROM settlement_claims").fetchone()[0]
            if legacy_claim_table is not None
            else 0
        )
    finally:
        conn.close()
    # Verification adopted the escrow and stepped the worker once; no
    # collection or reclaim was attempted.
    assert ("materialize", "succeeded") in operations
    assert not {operation for operation, _state in operations} & {"collect", "reclaim"}
    assert legacy_claims == 0


async def test_settlement_rejects_replacement_access_input_and_failed_verification(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise ValueError("chain mismatch")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    app = _app(runtime)

    # Rejection path: a settlement restating a negotiated term is a body the
    # canonical client never sends, so its refusal is checked hand-built.
    with TestClient(app) as client:
        replacement_body = {
            **_settle_body(negotiation_id),
            "ssh_public_key": "attacker-key",
        }
        replacement = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=replacement_body,
            headers=_headers("settle_escrow", ESCROW_UID, replacement_body),
        )
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            with pytest.raises(StorefrontClientError) as failed:
                await buyer.settle_evm(
                    ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )

    assert replacement.status_code == 422
    assert failed.value.status_code == 400
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None


async def test_settlement_rejects_unmatched_obligation_without_registering_claims(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        return 2

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.settle_evm(
                    ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )

    assert refused.value.status_code == 400
    assert "settlement verification returned no exact obligation" in str(refused.value)
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None
    aggregate = await runtime.settlement_runtime.get_status(negotiation_id)
    assert aggregate.obligations == []


async def test_status_fails_closed_without_canonical_verified_adoption(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise AssertionError("status must not call a settlement provider")

    # No committed plan, so nothing at startup can adopt the recorded escrow.
    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
        commit_plan=False,
    )
    inserted = await runtime.db.insert_escrow(
        escrow_uid=ESCROW_UID,
        negotiation_id=negotiation_id,
        chain_name="anvil",
        escrow_address=ESCROW_ADDRESS,
        is_primary=True,
        status="settlement_verified",
    )
    assert inserted

    with TestClient(_app(runtime)) as client:
        response = client.get(
            f"/api/v1/settle/{ESCROW_UID}/status",
            headers=_headers("settle_status", ESCROW_UID, method="GET"),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "settlement not found"


class _FulfillmentSite:
    def __init__(self) -> None:
        self.releases = []

    async def list_reservations(self):
        return []

    async def release(self, **request):
        self.releases.append(request)
        return {"state": "released"}


class _CapacityClient:
    def __init__(self) -> None:
        self.site_client = _FulfillmentSite()
        self.reservation_sites = {}
        self.reserve_calls = []
        self.commit_calls = []
        self.committed_window: tuple[str, str] | None = None

    def site(self, site_id):
        assert site_id == "site-a"
        return self.site_client

    async def reserve(self, **request):
        self.reserve_calls.append(request)
        self.reservation_sites["reservation-a"] = request["site"]
        return {
            "capacity_reservation_id": "reservation-a",
            "site": request["site"],
        }

    async def commit(self, **request):
        """Write-once, as the site's: the first commit's window is kept."""
        self.commit_calls.append(request)
        if self.committed_window is None:
            self.committed_window = (request["lease_start_utc"], request["lease_end_utc"])
        start, end = self.committed_window
        return {
            "capacity_reservation_id": request["capacity_reservation_id"],
            "state": "leased",
            "lease_start_utc": start,
            "lease_end_utc": end,
            "site": request["site_id"],
        }


class _ProvisioningClient:
    def __init__(self, *, torn_down: bool = False) -> None:
        self.begin_calls = []
        self.teardown_calls = []
        self.terminations = []
        self.torn_down = torn_down

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id="settlement-resource-a",
            pool_id="pool-a",
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "host_id": "machine-1",
                    "physical_host_id": "host-1",
                }
            },
        )

    async def begin_fulfillment(self, body):
        self.begin_calls.append(body)
        return SimpleNamespace(
            fulfillment_id="fulfillment-a",
            capacity_reservation_id="reservation-a",
            state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id, **request):
        assert fulfillment_id == "fulfillment-a"
        return SimpleNamespace(
            state="torn_down" if self.torn_down else "active",
            failure_reason=None,
            failure_message=None,
        )

    async def get_fulfillment_result(self, fulfillment_id, **request):
        return VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "fulfillment_id": fulfillment_id,
                "capacity_reservation_id": "reservation-a",
                "state": "active",
                "provisioned_resources": [],
                "domain_result": {
                    "kind": "compute.access-delivery",
                    "schema_version": 1,
                    "payload": {
                        "endpoints": [
                            {
                                "protocol": "ssh",
                                "host": "203.0.113.25",
                                "port": 2222,
                                "user": "tenant-a",
                            }
                        ],
                        "credentials": [],
                        "ready_at": "2030-01-01T00:00:01+00:00",
                    },
                },
            },
        )

    async def terminate_lease(self, capacity_reservation_id, *, reason=None):
        """The site ends the lease, then converges teardown through its fulfillment."""
        self.terminations.append((capacity_reservation_id, reason))
        self.torn_down = True
        return SimpleNamespace(capacity_reservation_id=capacity_reservation_id, status="releasing")

    async def begin_fulfillment_teardown(self, fulfillment_id, **request):
        self.teardown_calls.append((fulfillment_id, request))
        self.torn_down = True
        return SimpleNamespace(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="reservation-a",
            state="teardown_dispatch_pending",
        )


def _fulfillment_client(base_url: str) -> BareMetalFulfillmentTransport:
    """The production bare-metal buyer's fulfillment client, pointed at ``base_url``."""
    return BareMetalFulfillmentTransport(
        seller_url=base_url,
        principal=BUYER_SIGNER.identity,
        signer=BUYER_SIGNER,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(SELLER_SIGNER.identity,)
        ),
    )


@pytest.mark.parametrize(
    "reclaim_state,mechanism_status,collection_state",
    [
        ("succeeded", "ready", "pending"),
        ("in_progress", "ready", "pending"),
        ("manual_required", "ready", "pending"),
        ("pending", "reclaimed", "pending"),
        ("pending", "expired", "pending"),
        ("pending", "failed", "pending"),
        ("pending", "ready", "succeeded"),
    ],
)
async def test_alkahest_recovery_refuses_non_active_journal_before_physical_effects(
    tmp_path, reclaim_state, mechanism_status, collection_state
):
    calls = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    capacity, provisioning = _CapacityClient(), _ProvisioningClient()
    runtime = replace(
        runtime, capacity_client=capacity, fulfillment_client=provisioning
    )
    # Adopt without stepping the obligation, so the gate below is the first
    # thing that could start delivery.
    verified = await replace(
        runtime.settlement_service(), service_obligation=None
    ).verify(
        escrow_uid=ESCROW_UID,
        request=BareMetalSettleRequest(**_settle_body(negotiation_id)),
        buyer_principal=BUYER_SIGNER.identity,
    )
    aggregate = await runtime.settlement_runtime.get_status(negotiation_id)
    obligation = next(
        item for item in aggregate.obligations
        if item.obligation_ref == verified.obligation_ref
    )
    changed = obligation.model_copy(update={
        "reclaim_state": reclaim_state,
        "mechanism_status": mechanism_status,
        "collection_state": collection_state,
    })
    assert await runtime.settlement_repository.save_settlement_obligation(
        changed.model_dump(mode="json"), expected_version=obligation.version
    )
    restarted = replace(runtime, db=SQLiteClient(path, domain=runtime.domain))
    with pytest.raises(BareMetalFulfillmentError, match="no longer active"):
        await restarted.fulfillment_service().begin(
            negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
        )
    assert await restarted.db.load_bare_metal_fulfillment_lifecycle(
        negotiation_id=negotiation_id
    ) is None
    assert capacity.reserve_calls == []
    assert provisioning.begin_calls == []
    assert len(calls) == 1


@pytest.mark.parametrize("invalid_index", [None, 0, True])
async def test_alkahest_recovery_rechecks_chain_before_physical_effects(
    tmp_path, invalid_index
):
    calls = []
    source_valid = True

    async def verifier(**kwargs):
        calls.append(kwargs)
        if not source_valid:
            if invalid_index is None:
                raise ValueError("escrow revoked on chain")
            return invalid_index
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    capacity, provisioning = _CapacityClient(), _ProvisioningClient()
    runtime = replace(
        runtime, capacity_client=capacity, fulfillment_client=provisioning
    )
    # Adopt without stepping the obligation, so the gate below is the first
    # thing that could start delivery.
    await replace(runtime.settlement_service(), service_obligation=None).verify(
        escrow_uid=ESCROW_UID,
        request=BareMetalSettleRequest(**_settle_body(negotiation_id)),
        buyer_principal=BUYER_SIGNER.identity,
    )
    restarted = replace(runtime, db=SQLiteClient(path, domain=runtime.domain))
    source_valid = False
    with pytest.raises(BareMetalFulfillmentError, match="stored escrow source"):
        await restarted.fulfillment_service().begin(
            negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
        )
    assert await restarted.db.load_bare_metal_fulfillment_lifecycle(
        negotiation_id=negotiation_id
    ) is None
    assert capacity.reserve_calls == []
    assert provisioning.begin_calls == []

    source_valid = True
    first = await restarted.fulfillment_service().begin(
        negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
    )
    repeated = await restarted.fulfillment_service().begin(
        negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
    )
    assert repeated == first
    assert len(capacity.reserve_calls) == len(provisioning.begin_calls) == 1
    assert len(calls) == 4
    assert all(call["escrow_uid"] == ESCROW_UID for call in calls)
    assert all(call["agreed_price"] == 100 for call in calls)
    assert all(call["agreed_duration_seconds"] == 3600 for call in calls)
    assert (
        calls[-1]["alkahest_client"]
        is restarted.settlement_composition.resources["clients"]["anvil"]
    )
    assert calls[-1]["escrow_proposal"].escrow_address == ESCROW_ADDRESS


async def test_http_fulfillment_restarts_on_recorded_site_and_redacts_result(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    capacity = _CapacityClient()
    provisioning = _ProvisioningClient()
    runtime = replace(
        runtime,
        capacity_client=capacity,
        fulfillment_client=provisioning,
    )
    with serving(_app(runtime)) as base_url:
        async with StorefrontClient(
            base_url,
            signer=BUYER_SIGNER,
            caller_role="buyer",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        ) as storefront:
            settled = await storefront.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
        buyer = _fulfillment_client(base_url)
        # Settlement started fulfillment; the buyer only observes it.
        ready = buyer.status(negotiation_id)
        result = buyer.result(negotiation_id)
        access = buyer.access(negotiation_id)
        tearing_down = buyer.teardown(negotiation_id)

    restarted_capacity = _CapacityClient()
    restarted = replace(
        runtime,
        db=SQLiteClient(path, domain=runtime.domain),
        capacity_client=restarted_capacity,
        fulfillment_client=_ProvisioningClient(torn_down=True),
        site_bindings=(
            BareMetalSiteBinding(
                site_id="site-a",
                authority_url="http://site-a",
                authority_principal=SITE_SIGNER.identity,
            ),
        ),
    )
    with serving(_app(restarted)) as base_url:
        buyer = _fulfillment_client(base_url)
        torn_down = buyer.status(negotiation_id)
        # The site releases the capacity after the teardown and says so.
        async with StorefrontClient(
            base_url,
            signer=SITE_SIGNER,
            caller_role="service",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        ) as site:
            recorded = await site.notify_capacity_released("reservation-a", site_id="site-a")
        released = buyer.status(negotiation_id)
        repeated = buyer.status(negotiation_id)

    assert settled.status == "settlement_verified"
    assert ready["state"] == "active"
    assert tearing_down["state"] == "terminating"
    assert torn_down["state"] == "torn_down"
    assert recorded == {"capacity_reservation_id": "reservation-a", "state": "released"}
    assert released["state"] == "released"
    assert repeated == released
    assert capacity.reserve_calls[0]["site"] == "site-a"
    assert capacity.reserve_calls[0]["claim"]["resource_id"] == "resource-1"
    # Read back from the persisted listing, not supplied by the buyer.
    assert capacity.reserve_calls[0]["claim"]["gpu_model"] == LISTING_HARDWARE["gpu_model"]
    assert capacity.reserve_calls[0]["claim"]["dimensions"] == {"units": 1}
    assert len(provisioning.begin_calls) == 1
    assert provisioning.terminations == [("reservation-a", "buyer_teardown")]
    assert provisioning.teardown_calls == []
    # The storefront never releases capacity itself.
    assert restarted_capacity.site_client.releases == []
    public_result = result
    assert public_result["receipt"]["status"] == "ready"
    assert public_result["result"]["ssh_user"] == "tenant-a"
    # Where to connect is served live by the access route, never stored.
    assert "host" not in public_result["result"]
    assert "port" not in public_result["result"]
    lease_end = public_result["receipt"]["lease_end_utc"]
    assert public_result["result"]["lease_end_utc"] == lease_end
    assert access == {
        "negotiation_id": negotiation_id,
        "method": "ssh",
        "host": "203.0.113.25",
        "port": 2222,
        "username": "tenant-a",
        "expires_at": lease_end,
    }
    serialized_result = json.dumps(public_result, sort_keys=True)
    for forbidden in (
        "authority_url",
        "credential",
        "private_key",
        "provider",
        "provider_metadata",
    ):
        assert forbidden not in serialized_result


async def test_verify_registers_exactly_the_committed_plan(tmp_path) -> None:
    """Settlement verification registers the plan committed at acceptance.

    The buyer funds from the plan in the negotiation response, the one committed
    at acceptance; verification builds nothing and registers that plan's
    obligations exactly. Built here with the real builder against the development
    chain's addresses, every build recorded.
    """
    from market_alkahest.dev_chain import anvil_address_book_path
    from source_sites import SourceSites

    from arkhai_bare_metal_storefront.settlement import build_bare_metal_settlement_plan

    builds: list[dict] = []

    def recording_builder(**kwargs):
        artifacts = build_bare_metal_settlement_plan(**kwargs)
        builds.append(artifacts["settlement_plan"])
        return artifacts

    async def verifier(**_kwargs):
        # The escrow matches the plan's only obligation.
        return 0

    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address="0x3333333333333333333333333333333333333333",
        plan_builder=recording_builder,
        settlement_composition=_alkahest(),
        chain_config_paths={"anvil": str(anvil_address_book_path())},
        escrow_verifier=verifier,
        capacity_client=SourceSites(),
    )
    await db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="now",
        updated_at="now",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": ESCROW_ADDRESS,
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }
        ],
    )
    opened = await runtime.negotiation_runtime.start(
        repository=db,
        listing_id="listing-1",
        buyer_principal=BUYER_SIGNER.identity,
        seller_principal=runtime.seller_principal,
        actor_principal=BUYER_SIGNER.identity,
        proposal={
            "chain_name": "anvil",
            "escrow_address": ESCROW_ADDRESS,
            "fields": {"amount": "100", "token": TOKEN},
            "literal_fields": {"token": TOKEN},
            "expiration_unix": int(time.time()) + 3600,
        },
        terms={
            "kind": "bare_metal.v2",
            "version": 1,
            "payload": {
                "duration_seconds": 3600,
                "access_method": "ssh",
                "ssh_public_key": "ssh-ed25519 persisted-key",
            },
        },
        seller_agent_url=runtime.storefront_url,
        buyer_agent_url="https://buyer.example",
    )
    assert opened["action"] == "accept"
    negotiation_id = opened["negotiation_id"]

    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )

    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    committed = thread["settlement_plan"]
    committed = json.loads(committed) if isinstance(committed, str) else committed
    assert len(builds) == 1, "only the opening builds a plan"
    assert opened["settlement_plan"] == committed == builds[0]
    registered = await runtime.settlement_runtime.get_status(negotiation_id)
    assert [record.obligation for record in registered.obligations] == (
        SettlementPlan.model_validate(committed).model_dump(mode="json")["obligations"]
    )


PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"


async def test_payment_evidence_gates_replay_and_rechecks_receipt_after_restart(
    tmp_path,
):
    buyer = Ed25519Signer(bytes.fromhex("66" * 32))
    seller = Ed25519Signer(bytes.fromhex("77" * 32))
    receipt_signer = Ed25519Signer(bytes.fromhex("55" * 32))
    payments = FakePaymentsClient()
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "payment.db"), domain=domain)
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "priority": ["arkhai.payments.v1"],
            "arkhai_payments": {
                "enabled": True,
                "service_url": "http://127.0.0.1:3180",
                "development_auth": True,
                "service_identity": receipt_signer.identity.model_dump(mode="json"),
                "fee_bps": 0,
                "dispute_authority": "00000000-0000-4000-8000-000000000013",
            },
        },
        payments_client_for_owner=payments,
    )
    params = {
        "payee_account": PAYEE,
        "asset": "USD/2",
        "window": "PT1H",
        "deposit_agreement": False,
    }
    rates = [RateValue(field="amount", per="hour", value=100)]
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="arkhai.payments.v1", asset="USD/2", rates=rates, params=params
        ),
        mechanism="arkhai.payments.v1",
        asset="USD/2",
        rates=rates,
        params=params,
    )
    await db.upsert_bare_metal_listing(
        listing_id="listing-payment",
        status="open",
        created_at="now",
        updated_at="now",
        seller_principal=seller.identity,
        storefront_url="http://seller:8000",
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option.model_dump(mode="json")],
    )
    capacity, provisioning = _CapacityClient(), _ProvisioningClient()
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=seller.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=seller,
        settlement_composition=composition,
        capacity_client=capacity,
        fulfillment_client=provisioning,
    )
    negotiation_id = "neg-payment"
    message = BareMetalMessage(
        duration_seconds=3600, ssh_public_key="ssh-ed25519 payment-key"
    )
    now = datetime.now(timezone.utc).isoformat()
    agreement_bytes = Agreement(
        negotiation_id=negotiation_id,
        listing_id="listing-payment",
        listing_hash="0" * 64,
        buyer=buyer.identity.model_dump(mode="json"),
        seller=seller.identity.model_dump(mode="json"),
        settlement=option,
        settlement_params={"payer_account": PAYER},
        amount=100,
        asset="USD/2",
        duration_seconds=3600,
        start_utc=now,
        provision_terms=message.model_dump(mode="json", exclude_none=True),
        accepted_at=now,
    ).model_dump_json(exclude_none=True).encode()
    data = composition.arkhai_payments_stage().settlement_data(
        json.loads(agreement_bytes)
    )
    await seed_thread(
        db,
        negotiation_id=negotiation_id,
        listing_id="listing-payment",
        buyer_principal=buyer.identity,
        seller_principal=seller.identity,
        message=message,
        proposal={},
        amount=100,
        terms=BareMetalTerms(
            host_id="machine-1",
            physical_host_id="host-1",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 payment-key",
            listing_ref="listing-payment",
        ),
        agreement_bytes=agreement_bytes,
        settlement_data=data.to_wire(),
    )
    request = BareMetalSettleRequest(
        negotiation_id=negotiation_id, buyer_principal=buyer.identity
    )
    delivery = runtime.fulfillment_service()
    pending = await runtime.settlement_service().verify(
        escrow_uid=negotiation_id, request=request, buyer_principal=buyer.identity
    )
    assert (pending.status_code, pending.payload["status"]) == (202, "pending")
    with pytest.raises(BareMetalFulfillmentError, match="not authoritatively verified"):
        await delivery.begin(
            negotiation_id=negotiation_id, buyer_principal=buyer.identity
        )
    assert capacity.reserve_calls == [] and provisioning.begin_calls == []

    payments.serve(build_signed_receipt(signer=receipt_signer, mandate=data.mandate))
    verified = await runtime.settlement_service().verify(
        escrow_uid=negotiation_id, request=request, buyer_principal=buyer.identity
    )
    assert verified.status_code == 200
    assert verified.payload["settlement_ref"] == data.transaction_id
    # Settlement started delivery itself; a later begin is the same delivery.
    first = await delivery.begin(
        negotiation_id=negotiation_id, buyer_principal=buyer.identity
    )
    assert len(capacity.reserve_calls) == len(provisioning.begin_calls) == 1

    original = await runtime.settlement_service().verified_evidence(
        negotiation_id=negotiation_id, buyer_principal=buyer.identity
    )
    for change in (
        {"mechanism": "alkahest.v1"},
        {"settlement_ref": "changed-reference"},
        {"evidence": {**dict(original.evidence), "agreement_sha256": "a" * 64}},
        {"evidence": {**dict(original.evidence), "source": {"receipt": {}}}},
    ):
        with pytest.raises(RuntimeError, match="conflicts"):
            await db.save_bare_metal_settlement_evidence(replace(original, **change))
        assert (
            await runtime.settlement_service().verified_evidence(
                negotiation_id=negotiation_id, buyer_principal=buyer.identity
            )
            == original
        )

    restarted = replace(runtime, db=SQLiteClient(db.db_path, domain=domain))
    repeated = await restarted.fulfillment_service().begin(
        negotiation_id=negotiation_id, buyer_principal=buyer.identity
    )
    ready = await restarted.fulfillment_service().status(
        negotiation_id=negotiation_id, buyer_principal=buyer.identity
    )
    assert repeated == first
    assert ready["state"] == "active"
    stored_result = await restarted.db.load_bare_metal_result(
        negotiation_id=negotiation_id
    )
    assert "host" not in stored_result.model_dump()
    assert len(capacity.reserve_calls) == len(provisioning.begin_calls) == 1

    corrupt = copy.deepcopy(dict(original.evidence))
    corrupt["source"]["receipt"]["proof"]["value"] = "A" * 86
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE bare_metal_settlement_records SET evidence_json=? WHERE negotiation_id=?",
            (json.dumps(corrupt), negotiation_id),
        )
        assert conn.execute("SELECT count(*) FROM escrows").fetchone()[0] == 0
    with pytest.raises(
        BareMetalFulfillmentError, match="stored payment receipt is invalid"
    ):
        await restarted.fulfillment_service().status(
            negotiation_id=negotiation_id, buyer_principal=buyer.identity
        )
    assert len(capacity.reserve_calls) == len(provisioning.begin_calls) == 1


async def test_verify_refuses_a_thread_with_no_committed_plan(tmp_path) -> None:
    async def verifier(**_kwargs):
        raise AssertionError("verification must not reach the escrow")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"), verifier, commit_plan=False
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.settle_evm(
                    ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
                )

    assert refused.value.status_code == 409
    assert "no committed settlement plan" in str(refused.value)
    assert (await runtime.settlement_runtime.get_status(negotiation_id)).obligations == []
