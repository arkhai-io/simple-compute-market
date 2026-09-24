"""Which source derivation reads, and what it holds, on a real database.

These are the reconciler's cases whose meaning this module's rules define: an
empty projection is not the local tables, an unknown configured site is held
rather than read as empty, and another market's stored overrides do not reach VM
derivation. Each runs production derivation against real SQLite, so it is an
integration test. The database fixture and seeding helpers are the reconciler
unit module's; the rest of that module's database-backed cases move here when
it is next changed.
"""

from __future__ import annotations

import asyncio
import sqlite3

from market_pool_overrides import (
    PoolOverrideRecord,
    SQLitePoolOverrideStore,
    pool_override_migrations,
)

from tests.unit.test_reconciler import (  # noqa: F401  (db_path is a fixture)
    _BIG,
    _SMALL_SHAPE,
    _available_vm_slices,
    _member,
    _seed_listing,
    _seed_pool,
    _shape_slices,
    _shaped_pool,
    db_path,
    stale_open_listing_ids,
)


def test_none_projection_selects_the_local_tables(db_path):
    """Only an omitted or ``None`` projection selects the local tables."""
    _seed_pool(db_path, gpu_count=2)
    without_arg = _available_vm_slices(db_path, home_site="site-a")
    with_none = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=None)
    assert without_arg == with_none
    assert without_arg


def test_an_empty_projection_derives_nothing_and_holds_every_configured_site(db_path):
    """No site's projection is known: nothing is read from the local tables,
    which only configuration selects, and every configured site is held."""
    _seed_pool(db_path, gpu_count=2)  # local data exists
    holds: set = set()
    slices = _available_vm_slices(
        db_path, home_site="site-a", site_pool_projection={},
        configured_sites=("site-a", "site-b"), holds=holds,
    )
    assert slices == []
    assert holds == {("site", "site-a", ""), ("site", "site-b", "")}


def test_an_unknown_sites_listing_is_held_while_an_empty_known_sites_is_stale(db_path):
    _seed_listing(db_path, listing_id="at-b", pool_id="gpu-pool", site_id="site-b")

    unknown = stale_open_listing_ids(
        db_path, home_site="site-a", configured_sites=("site-a", "site-b"),
        site_pool_projection={"site-a": []}, backed_only=False,
    )
    known_empty = stale_open_listing_ids(
        db_path, home_site="site-a", configured_sites=("site-a", "site-b"),
        site_pool_projection={"site-a": [], "site-b": []}, backed_only=False,
    )

    assert unknown == []
    assert known_empty == ["at-b"]


def test_another_modes_stored_override_does_not_reach_vm_derivation(db_path):
    conn = sqlite3.connect(db_path)
    try:
        for migration in pool_override_migrations():
            migration.apply(conn)
        conn.commit()
    finally:
        conn.close()
    asyncio.run(
        SQLitePoolOverrideStore(db_path).replace(
            PoolOverrideRecord(
                site_id="site-a", pool_id="gpu", offering_mode="kube_pod",
                listing_shapes=[{"gpu": {"count": 8, "model": "H100"}}],
            )
        )
    )

    slices = _shape_slices(
        db_path, [_shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])]
    )

    assert {row["shape_source"] for row in slices} == {"pool_hint"}


def test_an_undecodable_stored_override_holds_its_pool(db_path):
    from domains.vms.listings.reconciler import derivation_reports

    conn = sqlite3.connect(db_path)
    try:
        for migration in pool_override_migrations():
            migration.apply(conn)
        with conn:
            conn.execute(
                "INSERT INTO pool_overrides (site_id, pool_id, offering_mode, terms) "
                "VALUES ('site-a', 'gpu', 'vm', '{not json')"
            )
    finally:
        conn.close()
    holds: set = set()

    slices = _shape_slices(
        db_path,
        [_shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])],
        holds=holds,
    )

    # Unreadable is not absent: the pool is held, not published from its hint.
    assert slices == []
    assert ("pool", "site-a", "gpu") in holds
    assert derivation_reports()["site-a"]["unreadable_shapes"]["gpu"] == [
        "storefront_override: terms: the stored value is not JSON"
    ]
