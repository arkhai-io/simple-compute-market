"""Opening the VM storefront's stores on a migrated database changes no schema.

The real app and lifespan compose the storefront from configuration over a
database its chain migrated, as ``test_degraded_startup`` does: the database
client, every store the composition opens, and every startup step, then a
publication cycle. The database's tables, columns, indexes, and triggers are
the same before and after, so no store issues DDL of its own. Over a database
the chain has not migrated, the same startup refuses before opening it.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import base64
import sqlite3
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from market_schema_migrations import schema_snapshot

import market_storefront.server as server
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils import sqlite_client as sqlite_module
from market_storefront.utils.migrations import (
    IncompatibleStorefrontDatabase,
    migrate_storefront_database,
)
from tests._settings_overrides import replaced_setting
from tests.integration.test_degraded_startup import (  # noqa: F401  (fixture)
    _CHAINS,
    _CONFIGURATION,
    _SEED,
    _Chain,
    _admin,
    lifecycle_registry,
)

pytestmark = pytest.mark.asyncio


def _snapshot(path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


async def test_starting_the_storefront_and_opening_its_stores_changes_no_schema(
    tmp_path, monkeypatch, lifecycle_registry
):
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    path = tmp_path / "storefront.db"
    migrate_storefront_database(path)
    migrated = _snapshot(path)

    chain = _Chain()
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=chain.constructor,
            alkahest_json_rpc=chain.rpc,
        ),
    )
    configuration = {**_CONFIGURATION, "db_path": str(path)}
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
        async with app.router.lifespan_context(app):
            async with _admin(app) as admin:
                health = await admin.get_health()
                await admin.admin_pause_lifecycle_loops()
                await admin.admin_run_lifecycle_cycle("publication")
                await admin.get_system_status()

    assert health.checks["database"] == "ok"
    assert _snapshot(path) == migrated


async def test_the_storefront_refuses_to_start_on_a_database_it_has_not_migrated(
    tmp_path, monkeypatch, lifecycle_registry
):
    """Startup checks the database before anything opens it: with none migrated
    it refuses, naming the migration command, and creates no file."""
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    path = tmp_path / "storefront.db"
    chain = _Chain()
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=chain.constructor,
            alkahest_json_rpc=chain.rpc,
        ),
    )
    configuration = {**_CONFIGURATION, "db_path": str(path)}
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
        with pytest.raises(IncompatibleStorefrontDatabase) as refused:
            async with app.router.lifespan_context(app):
                pass

    assert "`market-storefront-migrate`" in str(refused.value)
    assert not path.exists()
