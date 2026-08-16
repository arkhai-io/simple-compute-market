import json
import re
import time
from datetime import datetime, timezone

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
from pydantic import ValidationError

from compute_provisioning import (
    ComputeProvisioningClient,
    PROVISIONING_ROUTE_CONTRACTS,
    canonical_provisioning_request_body,
    ComputeProvisioningAuthenticationError,
    ExecutorActionEnvelope,
    ExecutorAdapterRegistry,
    FunctionalExecutorAdapter,
    IdempotentLifecycleEventSink,
    LifecycleEvent,
    ResultEnvelope,
    UnsupportedExecutorActionError,
    resolve_provisioning_route,
)


def _action(**overrides):
    values = {
        "capacity_reservation_id": "alloc-1",
        "deal_ref": {"escrow_uid": "escrow-1"},
        "executor_kind": "vm",
        "action_kind": "create",
        "idempotency_key": "request-1",
        "parameters": {"vm_target": "tenant-1"},
    }
    values.update(overrides)
    return ExecutorActionEnvelope(**values)


def test_contract_rejects_unsupported_major_version():
    with pytest.raises(ValidationError, match="supported majors: 1"):
        _action(contract_version="2.0")


@pytest.mark.asyncio
async def test_registry_validates_without_generic_field_inspection():
    submitted = []

    async def submit(envelope, value):
        submitted.append((envelope.capacity_reservation_id, value))
        return "job-1"

    adapter = FunctionalExecutorAdapter(
        executor_kind="vm",
        parameter_validators={"create": lambda payload: payload["vm_target"]},
        submit_action=submit,
        result_validators={"create": lambda payload: ResultEnvelope(executor_kind="vm", result_kind="created", value=dict(payload))},
        credential_validators={},
    )
    registry = ExecutorAdapterRegistry([adapter])
    action = _action()
    validated = registry.get("vm").validate_parameters(action.action_kind, action.parameters)
    assert await registry.get("vm").submit(action, validated) == "job-1"
    assert submitted == [("alloc-1", "tenant-1")]
    with pytest.raises(UnsupportedExecutorActionError):
        registry.get("vm").validate_parameters("reimage", {})


@pytest.mark.asyncio
async def test_event_sink_deduplicates_only_after_successful_delivery():
    delivered = []
    sink = IdempotentLifecycleEventSink(lambda event: _record(delivered, event.event_id))
    event = LifecycleEvent(
        event_id="event-1",
        capacity_reservation_id="alloc-1",
        deal_ref={"escrow_uid": "escrow-1"},
        executor_kind="vm",
        event_kind="usage_ready",
        payload={},
        occurred_at=datetime.now(timezone.utc),
    )
    assert await sink.deliver(event) is True
    assert await sink.deliver(event) is False
    assert delivered == ["event-1"]


async def _record(values, value):
    values.append(value)


