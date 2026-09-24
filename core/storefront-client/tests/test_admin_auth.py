import asyncio
import json
import urllib.parse

import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    RotationIntent,
    TrustedIdentitySet,
    SignatureProof,
    canonical_body_hash,
    sign_response,
    sign_rotation,
    verify_request,
)

from storefront_client.auth import (
    AUTH_HEADERS,
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from storefront_client.client import StorefrontClient, SyncStorefrontClient
from storefront_client.models import NegotiationSummary

_SIGNER = Ed25519Signer(bytes(range(32)))
_PUBLISHER = Ed25519Signer(bytes(range(1, 33)))
_REPLACEMENT = Ed25519Signer(bytes(range(2, 34)))


def _request_body(request: httpx.Request):
    return json.loads(request.content) if request.content else EMPTY_BODY


def _response_context(request: httpx.Request) -> tuple[str, str]:
    body = _request_body(request)
    path = request.url.path
    if path.endswith("/pool-overrides"):
        return _pool_override_context(request, body)
    if request.method == "PATCH":
        return "admin_patch_resource", "resource-1"
    if path.endswith("/identity/rotations"):
        intent = body["intent"]
        resource = "/".join(
            urllib.parse.quote(value, safe="")
            for value in (intent["authority"], intent["subject"])
        )
        return "admin_rotate_identity", resource
    if path.endswith("/identity/retirements"):
        resource = "/".join(
            urllib.parse.quote(value, safe="")
            for value in (body["authority"], body["subject"])
        )
        return "admin_retire_identity", resource
    query = urllib.parse.urlencode(
        sorted(request.url.params.multi_items()),
        quote_via=urllib.parse.quote,
        safe="",
    )
    if path.endswith("/identity/status"):
        return "admin_identity_status", f"identity-status?{query}"
    return "admin_list_negotiations", f"listing-1/negotiations?{query}"


def _pool_override_context(request: httpx.Request, body) -> tuple[str, str]:
    """The storefront's contract for the override routes, rebuilt independently."""
    if request.method in ("PUT", "DELETE"):
        values = body if request.method == "PUT" else dict(request.url.params)
        resource = "/".join(
            urllib.parse.quote(values[name], safe="") for name in ("site_id", "pool_id")
        )
        operation = (
            "admin_put_pool_override" if request.method == "PUT"
            else "admin_delete_pool_override"
        )
        return operation, resource
    params = dict(request.url.params)
    query = urllib.parse.urlencode(
        sorted(params.items()), quote_via=urllib.parse.quote, safe=""
    )
    operation = (
        "admin_get_pool_override" if "pool_id" in params else "admin_list_pool_overrides"
    )
    return operation, f"pool-overrides?{query}"


def _pool_override_body(request: httpx.Request) -> dict:
    override = {"site_id": "a", "pool_id": "b", "created_at": "t", "updated_at": "t"}
    if request.method == "PUT":
        return {
            "override": {**_request_body(request), "created_at": "t", "updated_at": "t"},
            "feasibility": [],
            "projection": {"revision": 3, "digest": "d3"},
        }
    if request.method == "DELETE":
        return {**dict(request.url.params), "deleted": True}
    if "pool_id" in request.url.params:
        return {"override": override}
    return {"overrides": [override]}


def _response_body(request: httpx.Request) -> dict:
    if request.url.path.endswith("/pool-overrides"):
        return _pool_override_body(request)
    if "/identity/" not in request.url.path:
        return {}
    body = _request_body(request)
    if request.url.path.endswith("/rotations"):
        authority = body["intent"]["authority"]
        subject = body["intent"]["subject"]
    elif request.url.path.endswith("/retirements"):
        authority = body["authority"]
        subject = body["subject"]
    else:
        authority = request.url.params["authority"]
        subject = request.url.params["subject"]
    return {
        "authority": authority,
        "subject": subject,
        "role": "admin",
        "primary": _REPLACEMENT.identity.model_dump(mode="json"),
        "observed_at": 1_000,
        "bindings": [
            {
                "principal": _REPLACEMENT.identity.model_dump(mode="json"),
                "status": "primary",
                "overlap_until": None,
                "active": True,
            }
        ],
    }


def _signed_response(request: httpx.Request) -> httpx.Response:
    body = _response_body(request)
    operation, resource = _response_context(request)
    authenticated = sign_response(
        signer=_PUBLISHER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_PUBLISHER.identity,
            method=request.method,
            operation=operation,
            resource=resource,
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            status=200,
            body_hash=canonical_body_hash(body),
        ),
    )
    headers = {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }
    return httpx.Response(200, json=body, headers=headers, request=request)


