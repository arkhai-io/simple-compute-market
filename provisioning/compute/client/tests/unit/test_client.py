"""The family client signs every request and verifies every response."""

import json
import time
import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Eip191Signer,
    Identity,
    ResponseEnvelope,
    RotationIntent,
    SignatureProof,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    sign_rotation,
    verify_request,
)
from compute_provisioning_client import (
    ComputeProvisioningClient,
    ComputeProvisioningAuthenticationError,
)
from compute_provisioning_contracts import (
    resolve_provisioning_route,
)


_ROUTES = (
    ("POST", "/api/v1/contract/leases", {"capacity_reservation_id": "reservation-1"}),
    ("GET", "/api/v1/contract/leases/reservation-1", EMPTY_BODY),
    ("POST", "/api/v1/contract/leases/reservation-1/terminate", {}),
    ("POST", "/api/v1/fulfillment/schedule", {"capacity_reservation_id": "reservation-1"}),
    ("POST", "/api/v1/fulfillment/begin", {"capacity_reservation_id": "reservation-1"}),
    ("POST", "/api/v1/fulfillment/fulfillment-1/begin-teardown", {}),
    ("GET", "/api/v1/fulfillment/fulfillment-1/status", EMPTY_BODY),
    ("GET", "/api/v1/fulfillment/fulfillment-1/result", EMPTY_BODY),
)


def _identity_headers(envelope):
    return {
        "X-Market-Signature-Version": envelope.protocol,
        "X-Market-Identity-Scheme": envelope.principal.scheme.value,
        "X-Market-Identity-Identifier": envelope.principal.identifier,
        "X-Market-Role": envelope.role,
        "X-Market-Request-ID": envelope.request_id,
        "X-Market-Timestamp": str(envelope.timestamp),
        "X-Market-Signature": envelope.proof.value,
    }


def _authenticated_request(request: httpx.Request, body):
    principal = Identity(
        scheme=request.headers["X-Market-Identity-Scheme"],
        identifier=request.headers["X-Market-Identity-Identifier"],
    )
    operation, resource = resolve_provisioning_route(
        request.method,
        request.url.path,
        body,
    )
    return AuthenticatedRequest(
        protocol=request.headers["X-Market-Signature-Version"],
        role=request.headers["X-Market-Role"],
        principal=principal,
        method=request.method,
        operation=operation,
        resource=resource,
        request_id=request.headers["X-Market-Request-ID"],
        timestamp=int(request.headers["X-Market-Timestamp"]),
        body_hash=canonical_body_hash(body),
        proof=SignatureProof(
            scheme=principal.scheme,
            value=request.headers["X-Market-Signature"],
        ),
    )


def _signed_transport(
    caller,
    authority,
    *,
    expected_role="seller",
    response_signer=None,
    response_role="service",
    served_body=None,
    unsigned=False,
    seen=None,
):
    signer = authority if response_signer is None else response_signer

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else EMPTY_BODY
        authenticated = _authenticated_request(request, body)
        operation, resource = resolve_provisioning_route(
            request.method,
            request.url.path,
            body,
        )
        result = verify_request(
            authenticated,
            body=body,
            now=authenticated.timestamp,
            max_skew=0,
            expected_role=expected_role,
            expected_method=request.method,
            expected_operation=operation,
            expected_resource=resource,
            expected_principals=TrustedIdentitySet(
                identities=(caller.identity,)
            ),
        )
        assert result.verified
        if seen is not None:
            seen.append(dict(request.headers))
        signed_body = {"ok": True}
        response_body = signed_body if served_body is None else served_body
        if unsigned:
            return httpx.Response(200, json=response_body)
        response = sign_response(
            signer=signer,
            envelope=ResponseEnvelope(
                role=response_role,
                principal=signer.identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=authenticated.request_id,
                timestamp=int(time.time()),
                status=200,
                body_hash=canonical_body_hash(signed_body),
            ),
        )
        return httpx.Response(
            200,
            json=response_body,
            headers=_identity_headers(response),
        )

    return httpx.MockTransport(handler)


# Routes only the administrator may call: the lease list and the operator's
# release controls.
_ADMIN_ROUTES = (
    ("GET", "/api/v1/contract/leases", EMPTY_BODY),
    ("POST", "/api/v1/contract/leases/reservation-1/release-oversight", {}),
    ("POST", "/api/v1/contract/leases/reservation-1/retry-release", {}),
    ("POST", "/api/v1/contract/leases/reservation-1/force-release", {}),
)


@pytest.mark.parametrize(
    ("caller", "authority"),
    (
        (Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)),
        (Eip191Signer(b"\x21" * 32), Eip191Signer(b"\x22" * 32)),
    ),
)
@pytest.mark.parametrize(
    ("role", "method", "path", "body"),
    [("seller", *route) for route in _ROUTES]
    + [("admin", *route) for route in _ROUTES + _ADMIN_ROUTES],
)
@pytest.mark.asyncio
async def test_client_signs_every_route_and_pins_signed_responses(
    caller,
    authority,
    role,
    method,
    path,
    body,
):
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=caller,
        caller_role=role,
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(caller, authority, expected_role=role),
    ) as client:
        assert await client.authenticated_request(
            method,
            path,
            body,
            request_id="request-1",
        ) == {"ok": True}


