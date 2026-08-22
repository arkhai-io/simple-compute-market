"""Wire-level coverage for the buyer's hosted settlement routes.

Every earlier test of these routes called the controller directly. That skips
the two things a buyer actually depends on: the middleware that signs the
answer, and the exact digest and context handed to the verifier. A route that
authenticates correctly under a direct call can still refuse every real request
and can still answer unreadably, and neither shows up until a signed client
talks to the mounted app.

Requests here are signed exactly as ``core_buyer`` signs them and responses are
verified exactly as ``core_buyer`` verifies them, so a passing test means a
buyer holding only the seller's pinned principal can complete the exchange.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from arkhai_vms import make_vm_provision_terms
from core_storefront.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from fastapi import FastAPI
from market_core.schemas import (
    RateValue,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_hosted_settlement import ConditionDescriptor
from market_identity import (
    AuthenticatedResponse,
    Ed25519Signer,
    EMPTY_BODY,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)
from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementOperationOutcome,
    derive_obligation_ref,
)

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import settlements_router
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER_SIGNER = Ed25519Signer(b"\x71" * 32)
SELLER_SIGNER = Ed25519Signer(b"\x72" * 32)
INTRUDER_SIGNER = Ed25519Signer(b"\x73" * 32)
BUYER = BUYER_SIGNER.identity
SELLER = SELLER_SIGNER.identity
SELLER_TRUST = TrustedIdentitySet(identities=(SELLER,))

NEGOTIATION_ID = "negotiation-wire-1"
SETTLEMENT_REF = "settlement-wire-1"

CONDITION = ConditionDescriptor.model_validate(
    {
        "protocol": "arkhai.condition.v1",
        "condition_id": "vm-fulfillment-1",
        "evaluator": {
            "kind": "builtin.v1",
            "version": "trivial.v1",
            "params": {"kind": "trivial"},
        },
        "demand": {"encoding": "application/jcs+json", "value": True},
    }
).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Accepted state
# ---------------------------------------------------------------------------


def _accepted_plan(funding_profile: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    option_params = {
        "account_ref": "account-seller",
        "claimant_principal": SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "condition": CONDITION,
        "funding_profile": funding_profile,
        "authority_id": "hosted-authority-1",
        "environment": "test",
        "country": "US",
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "11" * 32,
    }
    obligation = SettlementObligation(
        payer="buyer",
        claimant="seller",
        payer_principal=BUYER.model_dump(mode="json"),
        claimant_principal=SELLER.model_dump(mode="json"),
        amount=125,
        asset="usd",
        expiration_unix=2_000_000_000,
        conditions=[CONDITION],
        mechanism="fiat.stripe.v1",
        params={
            **option_params,
            "payer_principal": BUYER.model_dump(mode="json"),
        },
    )
    rates = [RateValue(field="amount", value=125)]
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=option_params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=option_params,
    )
    selection = SettlementSelection(
        option_id=option.option_id,
        mechanism=option.mechanism,
        expiration_unix=2_000_000_000,
    )
    provision = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAAaccepted buyer@test",
    ).model_dump(mode="json")
    listing = {
        "listing_id": "listing-1",
        "offer_resource": {"gpu_model": "H100", "gpu_count": 1},
        "settlement_options": [option.model_dump(mode="json")],
    }
    plan = SettlementPlan(
        buyer_principal=BUYER.model_dump(mode="json"),
        seller_principal=SELLER.model_dump(mode="json"),
        obligations=[obligation],
        service_terms={
            "vm.v1": {
                "listing_id": "listing-1",
                "order": dict(listing),
                "provision": provision,
            }
        },
    )
    thread = {
        "terminal_state": "success",
        "buyer_principal": BUYER.model_dump(mode="json"),
        "our_listing_id": "listing-1",
        "agreed_price": 125,
        "buyer_escrow_proposal": {
            "settlement_selection": selection.model_dump(mode="json")
        },
        "settlement_plan": plan.model_dump(),
        "provision_terms": provision,
    }
    return thread, listing, plan.obligations[0].model_dump()


# ---------------------------------------------------------------------------
# Signed transport
# ---------------------------------------------------------------------------


async def _call(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    operation: str,
    resource: str,
    body: dict[str, Any] | None = None,
    signer: Ed25519Signer = BUYER_SIGNER,
    request_id: str | None = None,
) -> tuple[int, Any, dict[str, str]]:
    """Send one buyer-signed request the way ``core_buyer`` sends it."""

    request_id = request_id or uuid.uuid4().hex
    body_value: Any = EMPTY_BODY if body is None else body
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="buyer",
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body_value),
        ),
    )
    headers = {
        "Accept": "application/json",
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }
    response = await client.request(
        method,
        path,
        headers=headers,
        json=body if body is not None else None,
    )
    payload = response.json() if response.content else {}
    return response.status_code, payload, dict(response.headers), request_id


def _assert_seller_signed(
    *,
    status: int,
    payload: Any,
    headers: dict[str, str],
    method: str,
    operation: str,
    resource: str,
    request_id: str,
) -> None:
    """Verify the answer exactly as the buyer's transport verifies it."""

    signed = AuthenticatedResponse.model_validate(
        {
            "protocol": headers.get(SIGNATURE_VERSION_HEADER.lower()),
            "role": headers.get(ROLE_HEADER.lower()),
            "principal": {
                "scheme": headers.get(IDENTITY_SCHEME_HEADER.lower()),
                "identifier": headers.get(IDENTITY_IDENTIFIER_HEADER.lower()),
            },
            "method": method,
            "operation": operation,
            "resource": resource,
            "request_id": headers.get(REQUEST_ID_HEADER.lower()),
            "timestamp": int(headers.get(TIMESTAMP_HEADER.lower()) or ""),
            "status": status,
            "body_hash": canonical_body_hash(payload),
            "proof": {
                "scheme": headers.get(IDENTITY_SCHEME_HEADER.lower()),
                "value": headers.get(SIGNATURE_HEADER.lower()),
            },
        }
    )
    verification = verify_response(
        signed,
        body=payload,
        now=int(time.time()),
        max_skew=300,
        expected_role="seller",
        expected_principals=SELLER_TRUST,
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_request_id=request_id,
    )
    assert verification.verified, verification.code


