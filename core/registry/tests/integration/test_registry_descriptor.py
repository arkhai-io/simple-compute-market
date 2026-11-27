"""The registry's descriptor, a public operation answered signed, and the trust
bootstrap that reads it.

Application integration: the running registry, in process, through the typed
client; the public operation's refusals through raw requests carrying a public
request's identity, which the typed client never sends to a wrong path or method
nor with signature fields; a replayed answer through a transport that returns it.
"""

from __future__ import annotations

import asyncio

import httpx
import injected_time
import pytest
from market_authenticated_requests import REPLAY_TABLE
from market_core import RegistryDescriptor
from market_identity import (
    Ed25519Signer,
    RequestBinding,
    TrustedIdentitySet,
    VerificationCode,
    build_public_request,
    verify_market_response,
)
from market_deal_lifecycle.configuration import authorities_by_registry, dispute_config
from sqlalchemy import text

from registry_client import RegistryClient, RegistryClientError, SyncRegistryClient
from core_registry.api.descriptor_routes import DESCRIPTOR_OPERATION
from core_registry.main import api, app

DESCRIPTOR_PATH = "/.well-known/arkhai/registry-descriptor.json"


async def test_typed_client_reads_authority_authenticated_descriptor(
    registry_client,
    registry_authority,
) -> None:
    descriptor = await registry_client.get_registry_descriptor()

    assert isinstance(descriptor, RegistryDescriptor)
    assert descriptor.base_url == "http://test"
    assert descriptor.schema_identity.id == "compute.market"
    assert descriptor.authority.name == "test-registry"
    assert descriptor.authority.principals[0].identifier == (
        registry_authority.identity.identifier
    )
    assert "recommendedDisputeAuthorities" not in descriptor.to_wire()
    recommendation = {
        "interface": "example.dispute.v1",
        "origin": "https://dispute.example",
        "account": "acct_example",
        "record_key": "example-public-key",
        "params": {},
        "advertisement": {
            "mechanisms": ["example.payment.v1"],
            "minimum_dispute_window_seconds": 60,
            "minimum_case_hold_seconds": None,
        },
    }
    api.state.registry_descriptor = RegistryDescriptor.model_validate(
        descriptor.to_wire() | {"recommendedDisputeAuthorities": [recommendation]}
    )
    recommended = await registry_client.get_registry_descriptor()
    assert recommended.recommended_dispute_authorities == [recommendation]
    reports = []
    recommendations = {"http://test": recommended.recommended_dispute_authorities}
    opted_in = authorities_by_registry(
        dispute_config({"use_registry_dispute_authorities": True}, role="buyer"),
        recommendations, role="buyer", report=reports.append,
    )
    assert opted_in["http://test"][0].authority.account == "acct_example"
    assert reports == []
    refused = authorities_by_registry(
        dispute_config({}, role="buyer"), recommendations,
        role="buyer", report=reports.append,
    )
    assert refused["http://test"] == ()
    assert "[[Dispute]]" in reports[-1]
    assert "use_registry_dispute_authorities = true" in reports[-1]
    seller = authorities_by_registry(
        dispute_config({}, role="seller"), {"http://test": []},
        role="seller", report=reports.append,
    )
    assert seller["http://test"] == ()
    assert "No dispute authority is available" in reports[-1]


def _descriptor(signer, *, base_url: str = "http://test", **fields) -> RegistryDescriptor:
    return RegistryDescriptor.model_validate(
        {
            "access": {"posture": "public"},
            "authority": {"name": "test-registry", "principals": [signer.identity.model_dump(mode="json")]},
            "baseUrl": base_url,
            "displayName": "Test Registry",
            "operatorIdentity": "test-operator",
            "schema": {"id": "compute.market", "version": "1"},
            **fields,
        }
    )


def _signed_by(response: httpx.Response, binding: RequestBinding, signer) -> bool:
    return verify_market_response(
        status=response.status_code,
        headers=response.headers,
        body=response.content,
        request=binding,
        expected_principals=TrustedIdentitySet(identities=(signer.identity,)),
        now=injected_time.now(),
        max_skew=300,
    ).verified


async def test_a_client_bootstraps_trust_from_the_descriptor_s_possession_proof() -> None:
    descriptor = await RegistryClient.bootstrap_registry_descriptor(
        "http://test", allow_insecure_http=True, transport=httpx.ASGITransport(app=app)
    )

    assert descriptor.authority.name == "test-registry"


