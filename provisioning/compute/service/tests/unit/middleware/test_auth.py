from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Ed25519Signer,
    Eip191Signer,
    Identity,
    RequestEnvelope,
    SignatureProof,
    canonical_body_hash,
    sign_request,
    ReplayIdentity,
    ReplayReservation,
    verify_response,
    TrustedIdentitySet,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    resolve_provisioning_route,
)
from compute_provisioning_service.db.models import (
    Base,
    ProvisioningReplayReservation,
)
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.middleware.auth import (
    SqlAlchemyProvisioningReplayStore,
    ProvisioningAuthMiddleware,
)

_ADMIN_SIGNER = Ed25519Signer(b"\x13" * 32)


_MUTATIONS = (
    ("/api/v1/actions", {"capacity_reservation_id": "reservation-1"}),
    ("/api/v1/jobs/job-1/contract/cancel", {}),
    ("/api/v1/contract/leases", {"capacity_reservation_id": "reservation-1"}),
    ("/api/v1/contract/leases/reservation-1/terminate", {}),
    ("/api/v1/contract/leases/reservation-1/retry-release", {}),
    ("/api/v1/contract/leases/reservation-1/force-release", {}),
    ("/api/v1/fulfillment/schedule", {"capacity_reservation_id": "reservation-1"}),
    ("/api/v1/fulfillment/begin", {"capacity_reservation_id": "reservation-1"}),
    ("/api/v1/fulfillment/fulfillment-1/begin-teardown", {}),
)


def _signer(scheme: str, seed: int):
    if scheme == "ed25519":
        return Ed25519Signer(bytes([seed]) * 32)
    return Eip191Signer(bytes([seed]) * 32)


class _PrincipalAuthority:
    def __init__(self, storefront):
        self._storefront = storefront

    def active_principals(self, role):
        principal = (
            _ADMIN_SIGNER.identity
            if role == "admin"
            else self._storefront.identity
        )
        return TrustedIdentitySet(identities=(principal,))


@pytest.fixture(params=("ed25519", "eip191"))
def identities(request):
    return _signer(request.param, 17), _signer(request.param, 23)


def _app(storefront, authority):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    replay = SqlAlchemyProvisioningReplayStore(factory)
    identity = ProvisioningIdentityContext(
        signer=authority,
        storefront_principal=storefront.identity,
        admin_principal=_ADMIN_SIGNER.identity,
        storefront_site_id="default",
    )
    app = FastAPI()
    calls = {"count": 0}
    app.add_middleware(
        ProvisioningAuthMiddleware,
        identity_provider=lambda: identity,
        replay_store_provider=lambda: replay,
        principal_authority_provider=lambda: _PrincipalAuthority(storefront),
    )

    async def mutation(_: Request):
        calls["count"] += 1
        return {"ok": True, "count": calls["count"]}

    app.add_api_route("/api/v1/actions", mutation, methods=["POST"])
    app.add_api_route(
        "/api/v1/jobs/{job_id}/contract/cancel", mutation, methods=["POST"]
    )
    app.add_api_route("/api/v1/contract/leases", mutation, methods=["POST"])
    for suffix in ("terminate", "retry-release", "force-release"):
        app.add_api_route(
            f"/api/v1/contract/leases/{{reservation_id}}/{suffix}",
            mutation,
            methods=["POST"],
        )
    app.add_api_route("/api/v1/fulfillment/schedule", mutation, methods=["POST"])
    app.add_api_route("/api/v1/fulfillment/begin", mutation, methods=["POST"])
    app.add_api_route(
        "/api/v1/fulfillment/{fulfillment_id}/begin-teardown",
        mutation,
        methods=["POST"],
    )
    app.add_api_route("/api/v1/system/check-leases", mutation, methods=["POST"])
    app.add_api_route("/api/v1/capacity/snapshot", mutation, methods=["GET"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app), calls


def _headers(
    signer,
    path: str,
    body,
    *,
    request_id: str = "request-1",
    role: str = "seller",
    method: str = "POST",
) -> dict[str, str]:
    operation, resource = resolve_provisioning_route(method, path, body)
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }


def _verified_response(response, authority: Identity, path: str, body: dict):
    operation, resource = resolve_provisioning_route("POST", path, body)
    principal = Identity(
        scheme=response.headers[IDENTITY_SCHEME_HEADER],
        identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
    )
    authenticated = AuthenticatedResponse(
        protocol=response.headers[SIGNATURE_VERSION_HEADER],
        role=response.headers[ROLE_HEADER],
        principal=principal,
        method="POST",
        operation=operation,
        resource=resource,
        request_id=response.headers[REQUEST_ID_HEADER],
        timestamp=int(response.headers[TIMESTAMP_HEADER]),
        status=response.status_code,
        body_hash=canonical_body_hash(response.json()),
        proof=SignatureProof(
            scheme=principal.scheme,
            value=response.headers[SIGNATURE_HEADER],
        ),
    )
    return verify_response(
        authenticated,
        body=response.json(),
        now=authenticated.timestamp,
        max_skew=0,
        expected_role="service",
        expected_principals=TrustedIdentitySet(identities=(authority,)),
        expected_method="POST",
        expected_operation=operation,
        expected_resource=resource,
        expected_request_id=authenticated.request_id,
    )