class _AsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return _signed_response(request)


class _SyncTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return _signed_response(request)


def _envelope(request: httpx.Request, *, operation: str, resource: str, body):
    scheme = request.headers[IDENTITY_SCHEME_HEADER]
    return AuthenticatedRequest(
        protocol=request.headers[SIGNATURE_VERSION_HEADER],
        role=request.headers[ROLE_HEADER],
        principal=Identity(
            scheme=scheme,
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        ),
        method=request.method,
        operation=operation,
        resource=resource,
        request_id=request.headers[REQUEST_ID_HEADER],
        timestamp=int(request.headers[TIMESTAMP_HEADER]),
        body_hash=canonical_body_hash(body),
        proof=SignatureProof(
            scheme=scheme,
            value=request.headers[SIGNATURE_HEADER],
        ),
    )


def test_admin_patch_sync_async_contract_is_byte_equivalent(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport = _AsyncTransport()
    sync_transport = _SyncTransport()

    async def run() -> None:
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(
                identities=(_PUBLISHER.identity,)
            ),
            transport=async_transport,
        ) as client:
            await client.patch_resource(
                "resource-1",
                state="available",
                attributes={"lease_end_utc": None},
                request_id="admin-patch-1",
            )

    asyncio.run(run())
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(
            identities=(_PUBLISHER.identity,)
        ),
        transport=sync_transport,
    ) as client:
        client.patch_resource(
            "resource-1",
            state="available",
            attributes={"lease_end_utc": None},
            request_id="admin-patch-1",
        )

    async_request = async_transport.requests[0]
    sync_request = sync_transport.requests[0]
    assert async_request.content == sync_request.content
    for name in AUTH_HEADERS:
        assert async_request.headers[name] == sync_request.headers[name]
    body = json.loads(async_request.content)
    result = verify_request(
        _envelope(
            async_request,
            operation="admin_patch_resource",
            resource="resource-1",
            body=body,
        ),
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="admin",
        expected_method="PATCH",
        expected_operation="admin_patch_resource",
        expected_resource="resource-1",
        expected_principals=TrustedIdentitySet(
            identities=(_SIGNER.identity,)
        ),
    )
    assert result.verified


def test_admin_list_negotiations_binds_effective_canonical_query(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    transport = _SyncTransport()
    buyer = Ed25519Signer(bytes(range(2, 34))).identity
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(
            identities=(_PUBLISHER.identity,)
        ),
        transport=transport,
    ) as client:
        client.list_negotiations(
            "listing-1",
            terminal_state="accepted",
            buyer_principal=buyer,
            request_id="admin-list-1",
        )

    request = transport.requests[0]
    query = urllib.parse.urlencode(
        [
            ("buyer_identifier", buyer.identifier),
            ("buyer_scheme", buyer.scheme.value),
            ("limit", "50"),
            ("offset", "0"),
            ("terminal_state", "accepted"),
        ],
        quote_via=urllib.parse.quote,
        safe="",
    )
    resource = f"listing-1/negotiations?{query}"
    result = verify_request(
        _envelope(
            request,
            operation="admin_list_negotiations",
            resource=resource,
            body=EMPTY_BODY,
        ),
        now=1_000,
        max_skew=0,
        expected_role="admin",
        expected_method="GET",
        expected_operation="admin_list_negotiations",
        expected_resource=resource,
        expected_principals=TrustedIdentitySet(
            identities=(_SIGNER.identity,)
        ),
    )
    assert result.verified
    assert "buyer_address" not in request.url.params


def test_negotiation_summary_exposes_scheme_tagged_buyer_principal():
    buyer = Ed25519Signer(bytes(range(2, 34))).identity
    seller = Ed25519Signer(bytes(range(3, 35))).identity
    summary = NegotiationSummary.from_dict(
        {
            "negotiation_id": "neg-1",
            "buyer_principal": buyer.model_dump(mode="json"),
            "seller_principal": seller.model_dump(mode="json"),
        }
    )
    assert summary.buyer_principal == buyer
    assert summary.seller_principal == seller
    assert "buyer_principal" not in summary.extra
    assert "seller_principal" not in summary.extra


