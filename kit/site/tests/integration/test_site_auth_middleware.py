"""The site-authority middleware, over a live HTTP client.

Exercises the composed surface rather than the pieces: a real app, the real
middleware, real Ed25519 signers, and requests signed the way
`kit/site-client` signs them, over `httpx.ASGITransport`.

What this is for. The original defect had two halves -- the authority refused a
marketplace-signed request, *and* the refusal itself was unsigned, so a client
requiring signed responses died on a missing header instead of reporting the
401 it was sent. A unit test of the route table cannot see either half. These
assert the response envelope on the refusal paths specifically, because that is
the half that was invisible.

Signing is reproduced here rather than driven through `SiteCapacityClient`
because the client also verifies the response and raises on anything it cannot
read -- which would turn "the refusal was unsigned" into an exception about
headers rather than an assertion about the refusal. The envelope is checked
directly instead.
"""

from __future__ import annotations

from dataclasses import replace
import time
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    Identity,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)
from market_site.auth import (
    CAPACITY_ROUTE_CONTRACTS,
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    SiteAuthMiddleware,
)

AUTHORITY_SIGNER = Ed25519Signer(b"authority-seed-32-bytes-exactly!")
SELLER_SIGNER = Ed25519Signer(b"seller-seed-32-bytes-exactly!!!!")
GATED_SIGNER = Ed25519Signer(b"gated-seed-32-bytes-exactly!!!!!")
IMPOSTOR_SIGNER = Ed25519Signer(b"impostor-seed-32-bytes-exactly!!")

_TRUST = {
    "seller": TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    "service": TrustedIdentitySet(identities=(GATED_SIGNER.identity,)),
    "admin": TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
}


def _expected_principals(role: str) -> TrustedIdentitySet:
    # Raises for a role this deployment trusts nobody for. `TrustedIdentitySet`
    # refuses to be empty, so a resolver has no way to *return* "nobody" --
    # which makes raising the only honest answer, and the middleware's
    # handling of it worth asserting.
    return _TRUST[role]


@pytest.fixture
def app() -> FastAPI:
    """A stand-in for the capacity router's own paths.

    The handler is trivial on purpose: what is under test is the middleware
    and the route table, and a real ledger would make a refusal and a
    ledger-level rejection hard to tell apart.
    """
    application = FastAPI()

    @application.get("/api/v1/capacity/snapshot")
    def snapshot() -> dict[str, Any]:
        return {"rows": []}

    @application.put("/api/v1/capacity/resources/{resource_id}")
    def put_resource(resource_id: str) -> dict[str, Any]:
        return {"resource_id": resource_id}

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: AUTHORITY_SIGNER,
        expected_principals=_expected_principals,
        contracts=CAPACITY_ROUTE_CONTRACTS,
    )
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://authority"
    ) as http:
        yield http


def _signed_headers(
    *,
    signer: Ed25519Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    request_id: str | None = None,
    timestamp: int | None = None,
) -> dict[str, str]:
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method.upper(),
            operation=operation,
            resource=resource,
            request_id=request_id or str(uuid.uuid4()),
            timestamp=timestamp if timestamp is not None else int(time.time()),
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


def _assert_signed_by_authority(response: httpx.Response) -> None:
    """Every response carries the authority's envelope, refusals included."""
    assert response.headers.get(SIGNATURE_HEADER), (
        f"response to {response.request.method} {response.request.url.path} "
        f"carries no signature (status {response.status_code}); a client "
        "requiring signed responses cannot read this outcome at all"
    )
    principal = Identity(
        scheme=response.headers[IDENTITY_SCHEME_HEADER],
        identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
    )
    assert principal == AUTHORITY_SIGNER.identity
    assert response.headers[ROLE_HEADER] == "service"
    assert response.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_a_signed_seller_request_is_served_and_the_response_signed(client):
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"rows": []}
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_an_unsigned_request_is_refused_and_the_refusal_is_signed(client):
    """The exact shape of the original defect.

    An `X-Admin-Key` gate produced this refusal unsigned, so the kit's client
    raised on a missing response header rather than reporting the 401. The
    status alone is not the assertion -- the envelope is.
    """
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers={REQUEST_ID_HEADER: str(uuid.uuid4())},
    )
    assert response.status_code == 401
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_a_request_carrying_no_request_id_is_refused_unsigned(client):
    """The one refusal that cannot be signed, asserted so it stays deliberate.

    A response envelope binds to the request id it answers. With none
    supplied there is nothing to bind to, and signing over an invented one
    would produce an envelope verifying against a request nobody sent.
    """
    response = await client.get("/api/v1/capacity/snapshot")
    assert response.status_code == 401
    assert SIGNATURE_HEADER not in response.headers


