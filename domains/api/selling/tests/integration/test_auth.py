"""Administrator authentication and response signing over injected collaborators.

The authentication is mounted on an application assembled here, over a real
core SQLite client as its replay store and a neutral storefront's signer and
administrators; the buyer and seller verifications are exercised by each
storefront's own suite through its bindings.
"""

from __future__ import annotations

import time

import pytest
from core_storefront.sqlite_client import SQLiteClient
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Ed25519Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

from arkhai_api_selling.auth import StorefrontAuth

# Deterministic development keys for these tests only; never used on any network.
ADMIN = Ed25519Signer(bytes.fromhex("44" * 32))
ROTATED_ADMIN = Ed25519Signer(bytes.fromhex("55" * 32))
STRANGER = Ed25519Signer(bytes.fromhex("66" * 32))
STOREFRONT = Ed25519Signer(bytes.fromhex("77" * 32))


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


@pytest.fixture
def storefront(tmp_path):
    """A factory for an application whose one route admits the injected administrators.

    With ``signed``, the storefront's response signing records each first
    dispatch, so an exact retry replays it; without, a retry finds a
    reservation and no outcome.
    """
    db = SQLiteClient(db_path=str(tmp_path / "auth.db"))
    state = {"store": db, "signer": STOREFRONT, "admins": (ADMIN.identity, ROTATED_ADMIN.identity)}
    auth = StorefrontAuth(
        replay_store=lambda: state["store"],
        signer=lambda: state["signer"],
        admin_principals=lambda: TrustedIdentitySet(identities=state["admins"]),
        seller_principal=lambda: STOREFRONT.identity,
    )

    def build(*, signed: bool = True):
        app = FastAPI()
        if signed:
            app.middleware("http")(auth.sign_responses)

        @app.get("/protected", dependencies=[Depends(auth.require_admin_principal)])
        async def protected() -> dict[str, bool]:
            return {"ok": True}

        return app, state

    return build


def test_admin_routes_require_exact_v2_principal_and_reject_replay(storefront) -> None:
    app, _state = storefront(signed=False)
    headers = _headers(ADMIN, "admin-request-1")
    with TestClient(app) as client:
        assert client.get("/protected", headers={"X-Admin-Key": "legacy"}).status_code == 401
        assert client.get("/protected", headers=headers).json() == {"ok": True}
        assert client.get("/protected", headers=_headers(ROTATED_ADMIN, "admin-request-2")).json() == {"ok": True}
        assert client.get("/protected", headers=_headers(STRANGER, "admin-request-3")).status_code == 403
        assert client.get("/protected", headers=headers).status_code == 409


def test_a_refused_admin_can_verify_the_refusal(storefront) -> None:
    """A refusal the caller must discard tells it nothing it can act on.

    The route's operation and resource and the caller's own request identity
    are known before trust is decided, so the refusal is bindable even though
    the caller is not trusted.
    """
    app, _state = storefront()
    headers = _headers(STRANGER, "admin-refusal-1")
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
        expected_principals=TrustedIdentitySet(identities=(STOREFRONT.identity,)),
        expected_method="GET",
        expected_operation="protected",
        expected_resource="/protected",
        expected_request_id="admin-refusal-1",
    )
    assert verification.verified, verification.code

    # No request identity to bind, so nothing is signed against an invented one.
    assert anonymous.status_code == 401
    assert "X-Market-Signature" not in anonymous.headers


def test_an_uninitialized_storefront_refuses_before_reading_the_request(storefront) -> None:
    app, state = storefront()
    state["store"] = None
    with TestClient(app) as client:
        refused = client.get("/protected", headers=_headers(ADMIN, "admin-request-9"))
    assert refused.status_code == 503
    assert refused.json() == {"detail": "storefront is not initialized"}


def test_an_exact_retry_of_a_signed_outcome_replays_it(storefront) -> None:
    app, _state = storefront()
    headers = _headers(ADMIN, "admin-request-1")
    with TestClient(app) as client:
        first = client.get("/protected", headers=headers)
        retried = client.get("/protected", headers=headers)
    assert (first.status_code, first.json()) == (200, {"ok": True})
    assert (retried.status_code, retried.json()) == (200, {"ok": True})
    assert retried.headers["X-Market-Request-ID"] == "admin-request-1"
