"""The family's mock-rule client signs from a mount and returns the family's models.

The transport below authenticates each request against a table assembled from
the mount's declarations, as the provisioning service does, so a request that
verifies was signed over that route's operation and resource. Every signer seed
here (a repeated byte) is a deterministic development key that must never be
used on a public network.
"""

from __future__ import annotations

import inspect
import json
import time

import httpx
import pytest
from compute_provisioning_client import (
    ComputeProvisioningClient,
    MockRuleClient,
    SyncComputeProvisioningClient,
    SyncMockRuleClient,
)
from compute_provisioning_contracts import (
    MockJobEvaluation,
    MockRouteMount,
    MockRuleAdded,
    MockRuleCreate,
    MockRuleDeleted,
    MockRuleResumed,
    MockRuleView,
    assemble_provisioning_route_table,
)
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    verify_request,
)

_CALLER = Ed25519Signer(b"\x41" * 32)
_AUTHORITY = Ed25519Signer(b"\x42" * 32)

_VM = MockRouteMount("/test", "provisioning_test")
_BARE_METAL = MockRouteMount("/test/bare-metal", "provisioning_test_bare_metal")

_VIEW = {
    "rule_id": "gate",
    "match": {"action": "grant"},
    "pause_before_result": True,
    "fail_with": None,
    "result_stdout": False,
    "paused": True,
    "waiting": 0,
}

# What the service answers, by the action each route performs.
_ANSWERS = {
    "rule_add": {"rule_id": "gate", "status": "added"},
    "rules_list": [_VIEW],
    "rule_delete": {"rule_id": "gate", "deleted": True},
    "rule_resume": {"rule_id": "gate", "resumed": True},
    "job_evaluate": {
        "params_valid": True,
        "host_exists": True,
        "rule_matched": "gate",
        "would_pause": True,
        "errors": [],
    },
}


def _headers(envelope) -> dict[str, str]:
    return {
        "X-Market-Signature-Version": envelope.protocol,
        "X-Market-Identity-Scheme": envelope.principal.scheme.value,
        "X-Market-Identity-Identifier": envelope.principal.identifier,
        "X-Market-Role": envelope.role,
        "X-Market-Request-ID": envelope.request_id,
        "X-Market-Timestamp": str(envelope.timestamp),
        "X-Market-Signature": envelope.proof.value,
    }


def _authority(mount: MockRouteMount, seen: list[tuple[str, str, str, str]]):
    """A provisioning service serving only ``mount``'s routes."""

    table = assemble_provisioning_route_table(mount.route_declarations())
    actions = {mount.operation(action): action for action in _ANSWERS}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else EMPTY_BODY
        contract, resource = table.resolve(request.method, request.url.path, body)
        principal = Identity(
            scheme=request.headers["X-Market-Identity-Scheme"],
            identifier=request.headers["X-Market-Identity-Identifier"],
        )
        authenticated = AuthenticatedRequest(
            protocol=request.headers["X-Market-Signature-Version"],
            role=request.headers["X-Market-Role"],
            principal=principal,
            method=request.method,
            operation=contract.operation,
            resource=resource,
            request_id=request.headers["X-Market-Request-ID"],
            timestamp=int(request.headers["X-Market-Timestamp"]),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=principal.scheme, value=request.headers["X-Market-Signature"]
            ),
        )
        verified = verify_request(
            authenticated,
            body=body,
            now=authenticated.timestamp,
            max_skew=0,
            expected_role="admin",
            expected_method=request.method,
            expected_operation=contract.operation,
            expected_resource=resource,
            expected_principals=TrustedIdentitySet(identities=(_CALLER.identity,)),
        )
        assert verified.verified, verified.code
        seen.append((request.method, request.url.path, contract.operation, resource))
        answer = _ANSWERS[actions[contract.operation]]
        response = sign_response(
            signer=_AUTHORITY,
            envelope=ResponseEnvelope(
                role="service",
                principal=_AUTHORITY.identity,
                method=request.method,
                operation=contract.operation,
                resource=resource,
                request_id=authenticated.request_id,
                timestamp=int(time.time()),
                status=200,
                body_hash=canonical_body_hash(answer),
            ),
        )
        return httpx.Response(200, json=answer, headers=_headers(response))

    return httpx.MockTransport(handler)


def _expected(mount: MockRouteMount) -> list[tuple[str, str, str, str]]:
    return [
        ("POST", mount.rules_path(), mount.operation("rule_add"), ""),
        ("GET", mount.rules_path(), mount.operation("rules_list"), ""),
        ("DELETE", mount.rule_path("gate"), mount.operation("rule_delete"), "gate"),
        ("POST", mount.rule_resume_path("gate"), mount.operation("rule_resume"), "gate"),
        ("POST", mount.evaluate_path(), mount.operation("job_evaluate"), ""),
    ]


def _assert_answers(added, listed, deleted, resumed, evaluated) -> None:
    assert added == MockRuleAdded(rule_id="gate", status="added")
    assert listed == [MockRuleView.model_validate(_VIEW)]
    assert deleted == MockRuleDeleted(rule_id="gate", deleted=True)
    assert resumed == MockRuleResumed(rule_id="gate", resumed=True)
    assert evaluated == MockJobEvaluation.model_validate(_ANSWERS["job_evaluate"])


@pytest.mark.parametrize("mount", (_VM, _BARE_METAL), ids=("vm", "bare-metal"))
@pytest.mark.asyncio
async def test_the_async_client_signs_each_route_of_its_mount(mount) -> None:
    seen: list[tuple[str, str, str, str]] = []
    async with ComputeProvisioningClient(
        "http://provisioner",
        signer=_CALLER,
        caller_role="admin",
        expected_authorities=TrustedIdentitySet(identities=(_AUTHORITY.identity,)),
        transport=_authority(mount, seen),
    ) as transport:
        rules = MockRuleClient(transport, mount)
        answers = (
            await rules.add_rule(MockRuleCreate(rule_id="gate", pause_before_result=True)),
            await rules.list_rules(),
            await rules.delete_rule("gate"),
            await rules.resume_rule("gate"),
            await rules.evaluate_job({"host": "h1", "action": "grant"}),
        )

    assert seen == _expected(mount)
    _assert_answers(*answers)


@pytest.mark.parametrize("mount", (_VM, _BARE_METAL), ids=("vm", "bare-metal"))
def test_the_sync_client_signs_each_route_of_its_mount(mount) -> None:
    seen: list[tuple[str, str, str, str]] = []
    transport = SyncComputeProvisioningClient(
        "http://provisioner",
        signer=_CALLER,
        caller_role="admin",
        expected_authorities=TrustedIdentitySet(identities=(_AUTHORITY.identity,)),
        transport=_authority(mount, seen),
    )
    try:
        rules = SyncMockRuleClient(transport, mount)
        answers = (
            rules.add_rule(MockRuleCreate(rule_id="gate", pause_before_result=True)),
            rules.list_rules(),
            rules.delete_rule("gate"),
            rules.resume_rule("gate"),
            rules.evaluate_job({"host": "h1", "action": "grant"}),
        )
    finally:
        transport.close()

    assert seen == _expected(mount)
    _assert_answers(*answers)


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(value)
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value)
    }


def test_the_async_and_sync_clients_have_the_same_operations() -> None:
    assert _public_methods(MockRuleClient) == _public_methods(SyncMockRuleClient)
