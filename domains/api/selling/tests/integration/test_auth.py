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
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
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


def _signed(signer: Ed25519Signer, *, role: str, method: str, operation: str, resource: str, request_id: str, body, timestamp: int) -> dict[str, str]:
    signed = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=timestamp,
            body_hash=canonical_body_hash(body),
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


BUYER = Ed25519Signer(bytes.fromhex("11" * 32))


class _Continue(BaseModel):
    """A buyer's continuation, its optional fields stated or left out."""

    action: str
    proposal: dict | None = None
    reason: str | None = None


@pytest.fixture
def mutations(tmp_path):
    """A seller mutation and a buyer route over a clock the test advances."""
    db = SQLiteClient(db_path=str(tmp_path / "mutations.db"))
    clock = {"now": 1_800_000_000}
    auth = StorefrontAuth(
        replay_store=lambda: db,
        signer=lambda: STOREFRONT,
        admin_principals=lambda: TrustedIdentitySet(identities=(ADMIN.identity,)),
        seller_principal=lambda: STOREFRONT.identity,
        clock=lambda: clock["now"],
    )
    app = FastAPI()
    app.middleware("http")(auth.sign_responses)
    runs = {"close": 0, "accept": 0}

    @app.post("/listings/{listing_id}/close", dependencies=[Depends(auth.seller_dependency("close_listing"))])
    async def close_listing(listing_id: str) -> dict[str, str]:
        runs["close"] += 1
        return {"listing_id": listing_id, "run": str(runs["close"])}

    @app.post("/negotiate/{neg_id}")
    async def negotiate_continue(neg_id: str, body: _Continue, request: Request) -> dict[str, str]:
        await auth.verify_buyer(request, "negotiate_continue", neg_id, expected_principal=BUYER.identity)
        runs["accept"] += 1
        return {"neg_id": neg_id, "action": body.action}

    return app, clock, runs


def test_a_sellers_exact_retry_replays_its_recorded_outcome_past_the_lease(mutations) -> None:
    """A seller mutation records its outcome, so an exact retry answers from the
    record and never runs the mutation again, even once the reservation's lease
    has lapsed, where an unrecorded reservation would have let it run twice."""
    app, clock, runs = mutations
    headers = _signed(
        STOREFRONT, role="seller", method="POST", operation="close_listing",
        resource="L-1", request_id="seller-close-1", body=EMPTY_BODY, timestamp=clock["now"],
    )
    with TestClient(app) as client:
        first = client.post("/listings/L-1/close", headers=headers)
        clock["now"] += 24 * 3600
        headers["X-Market-Timestamp"] = str(clock["now"])
        resigned = _signed(
            STOREFRONT, role="seller", method="POST", operation="close_listing",
            resource="L-1", request_id="seller-close-1", body=EMPTY_BODY, timestamp=clock["now"],
        )
        retried = client.post("/listings/L-1/close", headers=resigned)

    assert (first.status_code, first.json()) == (200, {"listing_id": "L-1", "run": "1"})
    assert (retried.status_code, retried.json()) == (200, {"listing_id": "L-1", "run": "1"})
    assert runs["close"] == 1


def test_a_buyer_is_verified_over_the_body_as_sent(mutations) -> None:
    """A client that signs what it sends verifies whether it states its optional
    fields as null or leaves them out."""
    app, clock, runs = mutations
    stated = {"action": "accept", "proposal": None, "reason": None}
    sparse = {"action": "accept"}
    with TestClient(app) as client:
        for request_id, body in (("buyer-1", stated), ("buyer-2", sparse)):
            headers = _signed(
                BUYER, role="buyer", method="POST", operation="negotiate_continue",
                resource="neg-1", request_id=request_id, body=body, timestamp=clock["now"],
            )
            response = client.post("/negotiate/neg-1", json=body, headers=headers)
            assert (response.status_code, response.json()) == (200, {"neg_id": "neg-1", "action": "accept"}), response.text
    assert runs["accept"] == 2
