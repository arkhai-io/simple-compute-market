"""The async and sync storefront clients expose the same public contract.

A route method added to one client must be added to the other in the same
change; this test fails on the first divergence in name or signature.
"""

from __future__ import annotations

import inspect

from storefront_client import StorefrontClient, SyncStorefrontClient

# Async-only context management has no sync counterpart by design.
_PROTOCOL_ONLY = {"__aenter__", "__aexit__", "__enter__", "__exit__"}


def _public_methods(cls: type) -> dict[str, inspect.Signature]:
    methods = {}
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in _PROTOCOL_ONLY:
            continue
        # Resolve annotations so quoting style under postponed evaluation does not
        # count as a contract difference.
        methods[name] = inspect.signature(member, eval_str=True)
    return methods


def test_async_and_sync_clients_expose_the_same_methods() -> None:
    assert sorted(_public_methods(StorefrontClient)) == sorted(
        _public_methods(SyncStorefrontClient)
    )


def test_async_and_sync_method_signatures_match() -> None:
    async_methods = _public_methods(StorefrontClient)
    sync_methods = _public_methods(SyncStorefrontClient)
    mismatched = {
        name: (str(async_methods[name]), str(sync_methods[name]))
        for name in async_methods.keys() & sync_methods.keys()
        if async_methods[name] != sync_methods[name]
    }
    assert mismatched == {}


def test_agreement_settlement_and_refund_are_part_of_the_contract() -> None:
    for name in ("settle_agreement", "settle_evm", "refund_settlement"):
        assert name in _public_methods(StorefrontClient)
    assert "settle" not in _public_methods(StorefrontClient)
