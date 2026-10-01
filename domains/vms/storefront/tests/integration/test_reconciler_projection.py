"""Which source derivation reads, what it holds, and what it prices.

These cases call production derivation directly against a real SQLite
database: an empty projection is not the local tables, an unknown configured
site is held rather than read as empty, another market's stored overrides do not
reach VM derivation, and asking rates resolve, hold, and refresh as the
precedence rules say. No application runs, so under docs/development/TESTING.md
they are focused evidence for derivation's own rules rather than integration
evidence. The storefront's integration evidence for the same paths drives the
real app through its typed clients, in test_pool_overrides_api.py. The database
fixture and seeding helpers are the reconciler unit module's.
"""

from __future__ import annotations

import asyncio
import sqlite3

from arkhai_vms.storefront_adapter import vm_listing_resource_for_listing
from arkhai_vms_listings.listing_comparison import (
    TERMS_DIFFER,
    compare_listing,
    refreshed_listing_resource,
)
from arkhai_vms_listings.pricing_resolution import GpuPricingFields
from arkhai_vms_listings.reconciler import PoolHintResolutionSettings, derivation_reports
from market_pool_overrides import (
    PoolOverrideRecord,
    SQLitePoolOverrideStore,
    pool_override_migrations,
)

from tests.unit.test_reconciler import (  # noqa: F401  (db_path is a fixture)
    _BIG,
    available_compute_slices,
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


# ---------------------------------------------------------------------------
# Asking rates
# ---------------------------------------------------------------------------

_LARGE_SHAPE = {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}


def _rate(shape, amount, *, asset="usd", period="hour"):
    return {"shape": shape, "amount": amount, "asset": asset, "period": period}


def _priced_pool(rates, *, shapes=(_SMALL_SHAPE, _LARGE_SHAPE)):
    pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=list(shapes))
    pool["pool_metadata"]["policy_tags"]["asking_rates"] = {"vm": rates}
    return pool


def _store_override(db_path, **stated):
    conn = sqlite3.connect(db_path)
    try:
        for migration in pool_override_migrations():
            migration.apply(conn)
        conn.commit()
    finally:
        conn.close()
    asyncio.run(
        SQLitePoolOverrideStore(db_path).replace(
            PoolOverrideRecord(offering_mode="vm", **stated)
        )
    )


def _rates_by_gpu_count(slices):
    return {row["gpu_count"]: row.get("asking_rate") for row in slices}


def test_a_pool_declaration_prices_each_shape_it_names(db_path):
    slices = _shape_slices(
        db_path,
        [_priced_pool([_rate(_SMALL_SHAPE, "2.10"), _rate(_LARGE_SHAPE, "16.00")])],
    )

    assert _rates_by_gpu_count(slices) == {
        1: {"amount": "2.10", "asset": "usd", "period": "hour"},
        2: {"amount": "16.00", "asset": "usd", "period": "hour"},
    }


def test_a_shape_nothing_prices_publishes_no_rate_field(db_path):
    slices = _shape_slices(db_path, [_priced_pool([_rate(_SMALL_SHAPE, "2.10")])])

    large = next(row for row in slices if row["gpu_count"] == 2)
    assert "asking_rate" not in large


def test_a_storefront_with_pricing_defaults_and_no_declaration_publishes_no_rate(db_path):
    """No configuration default supplies a rate, whatever pricing is configured."""
    slices = available_compute_slices(
        db_path,
        home_site="site-a",
        site_pool_projection={
            "site-a": [_shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])]
        },
        hint_resolution=PoolHintResolutionSettings(
            # Development fixture address; never used on a public network.
            gpu_pricing_flat_default=GpuPricingFields(
                min_price="2", token="0x" + "22" * 20
            ),
        ),
    )

    assert slices and all("asking_rate" not in row for row in slices)