def test_identity_rotation_sync_async_contract_is_byte_equivalent(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    authority = "storefront.administrator"
    subject = "tenant/admin"
    rotation = sign_rotation(
        current_signer=_SIGNER,
        replacement_signer=_REPLACEMENT,
        intent=RotationIntent(
            current=_SIGNER.identity,
            replacement=_REPLACEMENT.identity,
            subject=subject,
            authority=authority,
            nonce="rotation-1",
            overlap_seconds=300,
            expires_at=2_000,
        ),
    )
    publishers = TrustedIdentitySet(
        identities=(_PUBLISHER.identity,)
    )
    async_transport = _AsyncTransport()
    sync_transport = _SyncTransport()

    async def run() -> None:
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="admin",
            expected_publishers=publishers,
            transport=async_transport,
        ) as client:
            started = await client.admin_initiate_identity_rotation(
                authority=authority,
                subject=subject,
                current_signer=_SIGNER,
                replacement_signer=_REPLACEMENT,
                nonce="rotation-1",
                overlap_seconds=300,
                expires_at=2_000,
                request_id="rotate-1",
            )
            assert started.primary == _REPLACEMENT.identity
        async with StorefrontClient(
            "http://test",
            signer=_REPLACEMENT,
            caller_role="admin",
            expected_publishers=publishers,
            transport=async_transport,
        ) as client:
            await client.admin_complete_identity_rotation(
                rotation=rotation,
                request_id="retire-1",
            )
            status = await client.admin_get_identity_status(
                authority=authority,
                subject=subject,
                request_id="status-1",
            )
            assert status.observed_at == 1_000
            assert status.bindings[0].active is True

    asyncio.run(run())
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="admin",
        expected_publishers=publishers,
        transport=sync_transport,
    ) as client:
        client.admin_initiate_identity_rotation(
            authority=authority,
            subject=subject,
            current_signer=_SIGNER,
            replacement_signer=_REPLACEMENT,
            nonce="rotation-1",
            overlap_seconds=300,
            expires_at=2_000,
            request_id="rotate-1",
        )
    with SyncStorefrontClient(
        "http://test",
        signer=_REPLACEMENT,
        caller_role="admin",
        expected_publishers=publishers,
        transport=sync_transport,
    ) as client:
        client.admin_complete_identity_rotation(
            rotation=rotation,
            request_id="retire-1",
        )
        client.admin_get_identity_status(
            authority=authority,
            subject=subject,
            request_id="status-1",
        )

    assert len(async_transport.requests) == len(sync_transport.requests) == 3
    expected = (
        (
            "POST",
            "admin_rotate_identity",
            "storefront.administrator/tenant%2Fadmin",
            _SIGNER.identity,
        ),
        (
            "POST",
            "admin_retire_identity",
            "storefront.administrator/tenant%2Fadmin",
            _REPLACEMENT.identity,
        ),
        (
            "GET",
            "admin_identity_status",
            (
                "identity-status?"
                "authority=storefront.administrator&subject=tenant%2Fadmin"
            ),
            _REPLACEMENT.identity,
        ),
    )
    for async_request, sync_request, contract in zip(
        async_transport.requests,
        sync_transport.requests,
        expected,
        strict=True,
    ):
        method, operation, resource, principal = contract
        assert async_request.content == sync_request.content
        for name in AUTH_HEADERS:
            assert async_request.headers[name] == sync_request.headers[name]
        body = _request_body(async_request)
        result = verify_request(
            _envelope(
                async_request,
                operation=operation,
                resource=resource,
                body=body,
            ),
            body=body,
            now=1_000,
            max_skew=0,
            expected_role="admin",
            expected_method=method,
            expected_operation=operation,
            expected_resource=resource,
            expected_principals=TrustedIdentitySet(
                identities=(principal,)
            ),
        )
        assert result.verified

    assert _request_body(async_transport.requests[0]) == rotation.model_dump(
        mode="json"
    )


def test_administrator_rotation_rejects_wrong_outer_signer():
    rotation = sign_rotation(
        current_signer=_SIGNER,
        replacement_signer=_REPLACEMENT,
        intent=RotationIntent(
            current=_SIGNER.identity,
            replacement=_REPLACEMENT.identity,
            subject="admin-1",
            authority="storefront.administrator",
            nonce="rotation-1",
            overlap_seconds=300,
            expires_at=2_000,
        ),
    )
    publishers = TrustedIdentitySet(
        identities=(_PUBLISHER.identity,)
    )
    transport = _SyncTransport()
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="admin",
        expected_publishers=publishers,
        transport=transport,
    ) as client:
        with pytest.raises(ValueError, match="completion"):
            client.admin_complete_identity_rotation(rotation=rotation)
    with SyncStorefrontClient(
        "http://test",
        signer=_REPLACEMENT,
        caller_role="admin",
        expected_publishers=publishers,
        transport=transport,
    ) as client:
        with pytest.raises(ValueError, match="initiation"):
            client.admin_initiate_identity_rotation(
                authority="storefront.administrator",
                subject="admin-1",
                current_signer=_SIGNER,
                replacement_signer=_REPLACEMENT,
                nonce="rotation-1",
                overlap_seconds=300,
                expires_at=2_000,
            )
    assert transport.requests == []


