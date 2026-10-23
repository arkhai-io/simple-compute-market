"""The family client's sync and async variants offer identical methods; this service owns that contract."""

from __future__ import annotations

import inspect

from arkhai_api_client import AuthorityClient, SyncAuthorityClient


def _public(cls) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def test_async_and_sync_authority_clients_offer_identical_methods():
    assert _public(AuthorityClient) == _public(SyncAuthorityClient)