def test_an_override_at_a_non_first_site_replaces_that_sites_declared_rates(db_path):
    _store_override(
        db_path, site_id="site-b", pool_id="gpu", asking_rates=[_rate(_SMALL_SHAPE, "1.90")]
    )
    pool = _priced_pool([_rate(_SMALL_SHAPE, "2.10"), _rate(_LARGE_SHAPE, "16.00")])

    slices = available_compute_slices(
        db_path,
        home_site="site-a",
        site_pool_projection={"site-a": [pool], "site-b": [pool]},
        configured_sites=("site-a", "site-b"),
    )
    by_site = {
        site: _rates_by_gpu_count([r for r in slices if r["site_id"] == site])
        for site in ("site-a", "site-b")
    }

    assert by_site["site-a"][1]["amount"] == "2.10"
    assert by_site["site-a"][2]["amount"] == "16.00"
    # The override replaces the list as a whole: the large shape it does not
    # price publishes no rate, rather than inheriting the pool's.
    assert by_site["site-b"] == {
        1: {"amount": "1.90", "asset": "usd", "period": "hour"},
        2: None,
    }


def test_an_empty_override_withholds_every_rate(db_path):
    _store_override(db_path, site_id="site-a", pool_id="gpu", asking_rates=[])

    slices = _shape_slices(
        db_path,
        [_priced_pool([_rate(_SMALL_SHAPE, "2.10"), _rate(_LARGE_SHAPE, "16.00")])],
    )

    assert slices and all("asking_rate" not in row for row in slices)


def test_an_unreadable_declaration_holds_its_pool(db_path):
    holds: set = set()
    slices = _shape_slices(
        db_path, [_priced_pool([_rate(_SMALL_SHAPE, "2.10", period="month")])], holds=holds
    )

    assert slices == []
    assert ("pool", "site-a", "gpu") in holds
    assert "period" in derivation_reports()["site-a"]["unreadable_asking_rates"]["gpu"][0]


def test_an_unreadable_override_holds_its_pool_rather_than_falling_through(db_path):
    """The override names a shape outside the VM vocabulary. A valid pool
    declaration is below it, and must not speak for it."""
    conn = sqlite3.connect(db_path)
    try:
        for migration in pool_override_migrations():
            migration.apply(conn)
        with conn:
            conn.execute(
                "INSERT INTO pool_overrides (site_id, pool_id, offering_mode, asking_rates) "
                "VALUES ('site-a', 'gpu', 'vm', ?)",
                ('[{"shape": {"gpu": {"count": 1}}, "amount": "1", "asset": "usd", '
                 '"period": "hour"}]',),
            )
    finally:
        conn.close()
    holds: set = set()

    slices = _shape_slices(db_path, [_priced_pool([_rate(_SMALL_SHAPE, "2.10")])], holds=holds)

    assert slices == []
    assert ("pool", "site-a", "gpu") in holds


def test_a_rate_for_a_shape_the_pool_does_not_publish_is_reported(db_path):
    unlisted = {"gpu": {"count": 4, "model": "H100"}}
    slices = _shape_slices(
        db_path,
        [_priced_pool([_rate(_SMALL_SHAPE, "2.10"), _rate(unlisted, "8.00")],
                      shapes=[_SMALL_SHAPE])],
    )

    assert _rates_by_gpu_count(slices) == {1: {"amount": "2.10", "asset": "usd", "period": "hour"}}
    (reported,) = derivation_reports()["site-a"]["unpublished_asking_rates"]["gpu"]
    assert reported["shape"] == unlisted


def test_a_rate_change_or_removal_refreshes_in_place(db_path):
    """Price is a term of sale: a changed or withdrawn rate keeps the listing's
    key and refreshes the published resource, never closing the listing."""
    def _derive(rates):
        (row,) = [
            r for r in _shape_slices(db_path, [_priced_pool(rates, shapes=[_SMALL_SHAPE])])
        ]
        return row["resource_key"], vm_listing_resource_for_listing(row)

    key, stored = _derive([_rate(_SMALL_SHAPE, "2.10")])
    for changed in (
        [_rate(_SMALL_SHAPE, "2.40")],
        [_rate(_SMALL_SHAPE, "2.10", asset="eur")],
        [],
    ):
        fresh_key, fresh = _derive(changed)
        assert fresh_key == key

        comparison = compare_listing(
            stored_resource=stored,
            stored_terms={},
            fresh_resource=fresh,
            fresh_terms={},
            binding_backing="backed",
            source_backing="backed",
        )
        assert comparison.outcome == TERMS_DIFFER
        assert comparison.differing_fields == ("asking_rate",)

        refreshed = refreshed_listing_resource(
            stored_resource=stored, fresh_resource=fresh, binding_backing="backed"
        )
        assert refreshed.get("asking_rate") == fresh.get("asking_rate")
