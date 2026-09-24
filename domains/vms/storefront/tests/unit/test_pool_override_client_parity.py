"""Sync and async storefront clients expose the same pool-override contract.

`docs/development/TESTING.md` places this check with the owning service, which
owns the contract-validation boundary. An operator's CLI uses the sync client and
a scenario may use either, so a method present on only one variant would be
found by whichever caller reached for the other.
"""

from __future__ import annotations

import inspect

import pytest
from storefront_client.client import StorefrontClient, SyncStorefrontClient

_METHODS = (
    "admin_put_pool_override",
    "admin_get_pool_override",
    "admin_list_pool_overrides",
    "admin_delete_pool_override",
)


@pytest.mark.parametrize("name", _METHODS)
def test_each_pool_override_method_exists_on_both_clients(name: str) -> None:
    assert callable(getattr(StorefrontClient, name, None))
    assert callable(getattr(SyncStorefrontClient, name, None))


@pytest.mark.parametrize("name", _METHODS)
def test_pool_override_signatures_match(name: str) -> None:
    assert inspect.signature(getattr(StorefrontClient, name)) == inspect.signature(
        getattr(SyncStorefrontClient, name)
    )
