"""Provisioning client contract guardrails owned by the service test suite.

The compute provisioning client distribution is the family's authoritative
inter-service client, and VM and the Ansible implementation extend it over its
transport. None keeps contract-validation machinery of its own, so the service
suite owns the guardrail that each async and sync pair exposes the same public
operations with the same signatures. Behaviour through the real
routes is the integration suite's.
"""

from __future__ import annotations

import inspect
import time

import pytest
from compute_provisioning_client import ComputeProvisioningClient, SyncComputeProvisioningClient
from compute_provisioning_ansible.host_import import (
    AnsibleHostImportClient,
    SyncAnsibleHostImportClient,
)
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet
from vm_provisioning_operator import SyncVmOperatorClient, VmOperatorClient


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(value)
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value)
    }


@pytest.mark.parametrize(
    ("async_client", "sync_client"),
    [
        (ComputeProvisioningClient, SyncComputeProvisioningClient),
        (VmOperatorClient, SyncVmOperatorClient),
        (AnsibleHostImportClient, SyncAnsibleHostImportClient),
    ],
    ids=["family", "vm", "ansible-host-import"],
)
def test_async_and_sync_clients_have_matching_public_operations_and_signatures(
    async_client, sync_client
) -> None:
    async_methods = _public_methods(async_client)
    sync_methods = _public_methods(sync_client)

    assert set(async_methods) == set(sync_methods)
    assert async_methods == sync_methods


@pytest.mark.parametrize("signer_type", (Ed25519Signer, Eip191Signer))
def test_sync_client_retry_fresh_signs_and_rejects_changed_context(monkeypatch, signer_type) -> None:
    caller = signer_type(b"\x11" * 32)
    authority = signer_type(b"\x12" * 32)
    now = int(time.time())
    timestamps = iter((now, now + 1))
    monkeypatch.setattr(
        "compute_provisioning_client.base._unix_time",
        lambda: next(timestamps, now + 1),
    )
    client = SyncComputeProvisioningClient(
        "https://provisioning.example",
        signer=caller,
        caller_role="admin",
        expected_authorities=TrustedIdentitySet(identities=(authority.identity,)),
    )
    try:
        first = client.sign(
            "POST", "/api/v1/system/check-leases", {}, request_id="stable-request", route=None
        )
        second = client.sign(
            "POST", "/api/v1/system/check-leases", {}, request_id="stable-request", route=None
        )
        with pytest.raises(ValueError, match="changed request content"):
            client.sign(
                "POST",
                "/api/v1/system/check-leases",
                {"changed": True},
                request_id="stable-request",
                route=None,
            )
    finally:
        client.close()

    assert first.request_id == second.request_id == "stable-request"
    assert first.headers["X-Market-Timestamp"] != second.headers["X-Market-Timestamp"]
    assert first.headers["X-Market-Signature"] != second.headers["X-Market-Signature"]
