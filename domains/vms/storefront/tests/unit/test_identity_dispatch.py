"""Focused v2 identity tests for VM listing lifecycle composition."""

from __future__ import annotations

import time

import pytest
from fastapi import Request
from market_identity import (
    EMPTY_BODY,
    REQUEST_PROTOCOL,
    Ed25519Signer,
    ReplayReservation,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

import market_storefront.container as container
from market_storefront.middleware.admin_identity import _contract as _admin_contract
from core_storefront.auth import AuthError, ReplayClaim
from market_storefront.middleware.seller_auth import (
    _buyer_response_contract,
    authenticate_listing_mutation,
    authorize_listing_mutation,
    resolve_listing_mutation,
)

pytestmark = pytest.mark.asyncio


class ReplayStore:
    def __init__(self, *, buyer=None, listing_id="listing-1") -> None:
        self.reservations: dict[tuple[object, str], ReplayReservation] = {}
        self.outcomes: dict[tuple[object, str], tuple[int, object]] = {}
        self.buyer = buyer
        self.listing_id = listing_id

    async def get_replay_reservation(self, principal, request_id):
        return self.reservations.get((principal, request_id))

    async def claim_replay(self, reservation, *, now, lease_seconds):
        key = (reservation.identity.principal, reservation.identity.request_id)
        previous = self.reservations.get(key)
        if previous is not None:
            if previous.request_hash != reservation.request_hash:
                return ReplayClaim(state="changed", reservation=reservation)
            outcome = self.outcomes.get(key)
            return ReplayClaim(
                state="completed" if outcome is not None else "pending",
                reservation=reservation,
                recorded_outcome=outcome,
            )
        self.reservations[key] = reservation
        return ReplayClaim(
            state="dispatch",
            reservation=reservation,
            attempt_token="attempt-1",
        )

    async def record_replay_outcome(
        self, reservation, *, attempt_token, status, body
    ):
        key = (reservation.identity.principal, reservation.identity.request_id)
        self.outcomes[key] = (status, body)

    async def load_primary_escrow_for_listing(self, *, listing_id):
        assert listing_id == self.listing_id
        return {"negotiation_id": "neg-1"}

    async def load_escrow(self, *, escrow_uid):
        assert escrow_uid == "escrow-1"
        return {"negotiation_id": "neg-1"}

    async def load_negotiation_thread_row(self, *, negotiation_id):
        assert negotiation_id == "neg-1"
        return {
            "our_listing_id": self.listing_id,
            "buyer_principal": self.buyer.model_dump(mode="json"),
        }


def _request(
    path: str,
    headers: dict[str, str],
    *,
    method: str = "POST",
    query_string: bytes = b"",
) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "headers": [
                (name.lower().encode(), value.encode()) for name, value in headers.items()
            ],
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )


def _headers(*, signer, operation, resource, body, role, request_id="request-1"):
    timestamp = int(time.time())
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method="POST",
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=timestamp,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": REQUEST_PROTOCOL,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }


def _compose(monkeypatch, *, seller, buyer):
    store = ReplayStore(buyer=buyer.identity)
    monkeypatch.setattr(container, "resolved_marketplace_signer", seller)
    monkeypatch.setattr(container, "resolved_sqlite_client", store)
    return store


async def test_ed25519_seller_close_reserves_replay_and_exact_retry(monkeypatch):
    seller = Ed25519Signer(b"\x01" * 32)
    buyer = Ed25519Signer(b"\x02" * 32)
    store = _compose(monkeypatch, seller=seller, buyer=buyer)
    headers = _headers(
        signer=seller,
        operation="close_listing",
        resource="listing-1",
        body=EMPTY_BODY,
        role="seller",
    )
    request = _request("/api/v1/listings/listing-1/close", headers)
    mutation = await resolve_listing_mutation(request, EMPTY_BODY)
    assert mutation is not None

    first = await authenticate_listing_mutation(request, mutation)
    await store.record_replay_outcome(
        first.reservation,
        attempt_token=first.attempt_token,
        status=200,
        body={"closed": True},
    )
    retry = await authenticate_listing_mutation(request, mutation)

    assert first.dispatch_allowed is True
    assert retry.exact_retry is True
    assert retry.recorded_outcome == (200, {"closed": True})


