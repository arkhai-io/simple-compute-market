"""The registry client's administrator time calls: bearer-keyed and unsigned."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from registry_client import RegistryClient, RegistryClientError, SyncRegistryClient

_SIGNER = Ed25519Signer(bytes(range(32)))
_REGISTRY = Ed25519Signer(bytes(range(1, 33)))
_KEY = "admin-token"  # A development fixture; never a deployment's key.


def _registry(seen: list[httpx.Request], status: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def _arguments(transport) -> dict:
    return {
        "signer": _SIGNER,
        "caller_role": "seller",
        "expected_registries": TrustedIdentitySet(identities=(_REGISTRY.identity,)),
        "registry_authority": "registry",
        "transport": transport,
        # A read key the client carries for discovery; the administrator call
        # sends the administrator key in its place.
        "api_key": "read-key",
    }


def test_set_time_posts_the_instant_with_the_administrator_key_alone():
    seen: list[httpx.Request] = []
    transport = _registry(seen, 200, {"source": "injected", "now": 1794822300})

    async def run():
        async with RegistryClient("http://registry", **_arguments(transport)) as client:
            return await client.set_time(1794822300, admin_key=_KEY)

    answer = asyncio.run(run())

    assert (answer.source, answer.now) == ("injected", 1794822300)
    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/admin/time")
    assert request.headers["Authorization"] == f"Bearer {_KEY}"
    assert json.loads(request.content) == {"now": 1794822300}
    assert "X-Market-Signature" not in request.headers


def test_the_sync_client_reads_the_status_and_sets_the_time():
    seen: list[httpx.Request] = []
    status_transport = _registry(seen, 200, {"time": {"source": "wall"}})
    setting_transport = _registry(seen, 200, {"source": "injected", "now": 7})

    with SyncRegistryClient("http://registry", **_arguments(status_transport)) as client:
        status = client.get_admin_status(admin_key=_KEY)
    with SyncRegistryClient("http://registry", **_arguments(setting_transport)) as client:
        answer = client.set_time(7, admin_key=_KEY)

    assert status.time == {"source": "wall"}
    assert (answer.source, answer.now) == ("injected", 7)
    assert [(request.method, request.url.path) for request in seen] == [
        ("GET", "/admin/status"),
        ("POST", "/admin/time"),
    ]
    assert all(request.headers["Authorization"] == f"Bearer {_KEY}" for request in seen)


def test_a_refused_setting_raises_with_the_registry_s_status_and_body():
    transport = _registry([], 409, {"code": "time_moves_forward", "detail": "earlier"})

    async def run():
        async with RegistryClient("http://registry", **_arguments(transport)) as client:
            await client.set_time(1, admin_key=_KEY)

    with pytest.raises(RegistryClientError) as refused:
        asyncio.run(run())

    assert refused.value.status_code == 409
    assert "time_moves_forward" in refused.value.body
