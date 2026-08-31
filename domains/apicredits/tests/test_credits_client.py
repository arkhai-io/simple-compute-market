"""CreditsServiceClient: request shape, auth header, and error mapping
for all five credits-service operations. The actual callers
(``fulfillment.py``, ``keys_lookup.py``) construct this client directly
and are covered by their own test files, which patch
``CreditsServiceClient``'s methods rather than free-function names.
"""

from __future__ import annotations

import json

import httpx
import pytest
from market_identity import Identity, IdentityScheme

from domains.apicredits.settlement.credits_client import (
    CreditIssuanceRequest,
    CreditKeyTarget,
    CreditsServiceClient,
    CreditsServiceError,
)

_PRINCIPAL = Identity(
    scheme=IdentityScheme.EIP191,
    identifier="0xabcdef0000000000000000000000000000000001",
)


def _request(quantity: int = 10) -> CreditIssuanceRequest:
    return CreditIssuanceRequest.create(
        obligation_ref="esc-1",
        mechanism="alkahest.v1",
        owner=_PRINCIPAL,
        service="test-service",
        resource_id="quota-main",
        quantity=quantity,
        key=CreditKeyTarget(mode="new"),
    )


def _result_payload(request: CreditIssuanceRequest) -> dict:
    return {
        "schema": "arkhai.api-credits.issuance-result.v1",
        "fulfillment_id": request.fulfillment_id,
        "grant_id": request.fulfillment_id,
        "obligation_ref": request.obligation_ref,
        "mechanism": request.mechanism,
        "owner": request.owner.model_dump(mode="json"),
        "service": request.service,
        "resource_id": request.resource_id,
        "quantity": request.quantity,
        "key_mode": request.key.mode,
        "key_id": "k1",
        "balance": request.quantity,
        "request_digest": request.request_digest,
        "committed_at_unix": 2_000_000_000,
        "capacity_reservation_id": "quota-reservation",
        "already_issued": False,
        "secret": "k1.private",
    }


def _client(handler, admin_key: str = "test-admin-key") -> CreditsServiceClient:
    return CreditsServiceClient(
        "http://credits-service:8082",
        admin_key,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_submit_credit_issuance_sends_expected_request():
    captured = {}
    issuance_request = _request()

    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_result_payload(issuance_request))

    client = _client(handle)
    result = await client.submit_credit_issuance(issuance_request)

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/issuance"
    assert captured["headers"]["x-admin-key"] == "test-admin-key"
    assert captured["body"] == issuance_request.model_dump(
        mode="json",
        exclude_none=True,
    )
    assert result.fulfillment_id == issuance_request.fulfillment_id
    assert result.secret == "k1.private"
    assert "secret" not in result.model_dump(mode="json")


@pytest.mark.asyncio
async def test_submit_credit_issuance_raises_typed_error_with_service_reason():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"error": "quota_exhausted", "detail": "no capacity left"},
        )

    client = _client(handle)
    with pytest.raises(CreditsServiceError) as excinfo:
        await client.submit_credit_issuance(_request())

    assert excinfo.value.reason == "quota_exhausted"
    assert excinfo.value.detail == "no capacity left"
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_get_key_returns_none_on_404():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _client(handle)
    assert await client.get_key("missing-key") is None


@pytest.mark.asyncio
async def test_get_key_returns_payload_on_success():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/keys/k1"
        return httpx.Response(200, json={"key_id": "k1", "status": "active"})

    client = _client(handle)
    assert await client.get_key("k1") == {"key_id": "k1", "status": "active"}


@pytest.mark.asyncio
async def test_revoke_key_hits_the_revoke_endpoint():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/keys/k1/revoke"
        assert request.method == "POST"
        return httpx.Response(200, json={"key_id": "k1", "status": "revoked"})

    client = _client(handle)
    result = await client.revoke_key("k1")
    assert result["status"] == "revoked"


@pytest.mark.asyncio
async def test_adjust_key_balance_sends_delta_and_reason():
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"key_id": "k1", "balance": 5})

    client = _client(handle)
    await client.adjust_key_balance("k1", delta=-5, reason="rollback:esc-1")

    assert captured["body"] == {"delta": -5, "reason": "rollback:esc-1"}


@pytest.mark.asyncio
async def test_rollback_issuance_adjusts_and_revokes_a_new_key():
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"key_id": "k1"})

    client = _client(handle)
    result = await client.rollback_issuance(
        escrow_uid="esc-1",
        issuance={"key_id": "k1", "quantity": 10},
        key_mode="new",
    )

    assert result["rolled_back"] is True
    assert result["revoked"] is True
    assert "/api/v1/keys/k1/adjust" in calls
    assert "/api/v1/keys/k1/revoke" in calls


@pytest.mark.asyncio
async def test_rollback_issuance_does_not_revoke_an_existing_key():
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"key_id": "k1"})

    client = _client(handle)
    await client.rollback_issuance(
        escrow_uid="esc-1",
        issuance={"key_id": "k1", "quantity": 10},
        key_mode="existing",
    )

    assert "/api/v1/keys/k1/revoke" not in calls


@pytest.mark.asyncio
async def test_rollback_issuance_is_a_no_op_with_nothing_to_roll_back():
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call should be made")

    client = _client(handle)
    result = await client.rollback_issuance(
        escrow_uid="esc-1",
        issuance={},
        key_mode="new",
    )

    assert result == {
        "key_id": "",
        "rolled_back": False,
        "reason": "nothing_to_roll_back",
    }
