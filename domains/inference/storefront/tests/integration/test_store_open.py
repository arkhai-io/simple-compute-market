"""Starting the inference storefront on a migrated database changes no schema.

Application integration: the real app and lifespan compose the storefront from
configuration. Over a database its chain migrated, with the startup tasks
replaced as ``running`` does, the tables, columns, indexes, and triggers are the
same before and after; a store only a loop's step opens is not exercised here.
Over a database the chain has not migrated, the same startup refuses before
opening it.
"""

from __future__ import annotations

import sqlite3

import pytest
from arkhai_api_selling.migrations import (
    IncompatibleStorefrontDatabase,
    migrate_storefront_database,
)
from market_schema_migrations import schema_snapshot

from inference_storefront.migrate import CHAIN
from tests.integration.conftest import app, running


def _snapshot(path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


async def test_starting_the_storefront_and_opening_its_stores_changes_no_schema(
    storefront, quota_site, registries, monkeypatch
):
    migrate_storefront_database(CHAIN, storefront)
    migrated = _snapshot(storefront)

    async with running(monkeypatch) as clients:
        health = await clients.public.get_health()

    assert health.checks["database"] == "ok"
    assert _snapshot(storefront) == migrated


async def test_the_storefront_refuses_to_start_on_a_database_it_has_not_migrated(storefront):
    """Startup checks the database before anything opens it: with none migrated
    it refuses, naming the migration command, and creates no file."""
    served = app()

    with pytest.raises(IncompatibleStorefrontDatabase) as refused:
        async with served.router.lifespan_context(served):
            pass

    assert "`inference-storefront-migrate`" in str(refused.value)
    assert not storefront.exists()
