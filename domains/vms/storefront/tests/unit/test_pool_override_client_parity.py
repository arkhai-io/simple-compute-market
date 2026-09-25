"""Sync and async clients expose the same pool-override contract.

`docs/development/TESTING.md` requires this check with the owning service, which
owns the contract-validation boundary. The pool-override methods are the kit's
client extension over the core client's generic transport; an operator's CLI
uses the sync variant and a scenario may use either, so a method present on only
one variant would be found by whichever caller reached for the other.
"""

from __future__ import annotations

import inspect

import pytest
from market_pool_overrides import PoolOverrideClient, SyncPoolOverrideClient
from storefront_client.client import StorefrontClient, SyncStorefrontClient

_METHODS = (
    "put_pool_override",
    "get_pool_override",
    "list_pool_overrides",
    "delete_pool_override",
)


@pytest.mark.parametrize("name", _METHODS)
def test_each_pool_override_method_exists_on_both_clients(name: str) -> None:
    assert callable(getattr(PoolOverrideClient, name, None))
    assert callable(getattr(SyncPoolOverrideClient, name, None))


@pytest.mark.parametrize("name", _METHODS)
def test_pool_override_signatures_match(name: str) -> None:
    assert inspect.signature(getattr(PoolOverrideClient, name)) == inspect.signature(
        getattr(SyncPoolOverrideClient, name)
    )


def test_the_generic_transport_the_extension_wraps_matches_across_clients() -> None:
    assert inspect.signature(StorefrontClient.authenticated_request) == inspect.signature(
        SyncStorefrontClient.authenticated_request
    )
