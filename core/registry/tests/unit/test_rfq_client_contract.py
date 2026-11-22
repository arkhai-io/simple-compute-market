"""The authority's sync and async RFQ transports have the same operation surface."""

from inspect import getmembers, isfunction, signature

from registry_client.rfq_registry import RfqRegistryClient, SyncRfqRegistryClient


def test_the_rfq_client_operations_have_sync_async_parity():
    async_methods = {name: signature(value) for name, value in getmembers(RfqRegistryClient, isfunction)
                     if not name.startswith("_")}
    sync_methods = {name: signature(value) for name, value in getmembers(SyncRfqRegistryClient, isfunction)
                    if not name.startswith("_")}

    assert {"create", "search", "read", "edit", "close"} <= async_methods.keys()
    assert async_methods == sync_methods