async def test_reclaim_is_buyer_signed_and_bound_to_durable_payer(monkeypatch):
    seller = Ed25519Signer(b"\x03" * 32)
    buyer = Ed25519Signer(b"\x04" * 32)
    _compose(monkeypatch, seller=seller, buyer=buyer)
    body = {
        "escrow_uid": "escrow-1",
        "payer_principal": buyer.identity.model_dump(mode="json"),
    }
    headers = _headers(
        signer=buyer,
        operation="reclaim_listing",
        resource="listing-1",
        body=body,
        role="buyer",
    )
    request = _request("/api/v1/listings/listing-1/reclaim", headers)
    mutation = await resolve_listing_mutation(request, body)
    assert mutation is not None

    auth = await authenticate_listing_mutation(request, mutation)
    await authorize_listing_mutation(mutation)

    assert auth.principal == buyer.identity
    assert mutation.role == "buyer"


async def test_signed_refund_rejects_buyer_not_in_durable_thread(monkeypatch):
    seller = Ed25519Signer(b"\x05" * 32)
    buyer = Ed25519Signer(b"\x06" * 32)
    other = Ed25519Signer(b"\x07" * 32)
    _compose(monkeypatch, seller=seller, buyer=buyer)
    body = {
        "buyer_principal": other.identity.model_dump(mode="json"),
        "buyer_evm_address": "0x1111111111111111111111111111111111111111",
    }
    headers = _headers(
        signer=seller,
        operation="refund_listing",
        resource="listing-1",
        body=body,
        role="seller",
    )
    request = _request("/api/v1/listings/listing-1/refund", headers)
    mutation = await resolve_listing_mutation(request, body)
    assert mutation is not None
    await authenticate_listing_mutation(request, mutation)

    with pytest.raises(AuthError, match="durable ownership"):
        await authorize_listing_mutation(mutation)


async def test_claim_requires_configured_storefront_principal(monkeypatch):
    seller = Ed25519Signer(b"\x08" * 32)
    buyer = Ed25519Signer(b"\x09" * 32)
    _compose(monkeypatch, seller=seller, buyer=buyer)
    body = {
        "escrow_uid": "escrow-1",
        "fulfillment_uid": "fulfillment-1",
        "claimant_principal": buyer.identity.model_dump(mode="json"),
    }
    headers = _headers(
        signer=seller,
        operation="claim_listing",
        resource="listing-1",
        body=body,
        role="seller",
    )
    request = _request("/api/v1/listings/listing-1/claim", headers)
    mutation = await resolve_listing_mutation(request, body)
    assert mutation is not None
    await authenticate_listing_mutation(request, mutation)

    with pytest.raises(AuthError, match="storefront principal"):
        await authorize_listing_mutation(mutation)


@pytest.mark.parametrize(
    ("path", "operation", "resource", "body"),
    [
        ("/api/v1/listings/create", "create_listing", "", {"listing_id": "listing-1"}),
        (
            "/api/v1/listings/listing-1/close",
            "close_listing",
            "listing-1",
            EMPTY_BODY,
        ),
        (
            "/api/v1/listings/listing-1/arbitrate",
            "arbitrate_listing",
            "listing-1",
            {"decision": True},
        ),
    ],
)
async def test_seller_listing_matrix_uses_exact_operation_and_resource(
    monkeypatch, path, operation, resource, body
):
    seller = Ed25519Signer(b"\x0c" * 32)
    buyer = Ed25519Signer(b"\x0d" * 32)
    _compose(monkeypatch, seller=seller, buyer=buyer)
    headers = _headers(
        signer=seller,
        operation=operation,
        resource=resource,
        body=body,
        role="seller",
    )
    request = _request(path, headers)

    mutation = await resolve_listing_mutation(request, body)
    assert mutation is not None
    auth = await authenticate_listing_mutation(request, mutation)

    assert mutation.operation == operation
    assert mutation.resource == resource
    assert mutation.principal == seller.identity
    assert auth.dispatch_allowed is True


