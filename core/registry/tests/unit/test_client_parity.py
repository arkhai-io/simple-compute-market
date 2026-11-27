"""The registry clients' sync and async surfaces keep one contract.

The guard sits with the registry, which owns the contract both clients call.
"""

from __future__ import annotations

import inspect

from registry_client import RegistryClient, SyncRegistryClient


def test_registry_clients_keep_descriptor_method_parity() -> None:
    assert inspect.signature(
        RegistryClient.get_registry_descriptor
    ) == inspect.signature(SyncRegistryClient.get_registry_descriptor)
    async_bootstrap = inspect.signature(
        RegistryClient.bootstrap_registry_descriptor
    ).parameters
    sync_bootstrap = inspect.signature(
        SyncRegistryClient.bootstrap_registry_descriptor
    ).parameters
    assert [
        (name, parameter.kind, parameter.default)
        for name, parameter in async_bootstrap.items()
    ] == [
        (name, parameter.kind, parameter.default)
        for name, parameter in sync_bootstrap.items()
    ]
    assert "allow_insecure_http" in async_bootstrap
    assert {"signer", "caller_role"}.isdisjoint(async_bootstrap)