# ---------------------------------------------------------------------------
# In-memory settlement runtime
# ---------------------------------------------------------------------------


class _Runtime:
    """Just enough of the settlement runtime to move one obligation forward."""

    def __init__(self) -> None:
        self.records: dict[str, SettlementObligationRecord] = {}

    async def register_plan(self, *, agreement_ref: str, obligations: list[Any]):
        registered = [
            SettlementObligationRecord.from_obligation(
                agreement_ref=agreement_ref,
                obligation_index=index,
                obligation=obligation,
            )
            for index, obligation in enumerate(obligations)
        ]
        for record in registered:
            self.records[record.obligation_ref] = record
        return registered

    async def bind_mechanism_params(self, obligation_ref, params, *, local_principal):
        record = self.records[obligation_ref].model_copy(
            update={"mechanism_params": dict(params)}
        )
        self.records[obligation_ref] = record
        return record

    async def materialize(self, *, obligation_ref, local_principal, worker_id):
        self.records[obligation_ref] = self.records[obligation_ref].model_copy(
            update={
                "mechanism_ref": SETTLEMENT_REF,
                "mechanism_status": "requires_action",
                "mechanism_state": {"funding_reason": "payer_action_required"},
                "materialization_receipt": {"funding_reason": "payer_action_required"},
            }
        )
        return SettlementOperationOutcome(
            obligation_ref=obligation_ref,
            operation="materialize",
            status="pending",
            action={
                "kind": "confirmation",
                "operation_ref": "action-1",
                "expires_at_unix": 2_000_000_000,
                "url": "https://checkout.example/transient",
            },
            receipt={"funding_reason": "payer_action_required"},
        )

    async def reconcile_status(self, *, obligation_ref, local_principal, worker_id):
        return SettlementOperationOutcome(
            obligation_ref=obligation_ref,
            operation="status",
            status="pending",
            receipt={"funding_reason": "payer_action_required"},
        )


class _Repository:
    def __init__(self, runtime: _Runtime) -> None:
        self._runtime = runtime

    async def load_settlement_obligation(self, obligation_ref: str):
        record = self._runtime.records.get(obligation_ref)
        return None if record is None else record.model_dump()

    async def load_settlement_obligation_by_mechanism_ref(self, mechanism_ref: str):
        for record in self._runtime.records.values():
            if record.mechanism_ref == mechanism_ref:
                return record.model_dump()
        return None