@pytest.mark.asyncio
async def test_an_untrusted_principal_is_refused(client):
    """A well-formed signature from a key this role does not trust."""
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=IMPOSTOR_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_a_role_the_route_does_not_admit_is_refused(client):
    """Capacity routes are seller-scoped; the gated service is not one.

    The distinction a single shared secret could not express, and the reason
    the storefront and the gated application now hold different roles.
    """
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=GATED_SIGNER,
            role="service",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_admin_reaches_a_route_that_names_only_seller(client):
    """`admin` is admitted everywhere without being enumerated per route."""
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="admin",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 200, response.text
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_signing_the_wrong_operation_for_the_route_is_refused(client):
    """The route's operation is server-owned, not taken from the caller.

    A signature over a different operation must not verify, or the signed
    context would be whatever the caller chose to claim.
    """
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_events",
            resource="",
        ),
    )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_the_path_resource_is_part_of_the_signed_context(client):
    """A signature for one resource does not verify for another.

    `resource` is extracted from the path by the server, so signing for
    `resource-a` and calling `resource-b` is a context mismatch rather than a
    successful write to the wrong row.
    """
    headers = _signed_headers(
        signer=SELLER_SIGNER,
        role="seller",
        method="PUT",
        operation="capacity_resource_put",
        resource="resource-a",
    )
    ok = await client.put("/api/v1/capacity/resources/resource-a", headers=headers)
    assert ok.status_code == 200, ok.text

    mismatched = await client.put(
        "/api/v1/capacity/resources/resource-b",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="PUT",
            operation="capacity_resource_put",
            resource="resource-a",
        ),
    )
    assert mismatched.status_code == 403
    _assert_signed_by_authority(mismatched)


@pytest.mark.asyncio
async def test_a_stale_timestamp_is_refused(client):
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_snapshot",
            resource="",
            timestamp=int(time.time()) - 4000,
        ),
    )
    assert response.status_code in (401, 403)
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_a_reused_request_id_with_changed_content_is_refused(client):
    """Replay rejection, from the in-memory default store.

    An exact retry is allowed through -- the caller resent what it already
    sent. Reuse with *different* signed content is the attack, and is a
    conflict.
    """
    request_id = str(uuid.uuid4())

    first = await client.put(
        "/api/v1/capacity/resources/resource-a",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="PUT",
            operation="capacity_resource_put",
            resource="resource-a",
            request_id=request_id,
        ),
    )
    assert first.status_code == 200, first.text

    reused = await client.put(
        "/api/v1/capacity/resources/resource-b",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="PUT",
            operation="capacity_resource_put",
            resource="resource-b",
            request_id=request_id,
        ),
    )
    assert reused.status_code == 409
    _assert_signed_by_authority(reused)


