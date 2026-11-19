"""Opening the API-credit storefront's stores on a migrated database changes no schema.

The real app and lifespan compose the storefront from configuration over a
database its chain migrated, with the seams ``test_alkahest_release_conditions``
supplies for what lies beyond the storefront: the database client and every
store the service composition opens. That fixture replaces the startup tasks,
which preflight the credits service and start the timer loops, so a store only
a loop's step opens is not exercised here. The database's tables, columns,
indexes, and triggers are the same before and after. Over a database the chain
has not migrated, the same startup refuses before opening it.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import sqlite3

import pytest
from market_schema_migrations import schema_snapshot

from apicredits_storefront.utils.migrations import (
    IncompatibleStorefrontDatabase,
    migrate_storefront_database,
)
from tests.integration.test_alkahest_release_conditions import (  # noqa: F401  (fixture)
    _app,
    _replaced,
    _settlement,
    _started,
    storefront,
)


def _snapshot(path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_starting_the_storefront_and_opening_its_stores_changes_no_schema(storefront):
    migrate_storefront_database(storefront)
    migrated = _snapshot(storefront)

    async with _started(_settlement()) as (_listings, public, _admin):
        health = await public.get_health()

    assert health.checks["database"] == "ok"
    assert _snapshot(storefront) == migrated


@pytest.mark.asyncio
async def test_the_storefront_refuses_to_start_on_a_database_it_has_not_migrated(storefront):
    """Startup checks the database before anything opens it: with none migrated
    it refuses, naming the migration command, and creates no file."""
    app = _app()

    with _replaced(settlement=_settlement()):
        with pytest.raises(IncompatibleStorefrontDatabase) as refused:
            async with app.router.lifespan_context(app):
                pass

    assert "`apicredits-storefront-migrate`" in str(refused.value)
    assert not storefront.exists()
