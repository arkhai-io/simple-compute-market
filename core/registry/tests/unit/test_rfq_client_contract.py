"""The registry's RFQ client variants expose matching operations."""

from inspect import getmembers, isfunction, signature

import pytest
from registry_client.rfq_public import RfqPublicRegistryClient, SyncRfqPublicRegistryClient
from registry_client.rfq_registry import RfqRegistryClient, SyncRfqRegistryClient


@pytest.mark.parametrize(("async_client", "sync_client", "minimum"), (
    (RfqRegistryClient, SyncRfqRegistryClient, {"create", "search", "read", "edit", "close"}),
    (RfqPublicRegistryClient, SyncRfqPublicRegistryClient, {"search", "read"}),
))
def test_the_rfq_client_operations_have_sync_async_parity(async_client, sync_client, minimum):
    async_methods = {name: signature(value) for name, value in getmembers(async_client, isfunction)
                     if not name.startswith("_")}
    sync_methods = {name: signature(value) for name, value in getmembers(sync_client, isfunction)
                    if not name.startswith("_")}

    assert minimum <= async_methods.keys()
    assert async_methods == sync_methods