@pytest.mark.asyncio
async def test_an_excluded_path_needs_no_signature(client):
    """Liveness stays reachable without a credential.

    Asserted because the middleware refuses anything without a contract: an
    orchestrator's health probe holds no marketplace identity, and a gate that
    made the container look unhealthy would be a deployment failure rather
    than an auth one.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_a_route_with_no_contract_is_refused_before_any_handler(client):
    response = await client.get(
        "/api/v1/capacity/not-a-real-route",
        headers=_signed_headers(
            signer=SELLER_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_role_with_no_configured_principals_is_refused(client):
    """A resolver that cannot answer is a refusal, not a crash.

    `TrustedIdentitySet` cannot be empty, so a deployment trusting nobody for
    an admitted role leaves its resolver no value to return and it raises. The
    middleware must turn that into a signed refusal: the alternative is a 500
    from inside authentication, which tells a caller nothing and logs as a bug
    in the authority rather than a gap in its configuration.
    """
    unconfigured = FastAPI()

    @unconfigured.get("/api/v1/capacity/snapshot")
    def snapshot() -> dict[str, Any]:  # pragma: no cover - must not be reached
        return {"rows": []}

    def _no_principals(role: str) -> TrustedIdentitySet:
        raise KeyError(role)

    unconfigured.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: AUTHORITY_SIGNER,
        expected_principals=_no_principals,
        contracts=CAPACITY_ROUTE_CONTRACTS,
    )
    transport = httpx.ASGITransport(app=unconfigured)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://authority"
    ) as http:
        response = await http.get(
            "/api/v1/capacity/snapshot",
            headers=_signed_headers(
                signer=SELLER_SIGNER,
                role="seller",
                method="GET",
                operation="capacity_snapshot",
                resource="",
            ),
        )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


# ---------------------------------------------------------------------------
# The real client against the real middleware, for the query routes
#
# Every test above signs with this module's own `_signed_headers`, which
# builds the envelope the way the *server* expects. That is the right shape
# for testing the middleware's own branches, and it is exactly why a
# client/server disagreement about the canonical form was invisible here:
# both sides of the assertion were the server's view.
#
# `GET /api/v1/capacity/events` carries no body and two parameters that
# decide what it returns. `market_site_client` signs those parameters;
# the authority did not canonicalize them, so the proof verified over a
# different envelope than the one signed and every call was refused with
# `invalid_proof` -- from a caller whose signer, principal and role were
# all correct, and which succeeded on every route without a query.
#
# So these drive the actual `SiteCapacityClient`. Nothing about the
# envelope is reconstructed locally.
# ---------------------------------------------------------------------------


@pytest.fixture
def query_app() -> FastAPI:
    """The two capacity routes whose behavior is decided by query input."""
    application = FastAPI()

    @application.get("/api/v1/capacity/events")
    def events(after: int = 0, limit: int = 500) -> dict[str, Any]:
        return {"events": [], "latest_version": after + limit}

    @application.get("/api/v1/capacity/reservations")
    def reservations(
        state: str | None = None, escrow_uid: str | None = None
    ) -> dict[str, Any]:
        return {"reservations": [{"state": state, "escrow_uid": escrow_uid}]}

    application.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: AUTHORITY_SIGNER,
        expected_principals=_expected_principals,
        contracts=CAPACITY_ROUTE_CONTRACTS,
    )
    return application


def _real_client(query_app: FastAPI):
    from market_site_client import SiteCapacityClient

    return SiteCapacityClient(
        "http://authority",
        signer=SELLER_SIGNER,
        expected_authorities=TrustedIdentitySet(
            identities=(AUTHORITY_SIGNER.identity,),
        ),
        transport=httpx.ASGITransport(app=query_app),
    )


@pytest.mark.asyncio
async def test_the_real_client_can_read_the_event_feed(query_app):
    """`after`/`limit` are signed as integers on both sides.

    The client holds them as ints; `request.query_params` yields strings.
    Echoing the raw query back on the authority side would reproduce the
    mismatch in the other direction, so the coercion is the contract.
    """
    client = _real_client(query_app)
    events, head = await client.events_after(0, limit=1)
    assert events == []
    assert head == 1


@pytest.mark.asyncio
async def test_the_real_client_can_list_reservations_with_a_filter(query_app):
    client = _real_client(query_app)
    rows = await client.list_reservations(escrow_uid="0xabc")
    assert rows == [{"state": None, "escrow_uid": "0xabc"}]


@pytest.mark.asyncio
async def test_the_real_client_can_list_reservations_with_no_filter(query_app):
    """No filters is an empty query dict, not an absent one.

    `list_reservations()` signs `{}` while a bodyless request hashes as
    `EMPTY_BODY`, so this is a distinct case from the filtered call above
    and not covered by it.
    """
    client = _real_client(query_app)
    rows = await client.list_reservations()
    assert rows == [{"state": None, "escrow_uid": None}]


# ---------------------------------------------------------------------------
# Exact retry, per route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exact_retry_of_a_replay_safe_route_reaches_the_handler(client):
    """The default, and why it is the default.

    This store reserves `(principal, request_id)` but keeps no outcomes, so
    it cannot return a recorded one. A route whose handler resolves an exact
    retry itself -- deduplicating on a key inside the signed body, or being
    idempotent by construction -- is better served by being let through than
    by a refusal it does not need.
    """
    headers = _signed_headers(
        signer=SELLER_SIGNER,
        role="seller",
        method="GET",
        operation="capacity_snapshot",
        resource="",
    )
    first = await client.get("/api/v1/capacity/snapshot", headers=headers)
    second = await client.get("/api/v1/capacity/snapshot", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200, second.text


@pytest.mark.asyncio
async def test_an_exact_retry_of_a_non_replay_safe_route_is_refused(app):
    """A relative mutation must not be applied twice.

    Declared per route rather than assumed of all of them. The middleware
    used to let every exact retry through on the reasoning that capacity
    operations are idempotent, which stopped being true of the whole surface
    once the same middleware began protecting credit mutations.

    Refusing is the safe half of the exact-retry requirement -- no conflicting
    mutation runs. Returning the recorded outcome is the other half and needs
    a store that retains outcomes; `retain-authenticated-request-outcomes`
    owns that.
    """
    calls: list[int] = []

    application = FastAPI()

    @application.post("/api/v1/capacity/reservations")
    def reserve() -> dict[str, Any]:
        calls.append(1)
        return {"reserved": len(calls)}

    application.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: AUTHORITY_SIGNER,
        expected_principals=_expected_principals,
        contracts=tuple(
            replace(contract, exact_retry_safe=False)
            if contract.operation == "capacity_reserve"
            else contract
            for contract in CAPACITY_ROUTE_CONTRACTS
        ),
    )

    headers = _signed_headers(
        signer=SELLER_SIGNER,
        role="seller",
        method="POST",
        operation="capacity_reserve",
        resource="",
        body={"claim": {"units": 1}},
    )
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://authority"
    ) as http:
        first = await http.post(
            "/api/v1/capacity/reservations",
            json={"claim": {"units": 1}},
            headers=headers,
        )
        second = await http.post(
            "/api/v1/capacity/reservations",
            json={"claim": {"units": 1}},
            headers=headers,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert "cannot be safely retried" in second.json()["detail"]
    # The refusal's whole purpose: the handler ran once.
    assert len(calls) == 1