# IDs chosen to contain every delimiter a naive join or query would confuse.
_SITE = "site/a?b"
_POOL = "pool&c=d%e"


def _admin_clients(async_transport, sync_transport):
    publishers = TrustedIdentitySet(identities=(_PUBLISHER.identity,))
    return (
        StorefrontClient(
            "http://test", signer=_SIGNER, caller_role="admin",
            expected_publishers=publishers, transport=async_transport,
        ),
        SyncStorefrontClient(
            "http://test", signer=_SIGNER, caller_role="admin",
            expected_publishers=publishers, transport=sync_transport,
        ),
    )


def _verify(request, *, method, operation, resource, body=EMPTY_BODY):
    result = verify_request(
        _envelope(request, operation=operation, resource=resource, body=body),
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="admin",
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_principals=TrustedIdentitySet(identities=(_SIGNER.identity,)),
    )
    assert result.verified


def test_pool_override_requests_are_byte_equivalent_across_variants(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport, sync_transport = _AsyncTransport(), _SyncTransport()
    async_client, sync_client = _admin_clients(async_transport, sync_transport)
    record = {"site_id": _SITE, "pool_id": _POOL, "sla": 99.0}

    async def run() -> None:
        async with async_client as client:
            await client.admin_put_pool_override(record, request_id="put-1")
            await client.admin_get_pool_override(_SITE, _POOL, request_id="get-1")
            await client.admin_list_pool_overrides(site_id=_SITE, request_id="list-1")
            await client.admin_delete_pool_override(_SITE, _POOL, request_id="del-1")

    asyncio.run(run())
    with sync_client as client:
        client.admin_put_pool_override(record, request_id="put-1")
        client.admin_get_pool_override(_SITE, _POOL, request_id="get-1")
        client.admin_list_pool_overrides(site_id=_SITE, request_id="list-1")
        client.admin_delete_pool_override(_SITE, _POOL, request_id="del-1")

    for async_request, sync_request in zip(
        async_transport.requests, sync_transport.requests, strict=True
    ):
        assert async_request.method == sync_request.method
        assert async_request.url == sync_request.url
        assert async_request.content == sync_request.content
        for name in AUTH_HEADERS:
            assert async_request.headers[name] == sync_request.headers[name]


def test_pool_override_requests_sign_the_storefronts_resources(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    transport = _SyncTransport()
    _, client = _admin_clients(_AsyncTransport(), transport)
    record = {"site_id": _SITE, "pool_id": _POOL}
    encoded = "site%2Fa%3Fb/pool%26c%3Dd%25e"

    with client:
        written = client.admin_put_pool_override(record)
        client.admin_get_pool_override(_SITE, _POOL)
        listed = client.admin_list_pool_overrides()
        deleted = client.admin_delete_pool_override(_SITE, _POOL)

    put, get, list_all, delete = transport.requests
    _verify(put, method="PUT", operation="admin_put_pool_override",
            resource=encoded, body=record)
    _verify(get, method="GET", operation="admin_get_pool_override",
            resource="pool-overrides?pool_id=pool%26c%3Dd%25e&site_id=site%2Fa%3Fb")
    _verify(list_all, method="GET", operation="admin_list_pool_overrides",
            resource="pool-overrides?")
    _verify(delete, method="DELETE", operation="admin_delete_pool_override",
            resource=encoded)
    assert (written.projection_revision, written.projection_digest) == (3, "d3")
    assert [o.pool_id for o in listed.overrides] == ["b"]
    assert deleted.deleted is True


def test_a_pool_override_without_its_address_is_refused_before_sending():
    transport = _SyncTransport()
    _, client = _admin_clients(_AsyncTransport(), transport)

    with client, pytest.raises(ValueError):
        client.admin_put_pool_override({"site_id": _SITE})

    assert transport.requests == []
