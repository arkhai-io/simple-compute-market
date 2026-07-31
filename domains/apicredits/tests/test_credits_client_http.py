"""HTTP contract coverage for the API-credit service client."""

from __future__ import annotations

import json

import httpx
import pytest

from domains.apicredits.settlement.credits_client import (
    CreditsServiceClient,
    CreditsServiceError,
)


@pytest.mark.asyncio
async def test_issue_contract_and_auth_header():
    seen: dict[str, httpx.Request] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"key_id": "k1", "quantity": 2})

    client = CreditsServiceClient(
        "http://credits",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.submit_credit_issuance(
        escrow_uid="e1",
        quantity=2,
        key_mode="new",
        buyer_wallet="0x1",
        capacity_reservation_id="r1",
        resource_id="q1",
    )

    request = seen["request"]
    assert request.url.path == "/api/v1/issuance"
    assert request.headers["X-Admin-Key"] == "secret"
    assert json.loads(request.content)["capacity_reservation_id"] == "r1"
    assert result["key_id"] == "k1"


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
        await client.submit_credit_issuance(
            escrow_uid="e",
            quantity=1,
        )

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