@pytest.mark.parametrize(
    ("response_signer", "response_role", "served_body", "unsigned"),
    (
        (Ed25519Signer(b"\x31" * 32), "service", None, False),
        (None, "seller", None, False),
        (None, "service", {"ok": False}, False),
        (None, "service", None, True),
    ),
)
@pytest.mark.asyncio
async def test_client_rejects_wrong_authority_role_body_and_unsigned_response(
    response_signer,
    response_role,
    served_body,
    unsigned,
):
    caller = Ed25519Signer(b"\x11" * 32)
    authority = Ed25519Signer(b"\x12" * 32)
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=caller,
        caller_role="seller",
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(
            caller,
            authority,
            response_signer=response_signer,
            response_role=response_role,
            served_body=served_body,
            unsigned=unsigned,
        ),
    ) as client:
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await client.authenticated_request(
                "POST",
                "/api/v1/fulfillment/begin",
                {"capacity_reservation_id": "reservation-1"},
                request_id="request-1",
            )


@pytest.mark.parametrize(
    ("caller", "authority"),
    [
        (Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)),
        (Eip191Signer(b"\x21" * 32), Eip191Signer(b"\x22" * 32)),
    ],
)
@pytest.mark.asyncio
async def test_client_exact_retry_fresh_signs_and_changed_reuse_fails_closed(
    monkeypatch,
    caller,
    authority,
):
    seen = []
    now = int(time.time())
    timestamps = iter((now, now, now + 1, now + 1))
    monkeypatch.setattr(
        "compute_provisioning_client.base._unix_time",
        lambda: next(timestamps, now + 1),
    )
    body = {"capacity_reservation_id": "reservation-1"}
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=caller,
        caller_role="seller",
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(caller, authority, seen=seen),
    ) as client:
        await client.authenticated_request(
            "POST", "/api/v1/fulfillment/begin", body, request_id="durable-request"
        )
        await client.authenticated_request(
            "POST", "/api/v1/fulfillment/begin", body, request_id="durable-request"
        )
        with pytest.raises(ValueError, match="changed request content"):
            await client.authenticated_request(
                "POST",
                "/api/v1/fulfillment/begin",
                {"capacity_reservation_id": "reservation-2"},
                request_id="durable-request",
            )

    assert seen[0]["x-market-timestamp"] != seen[1]["x-market-timestamp"]
    assert seen[0]["x-market-signature"] != seen[1]["x-market-signature"]


@pytest.mark.asyncio
async def test_rotation_is_the_administrator_s_and_a_seller_cannot_sign_it():
    admin = Ed25519Signer(b"\x13" * 32)
    authority = Ed25519Signer(b"\x11" * 32)
    replacement = Eip191Signer(b"\x23" * 32)
    rotation = sign_rotation(
        current_signer=admin,
        replacement_signer=replacement,
        intent=RotationIntent(
            current=admin.identity,
            replacement=replacement.identity,
            subject="provisioning:admin",
            authority="provisioning",
            nonce="rotate-admin-1",
            overlap_seconds=60,
            expires_at=2_000_000_000,
        ),
    )
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=admin,
        caller_role="admin",
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(
            admin,
            authority,
            expected_role="admin",
        ),
    ) as client:
        assert await client.rotate_trusted_principal(
            "admin",
            rotation,
            request_id="rotate-1",
        ) == {"ok": True}
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=admin,
        caller_role="seller",
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(admin, authority),
    ) as seller:
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await seller.rotate_trusted_principal(
                "admin",
                rotation,
                request_id="wrong-role",
            )


_LEASE_GET = {
    "method": "GET",
    "path": r"/api/v1/example/leases/(?P<lease_id>[^/]+)",
    "operation": "provisioning_example_lease_get",
    "roles": ("admin",),
    "path_resource": "lease_id",
}


@pytest.mark.asyncio
async def test_the_client_signs_a_route_its_caller_names() -> None:
    signed: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        signed.append(
            (request.headers["X-Market-Role"], request.url.path)
        )
        return httpx.Response(500)

    caller = Ed25519Signer(b"\x51" * 32)
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=caller,
        caller_role="admin",
        expected_authorities=TrustedIdentitySet(identities=(caller.identity,)),
        transport=httpx.MockTransport(handler),
    ) as client:
        # The fake authority answers unsigned, so the call fails after sending.
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await client.authenticated_request(
                "GET", "/api/v1/example/leases/lease-1", route=_LEASE_GET
            )
        with pytest.raises(ValueError, match="does not describe"):
            await client.authenticated_request(
                "GET", "/api/v1/elsewhere/lease-1", route=_LEASE_GET
            )

    assert signed == [("admin", "/api/v1/example/leases/lease-1")]