def test_the_sync_client_bootstraps_the_same_descriptor(registry_authority) -> None:
    async_descriptor_transport = httpx.ASGITransport(app=app)

    class _Sync(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            async def forward() -> httpx.Response:
                response = await async_descriptor_transport.handle_async_request(request)
                content = await response.aread()
                return httpx.Response(response.status_code, headers=response.headers, content=content)

            return asyncio.run(forward())

    descriptor = SyncRegistryClient.bootstrap_registry_descriptor(
        "http://test", allow_insecure_http=True, transport=_Sync()
    )

    assert descriptor.authority.principals[0].identifier == registry_authority.identity.identifier


async def test_a_bootstrap_refuses_an_answer_signed_outside_the_descriptor() -> None:
    api.state.registry_descriptor = _descriptor(Ed25519Signer(bytes(range(2, 34))), displayName="Impersonated")

    with pytest.raises(RegistryClientError, match="wrong_principal"):
        await RegistryClient.bootstrap_registry_descriptor(
            "http://test", allow_insecure_http=True, transport=httpx.ASGITransport(app=app)
        )


async def test_a_bootstrap_refuses_a_descriptor_claiming_another_base_url(registry_authority) -> None:
    api.state.registry_descriptor = _descriptor(registry_authority, base_url="https://registry.example")

    with pytest.raises(RegistryClientError, match="names base URL https://registry.example, not http://test"):
        await RegistryClient.bootstrap_registry_descriptor(
            "http://test", allow_insecure_http=True, transport=httpx.ASGITransport(app=app)
        )


async def test_a_bootstrap_refuses_another_request_s_signed_answer() -> None:
    """A transport replaying a descriptor answered to an earlier request: its
    signature verifies, but binds another request ID than the bootstrap's."""

    registry = httpx.ASGITransport(app=app)
    earlier = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
    async with httpx.AsyncClient(transport=registry, base_url="http://test") as raw:
        recorded = await raw.get(DESCRIPTOR_PATH, headers=earlier.headers)

    class _Replaying(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(recorded.status_code, headers=recorded.headers, content=recorded.content)

    with pytest.raises(RegistryClientError, match="invalid registry response: invalid_proof"):
        await RegistryClient.bootstrap_registry_descriptor(
            "http://test", allow_insecure_http=True, transport=_Replaying()
        )


async def test_the_descriptor_is_readable_without_the_read_key_a_gated_registry_requires(
    registry_client, registry_authority, monkeypatch
) -> None:
    monkeypatch.setattr("core_registry.config.settings.require_read_api_key", True)
    api.state.registry_descriptor = _descriptor(
        registry_authority,
        access={"posture": "key-gated", "acquisitionPointer": "https://registry.example/access"},
    )

    descriptor = await registry_client.get_registry_descriptor()
    with pytest.raises(RegistryClientError) as gated:
        await registry_client.get_filter_spec()

    assert descriptor.access.posture == "key-gated"
    assert descriptor.access.acquisition_pointer == "https://registry.example/access"
    assert gated.value.status_code == 401


async def test_a_key_less_public_read_is_answered_signed_and_reserves_nothing(
    registry_authority, maker_signer, db_session
) -> None:
    """A client carrying no key reads the descriptor twice; the typed client
    verifies each answer against the registry's principal, bound to its request."""
    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=maker_signer,
        caller_role="buyer",
        expected_registries=TrustedIdentitySet(identities=(registry_authority.identity,)),
        registry_authority="test-registry",
    ) as keyless:
        first = await keyless.get_registry_descriptor()
        again = await keyless.get_registry_descriptor()

    assert first == again
    assert db_session.execute(text(f"SELECT COUNT(*) FROM {REPLAY_TABLE}")).scalar() == 0


async def test_a_signed_request_to_the_public_read_is_refused_as_malformed(registry_authority) -> None:
    """Rejection path: the typed client sends the descriptor read as its public
    operation, so this request is built by hand, its signature fields included;
    the refusal is signed over the identity it states."""

    public = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
    headers = {**public.headers, "Signature-Input": 'market=();created=1', "Signature": "market=:AA==:"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as raw:
        response = await raw.get(DESCRIPTOR_PATH, headers=headers)

    assert response.status_code == 400
    assert _signed_by(response, public.binding, registry_authority)


@pytest.mark.parametrize(
    ("method", "path", "status", "allow"),
    [
        ("GET", "/.well-known/arkhai/registry-descriptor.jsn", 404, None),
        ("POST", DESCRIPTOR_PATH, 405, "GET"),
    ],
)
async def test_a_public_request_no_route_serves_is_answered_signed(
    registry_authority, method: str, path: str, status: int, allow: str | None
) -> None:
    """Rejection path: a public request to a mistyped path or with another method."""

    public = build_public_request(method=method, operation=DESCRIPTOR_OPERATION)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as raw:
        response = await raw.request(method, path, headers=public.headers)

    assert response.status_code == status
    assert response.headers.get("allow") == allow
    assert _signed_by(response, public.binding, registry_authority)