@pytest.mark.parametrize(("path", "body"), _MUTATIONS)
def test_every_mutation_is_body_bound_and_response_signed(
    identities,
    path,
    body,
):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    response = client.post(path, json=body, headers=_headers(storefront, path, body))

    assert response.status_code == 200
    assert calls["count"] == 1
    assert _verified_response(response, authority.identity, path, body).verified


def test_wrong_role_principal_and_body_fail_before_dispatch(identities):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    path, body = _MUTATIONS[0]
    stranger = _signer(storefront.identity.scheme.value, 31)

    wrong_role = client.post(
        path,
        json=body,
        headers=_headers(storefront, path, body, request_id="wrong-role", role="service"),
    )
    wrong_principal = client.post(
        path,
        json=body,
        headers=_headers(stranger, path, body, request_id="wrong-principal"),
    )
    changed_body = client.post(
        path,
        json={"capacity_reservation_id": "reservation-2"},
        headers=_headers(storefront, path, body, request_id="wrong-body"),
    )

    assert wrong_role.status_code == 403
    assert wrong_principal.status_code == 403
    assert changed_body.status_code == 403
    assert calls["count"] == 0


def test_exact_retry_returns_recorded_outcome_and_changed_reuse_conflicts(identities):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    path, body = _MUTATIONS[0]
    headers = _headers(storefront, path, body, request_id="durable-request")

    first = client.post(path, json=body, headers=headers)
    exact = client.post(path, json=body, headers=headers)
    changed = {"capacity_reservation_id": "reservation-2"}
    changed_response = client.post(
        path,
        json=changed,
        headers=_headers(
            storefront,
            path,
            changed,
            request_id="durable-request",
        ),
    )

    assert first.json() == exact.json() == {"ok": True, "count": 1}
    assert changed_response.status_code == 409
    assert calls["count"] == 1


def test_legacy_admin_header_is_rejected_and_health_stays_open(identities):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    path, body = _MUTATIONS[0]

    assert client.post(path, json=body, headers={"X-Admin-Key": "legacy"}).status_code == 401
    assert client.get("/health").status_code == 200
    assert calls["count"] == 0

def test_admin_routes_require_exact_admin_principal_and_role(identities):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    path = "/api/v1/system/check-leases"
    body = {}

    accepted = client.post(
        path,
        json=body,
        headers=_headers(_ADMIN_SIGNER, path=path, body=body, role="admin"),
    )
    wrong_role = client.post(
        path,
        json=body,
        headers=_headers(_ADMIN_SIGNER, path=path, body=body, role="seller"),
    )
    wrong_principal = client.post(
        path,
        json=body,
        headers=_headers(storefront, path=path, body=body, role="admin"),
    )

    assert accepted.status_code == 200
    assert wrong_role.status_code == 403
    assert wrong_principal.status_code == 403
    assert calls["count"] == 1

def test_capacity_operator_reads_allow_exact_seller_or_admin_trust_set(identities):
    storefront, authority = identities
    client, calls = _app(storefront, authority)
    path = "/api/v1/capacity/snapshot"

    seller = client.get(
        path,
        headers=_headers(
            storefront,
            path,
            EMPTY_BODY,
            role="seller",
            method="GET",
            request_id="seller-read",
        ),
    )
    admin = client.get(
        path,
        headers=_headers(
            _ADMIN_SIGNER,
            path,
            EMPTY_BODY,
            role="admin",
            method="GET",
            request_id="admin-read",
        ),
    )
    wrong_binding = client.get(
        path,
        headers=_headers(
            storefront,
            path,
            EMPTY_BODY,
            role="admin",
            method="GET",
            request_id="wrong-read",
        ),
    )

    assert seller.status_code == 200
    assert admin.status_code == 200
    assert wrong_binding.status_code == 403
    assert calls["count"] == 2


def test_stale_exact_reservation_can_be_atomically_reclaimed(identities):
    storefront, _ = identities
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    store = SqlAlchemyProvisioningReplayStore(
        factory,
        dispatch_lease_seconds=30,
    )
    reservation = ReplayReservation(
        identity=ReplayIdentity(
            principal=storefront.identity,
            request_id="stale-request",
        ),
        request_hash="1" * 64,
    )

    assert store.reserve(reservation) is None
    assert store.claim_stale(reservation) is False
    with factory() as session:
        row = session.get(
            ProvisioningReplayReservation,
            (
                storefront.identity.scheme.value,
                storefront.identity.identifier,
                "stale-request",
            ),
        )
        row.dispatch_lease_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        session.commit()

    assert store.claim_stale(reservation) is True
    with factory() as session:
        row = session.get(
            ProvisioningReplayReservation,
            (
                storefront.identity.scheme.value,
                storefront.identity.identifier,
                "stale-request",
            ),
        )
        assert row.dispatch_attempt_count == 2