_ROUTES = (
    ("POST", "/api/v1/actions", {"capacity_reservation_id": "reservation-1"}),
    ("GET", "/api/v1/jobs/job-1/contract", EMPTY_BODY),
    ("POST", "/api/v1/jobs/job-1/contract/cancel", {}),
    ("GET", "/api/v1/jobs/job-1/contract/credentials", EMPTY_BODY),
    ("POST", "/api/v1/contract/leases", {"capacity_reservation_id": "reservation-1"}),
    ("GET", "/api/v1/contract/leases/reservation-1", EMPTY_BODY),
    ("POST", "/api/v1/contract/leases/reservation-1/terminate", {}),
    ("POST", "/api/v1/contract/leases/reservation-1/retry-release", {}),
    ("POST", "/api/v1/contract/leases/reservation-1/force-release", {}),
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


@pytest.mark.parametrize(
    ("caller", "authority"),
    (
        (Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)),
        (Eip191Signer(b"\x21" * 32), Eip191Signer(b"\x22" * 32)),
    ),
)
@pytest.mark.parametrize(("method", "path", "body"), _ROUTES)
@pytest.mark.asyncio
async def test_client_signs_every_route_and_pins_signed_responses(
    caller,
    authority,
    method,
    path,
    body,
):
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=caller,
        caller_role="seller",
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
        transport=_signed_transport(caller, authority),
    ) as client:
        assert await client._request(
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
            await client._request(
                "POST",
                "/api/v1/actions",
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
        "compute_provisioning.client._unix_time",
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
        await client._request(
            "POST", "/api/v1/actions", body, request_id="durable-request"
        )
        await client._request(
            "POST", "/api/v1/actions", body, request_id="durable-request"
        )
        with pytest.raises(ValueError, match="changed request content"):
            await client._request(
                "POST",
                "/api/v1/actions",
                {"capacity_reservation_id": "reservation-2"},
                request_id="durable-request",
            )

    assert seen[0]["x-market-timestamp"] != seen[1]["x-market-timestamp"]
    assert seen[0]["x-market-signature"] != seen[1]["x-market-signature"]

@pytest.mark.parametrize(
    "contract",
    [
        contract
        for contract in PROVISIONING_ROUTE_CONTRACTS
        if contract.method in {"POST", "PUT", "PATCH", "DELETE"}
    ],
    ids=lambda contract: contract.operation,
)
def test_every_bound_mutation_contract_is_reachable(contract):
    path = re.sub(
        r"\(\?P<[^>]+>\[\^/\]\+\)",
        "resource-1",
        contract.pattern.pattern,
    )
    path = path.replace("(?P<trust_role>admin|seller)", "admin").replace(
        "/?",
        "",
    )
    body = (
        {contract.body_resource: "resource-1"}
        if contract.body_resource is not None
        else {}
    )

    operation, resource = resolve_provisioning_route(
        contract.method,
        path,
        body,
    )

    assert operation == contract.operation
    assert resource == contract.match(contract.method, path, body)


def test_operator_capacity_routes_preserve_distinct_seller_and_admin_roles():
    dual_role_operations = {
        "capacity_snapshot",
        "capacity_reservations_list",
        "capacity_reservation_get",
        "capacity_truncate_lease",
    }
    routes = {
        contract.operation: contract
        for contract in PROVISIONING_ROUTE_CONTRACTS
    }

    for operation in dual_role_operations:
        assert routes[operation].allowed_roles == ("seller", "admin")
    assert routes["capacity_reserve"].allowed_roles == ("seller",)
    assert routes["provisioning_system_status"].allowed_roles == ("admin",)

@pytest.mark.parametrize(
    ("body", "expected_resource"),
    [
        ({"deal_ref": {"settlement_obligation_ref": "obligation-1"}}, ""),
        ({"capacity_reservation_id": "reservation-1"}, "reservation-1"),
    ],
)
def test_capacity_release_route_allows_optional_reservation_hint(
    body: dict[str, object],
    expected_resource: str,
) -> None:
    assert resolve_provisioning_route(
        "POST",
        "/api/v1/capacity/releases",
        body,
    ) == ("capacity_release", expected_resource)


def test_capacity_queries_are_canonical_body_bound():
    assert canonical_provisioning_request_body(
        "GET",
        "/api/v1/capacity/reservations",
        query={"state": "held", "escrow_uid": None},
    ) == {"state": "held"}
    assert canonical_provisioning_request_body(
        "GET",
        "/api/v1/capacity/events",
    ) == {"after": 0, "limit": 500}
    assert canonical_provisioning_request_body(
        "GET",
        "/api/v1/capacity/events",
        query={"limit": "25", "after": "7"},
    ) == {"after": 7, "limit": 25}


@pytest.mark.asyncio
async def test_admin_client_calls_two_proof_rotation_route_only():
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
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await client.submit_action(
                _action(),
                request_id="wrong-role",
            )