from __future__ import annotations

import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from market_identity import (
    AuthenticatedResponse,
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

import apicredits_storefront.container as container
from apicredits_storefront.middleware import admin_auth
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.utils.sqlite_client import SQLiteClient


def _headers(signer: Ed25519Signer, request_id: str) -> dict[str, str]:
    signed = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="admin",
            principal=signer.identity,
            method="GET",
            operation="protected",
            resource="/protected",
            request_id=request_id,
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(EMPTY_BODY),
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


def test_admin_routes_require_exact_v2_principal_and_reject_replay(
    tmp_path,
    monkeypatch,
) -> None:
    rotated_signer = Ed25519Signer(bytes.fromhex("55" * 32))
    stranger = Ed25519Signer(bytes.fromhex("66" * 32))
    signer = Ed25519Signer(bytes.fromhex("44" * 32))
    db = SQLiteClient(db_path=str(tmp_path / "admin-auth.db"))
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(
            identities=(signer.identity, rotated_signer.identity),
        ),
    )

    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(admin_auth.require_admin_principal)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    headers = _headers(signer, "admin-request-1")
    with TestClient(app) as client:
        assert client.get("/protected", headers={"X-Admin-Key": "legacy"}).status_code == 401
        assert client.get("/protected", headers=headers).json() == {"ok": True}
        assert client.get(
            "/protected",
            headers=_headers(rotated_signer, "admin-request-2"),
        ).json() == {"ok": True}
        assert client.get(
            "/protected",
            headers=_headers(stranger, "admin-request-3"),
        ).status_code == 403
        assert client.get("/protected", headers=headers).status_code == 409


def test_a_refused_admin_can_verify_the_refusal(tmp_path, monkeypatch) -> None:
    """A refusal the caller must discard tells it nothing it can act on.

    The route's operation and resource and the caller's own request identity
    are known before trust is decided, so the refusal is bindable even though
    the caller is not trusted.
    """

    signer = Ed25519Signer(bytes.fromhex("44" * 32))
    stranger = Ed25519Signer(bytes.fromhex("66" * 32))
    storefront = Ed25519Signer(bytes.fromhex("77" * 32))
    db = SQLiteClient(db_path=str(tmp_path / "admin-refusal.db"))
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_marketplace_signer", storefront)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(signer.identity,)),
    )

    app = FastAPI()
    app.middleware("http")(authenticate_response)

    @app.get("/protected", dependencies=[Depends(admin_auth.require_admin_principal)])
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    headers = _headers(stranger, "admin-refusal-1")
    with TestClient(app) as client:
        refused = client.get("/protected", headers=headers)
        anonymous = client.get("/protected")

    assert refused.status_code == 403
    payload = refused.json()
    signed = AuthenticatedResponse.model_validate(
        {
            "protocol": refused.headers["X-Market-Signature-Version"],
            "role": refused.headers["X-Market-Role"],
            "principal": {
                "scheme": refused.headers["X-Market-Identity-Scheme"],
                "identifier": refused.headers["X-Market-Identity-Identifier"],
            },
            "method": "GET",
            "operation": "protected",
            "resource": "/protected",
            "request_id": refused.headers["X-Market-Request-ID"],
            "timestamp": int(refused.headers["X-Market-Timestamp"]),
            "status": refused.status_code,
            "body_hash": canonical_body_hash(payload),
            "proof": {
                "scheme": refused.headers["X-Market-Identity-Scheme"],
                "value": refused.headers["X-Market-Signature"],
            },
        }
    )
    verification = verify_response(
        signed,
        body=payload,
        now=int(time.time()),
        max_skew=300,
        expected_role="seller",
        expected_principals=TrustedIdentitySet(identities=(storefront.identity,)),
        expected_method="GET",
        expected_operation="protected",
        expected_resource="/protected",
        expected_request_id="admin-refusal-1",
    )
    assert verification.verified, verification.code

    # No request identity to bind, so nothing is signed against an invented one.
    assert anonymous.status_code == 401
    assert "X-Market-Signature" not in anonymous.headers