@pytest_asyncio.fixture
async def wired(tmp_path, monkeypatch):
    """Mount the settlements router behind the middleware a buyer really meets."""

    thread, listing, obligation = _accepted_plan("us_ach_debit.v1")
    db = SQLiteClient(
        db_path=str(tmp_path / "wire.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )
    db.load_negotiation_thread_row = AsyncMock(return_value=thread)  # type: ignore[method-assign]
    db.load_listing = AsyncMock(return_value=listing)  # type: ignore[method-assign]

    runtime = _Runtime()
    composition = SimpleNamespace(
        runtime=runtime,
        repository=_Repository(runtime),
        worker=SimpleNamespace(wake=AsyncMock()),
        mechanism_clients={"fiat.stripe.v1": object()},
        local_principal=SELLER,
    )
    monkeypatch.setattr(_container, "resolved_sqlite_client", db)
    monkeypatch.setattr(_container, "resolved_settlement_composition", composition)
    monkeypatch.setattr(_container, "resolved_marketplace_signer", SELLER_SIGNER)

    app = FastAPI()
    app.middleware("http")(listing_lifecycle_middleware)
    app.include_router(settlements_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            obligation_ref=derive_obligation_ref(NEGOTIATION_ID, 0, obligation),
            runtime=runtime,
        )


# ---------------------------------------------------------------------------
# The exchange a buyer actually performs
# ---------------------------------------------------------------------------


async def _start(wired) -> tuple[int, Any, dict[str, str], str]:
    return await _call(
        wired.client,
        method="POST",
        path="/api/v1/settlements",
        operation="settlement_start",
        resource=wired.obligation_ref,
        body={
            "negotiation_id": NEGOTIATION_ID,
            "obligation_ref": wired.obligation_ref,
            "funding_authorization_ref": "authorization-1",
        },
    )


@pytest.mark.asyncio
async def test_start_then_status_completes_for_a_signed_buyer(wired) -> None:
    """The two calls every hosted purchase makes must both succeed and be signed."""

    status, payload, headers, request_id = await _start(wired)
    assert status == 200, payload
    _assert_seller_signed(
        status=status,
        payload=payload,
        headers=headers,
        method="POST",
        operation="settlement_start",
        resource=wired.obligation_ref,
        request_id=request_id,
    )
    settlement_ref = payload["settlement_ref"]
    assert settlement_ref == SETTLEMENT_REF

    status, payload, headers, request_id = await _call(
        wired.client,
        method="GET",
        path=f"/api/v1/settlements/{settlement_ref}",
        operation="settlement_status",
        resource=settlement_ref,
    )
    assert status == 200, payload
    _assert_seller_signed(
        status=status,
        payload=payload,
        headers=headers,
        method="GET",
        operation="settlement_status",
        resource=settlement_ref,
        request_id=request_id,
    )
    assert payload["obligation_ref"] == wired.obligation_ref


@pytest.mark.asyncio
async def test_status_polls_repeatedly_without_replay_refusal(wired) -> None:
    """``wait`` polls; a poll that collides with its predecessor stalls a purchase."""

    _status, payload, _headers, _request_id = await _start(wired)
    settlement_ref = payload["settlement_ref"]
    for _ in range(3):
        status, payload, headers, request_id = await _call(
            wired.client,
            method="GET",
            path=f"/api/v1/settlements/{settlement_ref}",
            operation="settlement_status",
            resource=settlement_ref,
        )
        assert status == 200, payload
        _assert_seller_signed(
            status=status,
            payload=payload,
            headers=headers,
            method="GET",
            operation="settlement_status",
            resource=settlement_ref,
            request_id=request_id,
        )


@pytest.mark.asyncio
async def test_a_refused_buyer_still_receives_a_signed_answer(wired) -> None:
    """An unsigned refusal is unreadable, so the buyer cannot report the cause.

    A principal that is not the payer must be refused — and must learn that it
    was refused rather than that the storefront answered unintelligibly.
    """

    _status, payload, _headers, _request_id = await _start(wired)
    settlement_ref = payload["settlement_ref"]

    status, payload, headers, request_id = await _call(
        wired.client,
        method="GET",
        path=f"/api/v1/settlements/{settlement_ref}",
        operation="settlement_status",
        resource=settlement_ref,
        signer=INTRUDER_SIGNER,
    )
    assert status == 403, payload
    _assert_seller_signed(
        status=status,
        payload=payload,
        headers=headers,
        method="GET",
        operation="settlement_status",
        resource=settlement_ref,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_a_caller_without_a_request_identity_is_refused_unsigned(wired) -> None:
    """There is nothing to bind, and an invented identity would verify against nothing."""

    _status, payload, _headers, _request_id = await _start(wired)
    settlement_ref = payload["settlement_ref"]

    response = await wired.client.get(
        f"/api/v1/settlements/{settlement_ref}",
        headers={"Accept": "application/json"},
    )
    assert response.status_code >= 400
    assert SIGNATURE_HEADER.lower() not in response.headers


@pytest.mark.asyncio
async def test_a_refusal_before_dispatch_reserves_no_replay_identity(wired) -> None:
    """A refused request dispatched nothing, so a later honest one must not inherit an outcome."""

    _status, payload, _headers, _request_id = await _start(wired)
    settlement_ref = payload["settlement_ref"]

    status, _payload, _headers, request_id = await _call(
        wired.client,
        method="GET",
        path=f"/api/v1/settlements/{settlement_ref}",
        operation="settlement_status",
        resource=settlement_ref,
        signer=INTRUDER_SIGNER,
    )
    assert status == 403

    db = _container.resolved_sqlite_client
    assert await db.get_replay_reservation(INTRUDER_SIGNER.identity, request_id) is None
