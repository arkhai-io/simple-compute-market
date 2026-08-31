"""Provisioning client contract guardrails owned by the service test suite.

The provisioning client wheel is the authoritative inter-service contract for
public DTOs and HTTP operations.  The client project intentionally stays light
(no local test machinery), so the service suite owns the guardrail that the
async and sync clients expose the same public operation surface.
"""

from __future__ import annotations

import inspect

import time

import pytest
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet
from vm_provisioning_operator import ProvisioningClient, SyncProvisioningClient


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(value)
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value)
    }


def test_async_and_sync_clients_have_matching_public_operations_and_signatures() -> None:
    async_methods = _public_methods(ProvisioningClient)
    sync_methods = _public_methods(SyncProvisioningClient)

    assert set(async_methods) == set(sync_methods)
    assert async_methods == sync_methods


@pytest.mark.parametrize("signer_type", (Ed25519Signer, Eip191Signer))
def test_operator_client_retry_fresh_signs_and_rejects_changed_context(
    monkeypatch,
    signer_type,
) -> None:
    caller = signer_type(b"\x11" * 32)
    authority = signer_type(b"\x12" * 32)
    now = int(time.time())
    timestamps = iter((now, now + 1))
    monkeypatch.setattr(
        "compute_provisioning.client._unix_time",
        lambda: next(timestamps, now + 1),
    )
    client = SyncProvisioningClient(
        "https://provisioning.example",
        signer=caller,
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,)
        ),
    )
    try:
        first, _, _, first_id = client._authentication(
            "POST",
            "/api/v1/system/check-leases",
            {},
            request_id="stable-request",
        )
        second, _, _, second_id = client._authentication(
            "POST",
            "/api/v1/system/check-leases",
            {},
            request_id="stable-request",
        )
        with pytest.raises(ValueError, match="changed request content"):
            client._authentication(
                "POST",
                "/api/v1/system/check-leases",
                {"changed": True},
                request_id="stable-request",
            )
    finally:
        client.close()

    assert first_id == second_id == "stable-request"
    assert first["X-Market-Timestamp"] != second["X-Market-Timestamp"]
    assert first["X-Market-Signature"] != second["X-Market-Signature"]
