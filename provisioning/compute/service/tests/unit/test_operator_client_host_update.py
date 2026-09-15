"""Both operator clients carry an explicit tenant-endpoint reset in a host update.

Request bodies are captured at the transport. The captured response is not a
signed provisioning response, so each client refuses it after sending; only the
outgoing body is under test here.
"""

from __future__ import annotations

import json

import httpx
import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from vm_provisioning_operator.client import ProvisioningClient, SyncProvisioningClient
from vm_provisioning_operator.models import HostUpdate

SIGNER = Ed25519Signer(b"\x21" * 32)
AUTHORITIES = TrustedIdentitySet(identities=(Ed25519Signer(b"\x22" * 32).identity,))

CASES = [
    pytest.param(HostUpdate(public_port=None), {"public_port": None}, id="clear-port"),
    pytest.param(
        HostUpdate(public_host=None, public_port=None),
        {"public_host": None, "public_port": None},
        id="clear-endpoint",
    ),
    pytest.param(HostUpdate(ssh_port=6005), {"ssh_port": 6005}, id="omitted-endpoint"),
    pytest.param(HostUpdate(), {}, id="empty"),
    pytest.param(HostUpdate(gpu_model=None), {}, id="other-null-still-omitted"),
]


def _capturing(bodies: list):
    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content) if request.content else None)
        return httpx.Response(200, json={})

    return handler


@pytest.mark.parametrize(("update", "expected"), CASES)
def test_sync_client_update_body(update, expected):
    bodies: list = []
    client = SyncProvisioningClient(
        "http://test", SIGNER, AUTHORITIES, transport=httpx.MockTransport(_capturing(bodies))
    )
    try:
        with pytest.raises(Exception):
            client.update_host("bm1", update)
    finally:
        client.close()

    assert bodies == [expected]


@pytest.mark.parametrize(("update", "expected"), CASES)
@pytest.mark.asyncio
async def test_async_client_update_body(update, expected):
    bodies: list = []
    client = ProvisioningClient(
        "http://test", SIGNER, AUTHORITIES, transport=httpx.MockTransport(_capturing(bodies))
    )
    try:
        with pytest.raises(Exception):
            await client.update_host("bm1", update)
    finally:
        await client.close()

    assert bodies == [expected]
