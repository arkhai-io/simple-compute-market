"""Provisioning client contract guardrails owned by the service test suite.

The provisioning client wheel is the authoritative inter-service contract for
public DTOs and HTTP operations.  The client project intentionally stays light
(no local test machinery), so the service suite owns the guardrail that the
async and sync clients expose the same public operation surface.
"""

from __future__ import annotations

import inspect

from provisioning_client import ProvisioningClient, SyncProvisioningClient


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