async def test_public_listing_get_is_not_authenticated(monkeypatch):
    seller = Ed25519Signer(b"\x0a" * 32)
    buyer = Ed25519Signer(b"\x0b" * 32)
    _compose(monkeypatch, seller=seller, buyer=buyer)

    assert (
        await resolve_listing_mutation(
            _request("/api/v1/listings/listing-1", {}, method="GET"),
            EMPTY_BODY,
        )
        is None
    )


@pytest.mark.parametrize(
    ("method", "path", "body", "expected"),
    [
        (
            "POST",
            "/api/v1/negotiate/new",
            {"listing_id": "listing-1"},
            ("negotiate_new", "listing-1"),
        ),
        (
            "POST",
            "/api/v1/negotiate/neg-1",
            {},
            ("negotiate_continue", "neg-1"),
        ),
        (
            "POST",
            "/api/v1/deals/deal-1/heartbeat",
            {},
            ("deal_heartbeat", "deal-1"),
        ),
        (
            "POST",
            "/api/v1/settlements",
            {"obligation_ref": "obligation-1"},
            ("settlement_start", "obligation-1"),
        ),
        (
            "GET",
            "/api/v1/settlements/settlement-1",
            EMPTY_BODY,
            ("settlement_status", "settlement-1"),
        ),
        (
            "POST",
            "/api/v1/settlements/settlement-1/reclaim",
            EMPTY_BODY,
            ("settlement_reclaim", "settlement-1"),
        ),
    ],
)
async def test_buyer_route_response_contracts_are_scheme_neutral(
    method, path, body, expected
):
    request = _request(path, {}, method=method)
    assert _buyer_response_contract(request, body) == expected


@pytest.mark.parametrize(
    ("method", "path", "body", "operation", "resource"),
    [
        ("POST", "/api/v1/admin/pause", {}, "admin_pause", ""),
        (
            "PATCH",
            "/api/v1/admin/portfolio/resources/vm-1",
            {"state": "available"},
            "admin_patch_resource",
            "vm-1",
        ),
        (
            "POST",
            "/api/v1/listings/listing-1/negotiations/neg-1/advance",
            {"action": "accept"},
            "admin_advance_negotiation",
            "listing-1/neg-1",
        ),
        (
            "POST",
            "/api/v1/admin/settle/escrow-1/verify",
            {"listing_id": "listing-1"},
            "admin_verify_settlement",
            "escrow-1",
        ),
        (
            "POST",
            "/api/v1/admin/identity/rotations",
            {
                "intent": {
                    "authority": "storefront.administrator",
                    "subject": "operator/a",
                }
            },
            "admin_rotate_identity",
            "storefront.administrator/operator%2Fa",
        ),
        (
            "POST",
            "/api/v1/admin/identity/retirements",
            {
                "authority": "storefront.service-peer",
                "subject": "peer/a",
                "rotation_nonce": "rotate-1",
                "principal": {
                    "scheme": "eip191",
                    "identifier": "0x" + "11" * 20,
                },
            },
            "admin_retire_identity",
            "storefront.service-peer/peer%2Fa",
        ),
    ],
)
async def test_administrator_routes_bind_operation_resource_and_exact_body(
    method, path, body, operation, resource
):
    contract = _admin_contract(_request(path, {}, method=method), body)
    assert contract is not None
    assert contract.operation == operation
    assert contract.resource == resource
    assert contract.body == body


async def test_identity_status_route_binds_sorted_exact_query() -> None:
    request = _request(
        "/api/v1/admin/identity/status",
        {},
        method="GET",
        query_string=(
            b"subject=operator%2Fa&authority=storefront.administrator"
        ),
    )
    contract = _admin_contract(request, EMPTY_BODY)

    assert contract is not None
    assert contract.operation == "admin_identity_status"
    assert contract.resource == (
        "identity-status?authority=storefront.administrator"
        "&subject=operator%2Fa"
    )
    assert contract.body is EMPTY_BODY
