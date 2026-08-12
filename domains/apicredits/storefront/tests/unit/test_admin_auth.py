from __future__ import annotations

import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)

import apicredits_storefront.container as container
from apicredits_storefront.middleware import admin_auth
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
