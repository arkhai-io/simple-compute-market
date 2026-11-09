"""Opening the bare-metal storefront's stores on a migrated database changes no schema.

The production app starts over a runtime composed from the configuration files,
as ``test_app_composition`` starts it, only the site's transport replaced and
its loops held, over a database its chain migrated: the database client, every
store the runtime opens -- the lifecycle store among them -- and the startup
that seeds the site's service peer, then its health read through the typed
client. The database's tables, columns, indexes, and
triggers are the same before and after, so no store issues DDL of its own.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from market_schema_migrations import schema_snapshot
from storefront_client import StorefrontClient
from test_app_composition import _started_app

from arkhai_bare_metal_storefront.migrations import migrate_storefront_database


def _snapshot(path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_starting_the_storefront_and_opening_its_stores_changes_no_schema(
    monkeypatch, tmp_path
):
    path = tmp_path / "storefront.db"
    migrate_storefront_database(path)
    migrated = _snapshot(path)

    app, composed = _started_app(monkeypatch, tmp_path)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            health = await public.get_health()

    assert health.checks["database"] == "ok"
    assert len(composed) == 1
    assert composed[0].lifecycle is not None
    assert _snapshot(path) == migrated
