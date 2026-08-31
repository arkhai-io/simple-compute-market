"""HTTP contract coverage for the API-credit service client."""

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


def _request(quantity: int = 2) -> CreditIssuanceRequest:
    return CreditIssuanceRequest.create(
        obligation_ref="e1",
        mechanism="alkahest.v1",
        owner=_PRINCIPAL,
        service="service-main",
        resource_id="q1",
        quantity=quantity,
        key=CreditKeyTarget(mode="new"),
        capacity_reservation_id="r1",
    )


def _response(request: CreditIssuanceRequest) -> dict:
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
        "key_mode": "new",
        "key_id": "k1",
        "balance": request.quantity,
        "request_digest": request.request_digest,
        "committed_at_unix": 2_000_000_000,
        "capacity_reservation_id": "r1",
        "already_issued": False,
        "secret": "k1.private",
    }


@pytest.mark.asyncio
async def test_issue_contract_and_auth_header():
    seen: dict[str, httpx.Request] = {}
    issuance_request = _request()

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=_response(issuance_request))

    client = CreditsServiceClient(
        "http://credits",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.submit_credit_issuance(issuance_request)

    request = seen["request"]
    assert request.url.path == "/api/v1/issuance"
    assert request.headers["X-Admin-Key"] == "secret"
    assert json.loads(request.content)["capacity_reservation_id"] == "r1"
    assert result.key_id == "k1"


@pytest.mark.asyncio
async def test_get_key_not_found_returns_none():
    client = CreditsServiceClient(
        "http://credits",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, request=request)
        ),
    )
    assert await client.get_key("missing") is None


@pytest.mark.asyncio
async def test_http_issuance_error_maps_reason_and_detail():
    client = CreditsServiceClient(
        "http://credits",
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                409,
                json={"error": "quota_exhausted", "detail": "full"},
                request=request,
            )
        ),
    )

    with pytest.raises(CreditsServiceError) as exc_info:
        await client.submit_credit_issuance(_request(quantity=1))

    assert exc_info.value.reason == "quota_exhausted"
    assert exc_info.value.detail == "full"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_rollback_adjusts_then_revokes_new_key():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={}, request=request)

    client = CreditsServiceClient(
        "http://credits",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.rollback_issuance(
        escrow_uid="e",
        issuance={"key_id": "k", "quantity": 3},
        key_mode="new",
    )

    assert paths == ["/api/v1/keys/k/adjust", "/api/v1/keys/k/revoke"]
    assert result["rolled_back"] is True
    assert result["revoked"] is True
