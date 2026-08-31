"""_register_seed_quota: delegates to the typed capacity-administration
client rather than constructing its own HTTP request.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from core_storefront.auth import signed_response_headers
from market_identity import Ed25519Signer, TrustedIdentitySet

from apicredits_storefront import startup



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

    monkeypatch.setattr(
        startup,
        "_capacity_authority_site",
        lambda: SimpleNamespace(
            url="http://credits-service:8082",
            expected_authorities=TrustedIdentitySet(
                identities=(_AUTHORITY_SIGNER.identity,),
            ),
        ),
    )
    import apicredits_storefront.container as container
    monkeypatch.setattr(container, "resolved_marketplace_signer", _SELLER_SIGNER)

    import market_site_client
    real_client_cls = market_site_client.SiteCapacityAdminClient

    def _client_with_test_transport(
        base_url,
        *,
        signer,
        expected_authorities,
        **kwargs,
    ):
        return real_client_cls(
            base_url,
            signer=signer,
            expected_authorities=expected_authorities,
            timeout=kwargs["timeout"],
            max_timestamp_skew=kwargs["max_timestamp_skew"],
            transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(
        market_site_client, "SiteCapacityAdminClient", _client_with_test_transport,
    )

    await startup._register_seed_quota(resource_id="demo-quota", total_units=100)

    assert captured["path"] == "/api/v1/capacity/resources/demo-quota"
    assert captured["headers"]["x-market-role"] == "seller"
    assert captured["body"]["total_units"] == 100
    assert captured["body"]["resource_type"] == "api_credits"


@pytest.mark.asyncio
async def test_register_seed_quota_raises_runtime_error_on_client_failure(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        return _signed_response(request, status=500, body="ledger unavailable")

    monkeypatch.setattr(
        startup,
        "_capacity_authority_site",
        lambda: SimpleNamespace(
            url="http://credits-service:8082",
            expected_authorities=TrustedIdentitySet(
                identities=(_AUTHORITY_SIGNER.identity,),
            ),
        ),
    )
    import apicredits_storefront.container as container
    monkeypatch.setattr(container, "resolved_marketplace_signer", _SELLER_SIGNER)

    import market_site_client
    real_client_cls = market_site_client.SiteCapacityAdminClient

    def _client_with_test_transport(
        base_url,
        *,
        signer,
        expected_authorities,
        **kwargs,
    ):
        return real_client_cls(
            base_url,
            signer=signer,
            expected_authorities=expected_authorities,
            timeout=kwargs["timeout"],
            max_timestamp_skew=kwargs["max_timestamp_skew"],
            transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(
        market_site_client, "SiteCapacityAdminClient", _client_with_test_transport,
    )

    with pytest.raises(RuntimeError, match="demo-quota"):
        await startup._register_seed_quota(resource_id="demo-quota", total_units=100)
