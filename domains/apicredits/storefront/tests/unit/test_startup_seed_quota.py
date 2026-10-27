"""The seed's quota registration: through the typed capacity-administration
client, in the credits authority's default pool, as an API-credits resource.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from core_storefront.auth import signed_response_headers
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_site_client import SiteCapacityAdminClient

import apicredits_storefront.container as container
from apicredits_storefront import server


_SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
_AUTHORITY_SIGNER = Ed25519Signer(bytes.fromhex("33" * 32))


def _signed_response(
    request: httpx.Request,
    *,
    status: int,
    body,
) -> httpx.Response:
    headers = signed_response_headers(
        signer=_AUTHORITY_SIGNER,
        role="service",
        method=request.method,
        operation="capacity_resource_put",
        resource="demo-quota",
        request_id=request.headers["X-Market-Request-ID"],
        status=status,
        body=body,
    )
    return (
        httpx.Response(status, json=body, headers=headers)
        if isinstance(body, dict)
        else httpx.Response(status, text=body, headers=headers)
    )

def _seed(handle):
    def client(base_url, *, signer, expected_authorities, **kwargs):
        return SiteCapacityAdminClient(
            base_url,
            signer=signer,
            expected_authorities=expected_authorities,
            timeout=kwargs["timeout"],
            max_timestamp_skew=kwargs["max_timestamp_skew"],
            transport=httpx.MockTransport(handle),
        )

    return replace(
        server.listing_seed(),
        admin_client=client,
        site=lambda: SimpleNamespace(
            url="http://credits-service:8082",
            expected_authorities=TrustedIdentitySet(
                identities=(_AUTHORITY_SIGNER.identity,),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_register_seed_quota_sends_expected_request_via_the_typed_client(monkeypatch):
    captured = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return _signed_response(
            request,
            status=200,
            body={"resource_id": "demo-quota"},
        )

    monkeypatch.setattr(container, "resolved_marketplace_signer", _SELLER_SIGNER)

    await _seed(handle).register_quota(resource_id="demo-quota", total_units=100)

    assert captured["path"] == "/api/v1/capacity/resources/demo-quota"
    assert captured["headers"]["x-market-role"] == "seller"
    # Declared explicitly in the quota's own dimension, in its pool.
    assert captured["body"]["capacity"] == {"units": 100}
    assert captured["body"]["pool_id"] == "default"
    assert captured["body"]["resource_type"] == "api_credits"


@pytest.mark.asyncio
async def test_register_seed_quota_raises_runtime_error_on_client_failure(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        return _signed_response(request, status=500, body="ledger unavailable")

    monkeypatch.setattr(container, "resolved_marketplace_signer", _SELLER_SIGNER)

    with pytest.raises(RuntimeError, match="demo-quota"):
        await _seed(handle).register_quota(resource_id="demo-quota", total_units=100)
