"""Focused identity contract tests for provisioning service callbacks."""

from __future__ import annotations

import time

import pytest
from fastapi import Request
from market_identity import (
    REQUEST_PROTOCOL,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    TrustedIdentitySet,
    sign_request,
)

import market_storefront.container as container
from core_storefront.auth import AuthError
from core_storefront.identity_authority import StorefrontIdentityAuthority
from core_storefront.sqlite_client import SQLiteClient
from market_storefront.middleware.service_peer_auth import (
    _authenticate,
    _callback,
)

pytestmark = pytest.mark.asyncio
_SERVICE_SIGNER = Ed25519Signer(bytes(range(32)))
_SELLER_SIGNER = Ed25519Signer(bytes(range(1, 33)))
_SERVICE_PRINCIPAL = _SERVICE_SIGNER.identity
_SERVICE_AUTHORITIES = TrustedIdentitySet(identities=(_SERVICE_PRINCIPAL,))



def _request(path: str, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (name.lower().encode(), value.encode())
                for name, value in headers.items()
            ],
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )


def _headers(*, signer, operation, resource, body, role="service"):
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method="POST",
            operation=operation,
            resource=resource,
            request_id=f"{operation}-request",
            timestamp=int(time.time()),
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


def _compose(tmp_path, monkeypatch):
    db = SQLiteClient(str(tmp_path / "storefront.db"))
    service = _SERVICE_SIGNER
    seller = _SELLER_SIGNER
    StorefrontIdentityAuthority(db.db_path).register_service_peer(
        peer_id="provisioning-home",
        role="service",
        site_id="home",
        principal=_SERVICE_PRINCIPAL,
        now=int(time.time()),
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_marketplace_signer", seller)
    monkeypatch.setattr(
        "market_storefront.middleware.service_peer_auth.get_service_peer_configs",
        lambda: {
            "provisioning-home": (
                "service",
                "home",
                _SERVICE_AUTHORITIES,
            )
        },
    )
    return db, service


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        (
            "/api/v1/admin/fulfillment/events/capacity-released",
            "fulfillment_capacity_released",
        ),
        (
            "/api/v1/admin/fulfillment/events/usage-started",
            "fulfillment_usage_started",
        ),
        ("/api/v1/admin/fulfillment/events/failed", "fulfillment_failed"),
    ],
)
async def test_ed25519_service_callback_binds_site_role_body_and_replay(
    tmp_path, monkeypatch, path, operation
):
    db, service = _compose(tmp_path, monkeypatch)
    body = {"capacity_reservation_id": "reservation-1", "site_id": "home"}
    request = _request(
        path,
        _headers(
            signer=service,
            operation=operation,
            resource="reservation-1",
            body=body,
        ),
    )
    callback = _callback(request, body)
    assert callback is not None

    first = await _authenticate(request=request, callback=callback)
    await db.record_replay_outcome(
        first.reservation,
        attempt_token=first.attempt_token,
        status=200,
        body={"ok": True},
    )
    retry = await _authenticate(request=request, callback=callback)

    assert first.dispatch_allowed is True
    assert first.principal == service.identity
    assert retry.exact_retry is True
    assert retry.recorded_outcome == (200, {"ok": True})


async def test_service_callback_rejects_body_mutation_cross_role_and_unknown_site(
    tmp_path, monkeypatch
):
    _, service = _compose(tmp_path, monkeypatch)
    path = "/api/v1/admin/fulfillment/events/failed"
    signed_body = {"capacity_reservation_id": "reservation-1", "site_id": "home"}

    mutated = {**signed_body, "reason": "mutated after signing"}
    request = _request(
        path,
        _headers(
            signer=service,
            operation="fulfillment_failed",
            resource="reservation-1",
            body=signed_body,
        ),
    )
    callback = _callback(request, mutated)
    assert callback is not None
    with pytest.raises(AuthError, match="Invalid marketplace signature"):
        await _authenticate(request=request, callback=callback)

    wrong_role_request = _request(
        path,
        _headers(
            signer=service,
            operation="fulfillment_failed",
            resource="reservation-1",
            body=signed_body,
            role="seller",
        ),
    )
    callback = _callback(wrong_role_request, signed_body)
    assert callback is not None
    with pytest.raises(AuthError, match="role"):
        await _authenticate(request=wrong_role_request, callback=callback)

    unknown_site_body = {**signed_body, "site_id": "other"}
    unknown_site_request = _request(
        path,
        _headers(
            signer=service,
            operation="fulfillment_failed",
            resource="reservation-1",
            body=unknown_site_body,
        ),
    )
    callback = _callback(unknown_site_request, unknown_site_body)
    assert callback is not None
    with pytest.raises(AuthError, match="configured service peer"):
        await _authenticate(request=unknown_site_request, callback=callback)
