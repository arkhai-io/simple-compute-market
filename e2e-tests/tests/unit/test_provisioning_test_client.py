"""The provisioning test client reaches each domain's mock routes through the
family's mock-rule client, at the mount that domain states."""

from __future__ import annotations

import httpx
import pytest
from compute_provisioning_contracts import MockRouteMount, MockRuleCreate
from e2e_harness.provisioning_test_client import (
    BARE_METAL_MOCK_ROUTE_MOUNT,
    ProvisioningTestClient,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from vm_provisioning_operator import VM_MOCK_ROUTE_MOUNT

# Deterministic development keys; never used on a public network.
_ADMIN = Ed25519Signer(b"\x41" * 32)
_SERVICE = Ed25519Signer(b"\x42" * 32)


class _Refused(Exception):
    """Raised by the recording transport, so no response needs a proof."""


def _recording_client(requests: list[httpx.Request]) -> ProvisioningTestClient:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise _Refused(request.url.path)

    return ProvisioningTestClient(
        "http://provisioning.test:8081",
        signer=_ADMIN,
        expected_authorities=TrustedIdentitySet(identities=(_SERVICE.identity,)),
        transport=httpx.MockTransport(handle),
    )


@pytest.mark.parametrize(
    ("domain", "prefix"),
    [("vm_rules", "/test"), ("bare_metal_rules", "/test/bare-metal")],
)
def test_each_domains_rules_are_reached_at_its_own_mount(domain: str, prefix: str) -> None:
    requests: list[httpx.Request] = []
    with _recording_client(requests) as client:
        rules = getattr(client, domain)
        calls = (
            lambda: rules.add_rule(MockRuleCreate(rule_id="gate")),
            lambda: rules.list_rules(),
            lambda: rules.resume_rule("gate"),
            lambda: rules.delete_rule("gate"),
            lambda: rules.evaluate_job({"host": "host-a"}),
        )
        for call in calls:
            with pytest.raises(_Refused):
                call()

    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", f"{prefix}/mock-rules"),
        ("GET", f"{prefix}/mock-rules"),
        ("POST", f"{prefix}/mock-rules/gate/resume"),
        ("DELETE", f"{prefix}/mock-rules/gate"),
        ("POST", f"{prefix}/evaluate-job"),
    ]
    # Each request is signed in the administrator role the routes require.
    assert {r.headers["X-Market-Role"] for r in requests} == {"admin"}


def test_each_domains_mount_names_its_signed_operations() -> None:
    """A request is signed for its mount's operation names, which the paths
    above do not show: each mount is the one the domain's adapter binds."""
    assert VM_MOCK_ROUTE_MOUNT == MockRouteMount("/test", "provisioning_test")
    assert BARE_METAL_MOCK_ROUTE_MOUNT == MockRouteMount(
        "/test/bare-metal", "provisioning_test_bare_metal"
    )
