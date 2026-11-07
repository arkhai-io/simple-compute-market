"""The store and its migration on a real SQLite database."""

from __future__ import annotations

import sqlite3

import pytest

from market_pool_overrides import (
    PoolOverrideAddress,
    PoolOverrideRecord,
    SQLitePoolOverrideStore,
    pool_override_migrations,
)

SHAPE = {"gpu": {"count": 1, "model": "H100"}}


def _migrated(path) -> SQLitePoolOverrideStore:
    conn = sqlite3.connect(path)
    try:
        for migration in pool_override_migrations():
            migration.apply(conn)
        conn.commit()
    finally:
        conn.close()
    return SQLitePoolOverrideStore(str(path))


def _record(site="site-a", pool="gpu", mode="vm", **fields) -> PoolOverrideRecord:
    fields = fields or {"terms": {"sla": 99.0}}
    return PoolOverrideRecord(site_id=site, pool_id=pool, offering_mode=mode, **fields)


@pytest.fixture
def store(tmp_path) -> SQLitePoolOverrideStore:
    return _migrated(tmp_path / "store.db")


def test_the_migration_creates_the_table_and_a_rerun_changes_nothing(tmp_path):
    path = tmp_path / "rerun.db"
    _migrated(path)
    store = _migrated(path)

    conn = sqlite3.connect(path)
    try:
        key = [row[1] for row in conn.execute("PRAGMA table_info(pool_overrides)") if row[5]]
    finally:
        conn.close()
    assert key == ["site_id", "pool_id", "offering_mode"]
    assert store.db_path == str(path)


async def test_replacement_clears_unset_fields_and_keeps_created_at(store):
    first = await store.replace(_record(listing_shapes=[SHAPE], terms={"sla": 99.0}))

    second = await store.replace(_record(settlements=[{"mechanism": "m"}]))

    assert (second["listing_shapes"], second["terms"]) == (None, None)
    assert second["settlements"] == [{"mechanism": "m"}]
    assert second["created_at"] == first["created_at"]


async def test_one_pool_holds_an_independent_override_per_mode(store):
    await store.replace(_record(mode="vm", terms={"sla": 1.0}))
    await store.replace(_record(mode="kube_pod", terms={"sla": 2.0}))

    vm = await store.get(PoolOverrideAddress(site_id="site-a", pool_id="gpu", offering_mode="vm"))
    pod = await store.get(PoolOverrideAddress(site_id="site-a", pool_id="gpu", offering_mode="kube_pod"))

    assert (vm["terms"], pod["terms"]) == ({"sla": 1.0}, {"sla": 2.0})


async def test_lists_filter_by_site_then_pool(store):
    for site, pool, mode in (("site-b", "gpu", "vm"), ("site-a", "z", "vm"),
                             ("site-a", "gpu", "vm"), ("site-a", "gpu", "kube_pod")):
        await store.replace(_record(site, pool, mode))

    everything = await store.list()
    site_a_gpu = await store.list(site_id="site-a", pool_id="gpu")

    assert [(o["site_id"], o["pool_id"], o["offering_mode"]) for o in everything] == [
        ("site-a", "gpu", "kube_pod"), ("site-a", "gpu", "vm"), ("site-a", "z", "vm"),
        ("site-b", "gpu", "vm"),
    ]
    assert [o["offering_mode"] for o in site_a_gpu] == ["kube_pod", "vm"]


async def test_delete_is_idempotent_and_reports_existence(store):
    address = PoolOverrideAddress(site_id="site-a", pool_id="gpu", offering_mode="vm")
    await store.replace(_record())

    assert await store.delete(address) is True
    assert await store.delete(address) is False
    assert await store.get(address) is None


def test_the_reader_returns_one_modes_overrides_decoded(tmp_path):
    import asyncio

    from market_pool_overrides import read_pool_overrides

    store = _migrated(tmp_path / "reader.db")
    asyncio.run(store.replace(_record(mode="vm", listing_shapes=[SHAPE], terms={"sla": 1.0})))
    asyncio.run(store.replace(_record(pool="other", mode="kube_pod", terms={"sla": 2.0})))

    conn = sqlite3.connect(store.db_path)
    try:
        (vm,) = read_pool_overrides(conn, offering_mode="vm")
    finally:
        conn.close()

    assert (vm.site_id, vm.pool_id, vm.offering_mode) == ("site-a", "gpu", "vm")
    assert (vm.listing_shapes, vm.settlements, vm.terms) == ([SHAPE], None, {"sla": 1.0})
    assert vm.problems == ()


def test_a_database_without_the_store_reads_as_no_overrides(tmp_path):
    from market_pool_overrides import read_pool_overrides

    conn = sqlite3.connect(tmp_path / "empty.db")
    try:
        assert read_pool_overrides(conn, offering_mode="vm") == []
    finally:
        conn.close()


def test_an_undecodable_field_is_kept_and_named(tmp_path):
    from market_pool_overrides import read_pool_overrides

    path = tmp_path / "corrupt.db"
    _migrated(path)
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO pool_overrides (site_id, pool_id, offering_mode, listing_shapes) "
                "VALUES ('site-a', 'gpu', 'vm', '[not json')"
            )
        (row,) = read_pool_overrides(conn, offering_mode="vm")
    finally:
        conn.close()

    assert row.listing_shapes == "[not json"
    assert row.problems == ("listing_shapes: the stored value is not JSON",)
