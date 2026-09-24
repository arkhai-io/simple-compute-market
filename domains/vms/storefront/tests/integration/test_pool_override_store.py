"""The pool override store on a real database, and derivation reading it.

The repository and migration are proven against SQLite directly. Derivation is
proven through ``available_compute_slices`` and the structural-key reader
reconciliation uses, both of which read the store from the same database file.
"""

from __future__ import annotations

import sqlite3

import pytest
from arkhai_vms import vm_shape_digest
from domains.vms.listings import (
    available_compute_slices,
    current_available_resource_keys,
    declared_shape_feasibility,
)
from domains.vms.listings.reconciler import derivation_reports
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_row,
)

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility
from market_storefront.utils.sqlite_client import SQLiteClient

pytestmark = pytest.mark.asyncio

SITE = "site-a"
DECLARED = {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 2000}
SMALL = {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
         "memory": {"gib": 64}, "storage": {"gib": 100}}
HINTED = {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}


def _client(path) -> SQLiteClient:
    return SQLiteClient(
        db_path=str(path),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


@pytest.fixture
def repository(tmp_path) -> SQLiteClient:
    return _client(tmp_path / "overrides.db")


def _pool(pool_id: str = "gpu", *, shapes=None) -> dict:
    tags = {"listing_cardinality_mode": "fungible", "region": "us-east"}
    if shapes is not None:
        tags["listing_shapes"] = {"vm": shapes}
    return build_resource_pool_row(
        pool_id,
        policy_tags=tags,
        resources=[
            build_projected_resource(
                f"{pool_id}-m1",
                capacity=DECLARED,
                attributes={"gpu_model": "H100", "region": "us-east"},
            )
        ],
    )


# -- migration -----------------------------------------------------------------


async def test_a_fresh_database_has_the_store_and_a_rerun_changes_nothing(tmp_path):
    path = tmp_path / "fresh.db"
    first = _client(path)
    await first.replace_pool_override({"site_id": SITE, "pool_id": "gpu", "sla": 99.0})

    _client(path)  # migrations run again at construction

    conn = sqlite3.connect(path)
    try:
        applied = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations "
            "WHERE id = '20260924_011_storefront_pool_overrides'"
        ).fetchone()[0]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(storefront_pool_overrides)")]
    finally:
        conn.close()
    assert applied == 1
    assert columns[:2] == ["site_id", "pool_id"]
    assert (await first.get_pool_override(site_id=SITE, pool_id="gpu"))["sla"] == 99.0


# -- repository ----------------------------------------------------------------


async def test_replacement_clears_unset_fields_and_keeps_created_at(repository):
    first = await repository.replace_pool_override(
        {"site_id": SITE, "pool_id": "gpu", "sla": 99.0, "min_price": "3",
         "listing_shapes": [SMALL]}
    )

    second = await repository.replace_pool_override(
        {"site_id": SITE, "pool_id": "gpu", "token": "0xtoken"}
    )

    assert (second["sla"], second["min_price"], second["listing_shapes"]) == (None, None, None)
    assert second["token"] == "0xtoken"
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


async def test_lists_are_filtered_by_site_and_ordered(repository):
    for site, pool in (("site-b", "gpu"), (SITE, "z"), (SITE, "gpu")):
        await repository.replace_pool_override({"site_id": site, "pool_id": pool})

    everything = await repository.list_pool_overrides()
    one_site = await repository.list_pool_overrides(site_id=SITE)

    assert [(o["site_id"], o["pool_id"]) for o in everything] == [
        (SITE, "gpu"), (SITE, "z"), ("site-b", "gpu"),
    ]
    assert [o["pool_id"] for o in one_site] == ["gpu", "z"]


async def test_delete_is_idempotent_and_reports_existence(repository):
    await repository.replace_pool_override({"site_id": SITE, "pool_id": "gpu"})

    assert await repository.delete_pool_override(site_id=SITE, pool_id="gpu") is True
    assert await repository.delete_pool_override(site_id=SITE, pool_id="gpu") is False
    assert await repository.get_pool_override(site_id=SITE, pool_id="gpu") is None


async def test_two_sites_hold_separate_overrides_for_one_pool_name(repository):
    await repository.replace_pool_override({"site_id": SITE, "pool_id": "gpu", "sla": 1.0})
    await repository.replace_pool_override({"site_id": "site-b", "pool_id": "gpu", "sla": 2.0})

    assert (await repository.get_pool_override(site_id=SITE, pool_id="gpu"))["sla"] == 1.0
    assert (await repository.get_pool_override(site_id="site-b", pool_id="gpu"))["sla"] == 2.0


# -- derivation reads the store ------------------------------------------------


async def test_a_stored_override_shapes_every_structural_key_reader(repository):
    """Publication and reconciliation must derive the same keys, or
    reconciliation would close every listing an override shaped."""
    await repository.replace_pool_override(
        {"site_id": SITE, "pool_id": "gpu", "listing_shapes": [SMALL]}
    )
    projection = {SITE: [_pool(shapes=[HINTED])]}

    slices = available_compute_slices(
        repository.db_path,
        home_site=SITE,
        site_pool_projection=projection,
        shape_feasible=vm_shape_feasibility(),
    )
    keys = current_available_resource_keys(
        repository.db_path,
        home_site=SITE,
        site_pool_projection=projection,
        shape_feasible=vm_shape_feasibility(),
    )

    assert [row["shape_digest"] for row in slices] == [vm_shape_digest(SMALL)]
    assert {row["shape_source"] for row in slices} == {"storefront_override"}
    assert keys == {row["resource_key"] for row in slices}


async def test_an_override_for_another_site_does_not_reach_this_one(repository):
    await repository.replace_pool_override(
        {"site_id": "site-b", "pool_id": "gpu", "listing_shapes": [SMALL]}
    )

    slices = available_compute_slices(
        repository.db_path,
        home_site=SITE,
        site_pool_projection={SITE: [_pool(shapes=[HINTED])]},
        shape_feasible=vm_shape_feasibility(),
    )

    assert {row["shape_source"] for row in slices} == {"pool_hint"}


# -- the write report's feasibility judge -------------------------------------


async def test_declared_feasibility_judges_an_override_as_derivation_would(repository):
    too_big = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 1024}}

    feasible = declared_shape_feasibility(
        repository.db_path,
        [_pool(), _pool("other")],
        site_id=SITE,
        pool_id="gpu",
        home_site=SITE,
        override={"listing_shapes": [SMALL, too_big]},
        shape_feasible=vm_shape_feasibility(),
    )

    assert feasible == {vm_shape_digest(SMALL): True, vm_shape_digest(too_big): False}


async def test_declared_feasibility_records_no_site_report(repository):
    before = derivation_reports()

    declared_shape_feasibility(
        repository.db_path,
        [_pool()],
        site_id="site-unreported",
        pool_id="gpu",
        home_site=SITE,
        override={"listing_shapes": [SMALL]},
        shape_feasible=vm_shape_feasibility(),
    )

    assert derivation_reports() == before


async def test_declared_feasibility_of_an_override_without_shapes_is_empty(repository):
    assert declared_shape_feasibility(
        repository.db_path,
        [_pool()],
        site_id=SITE,
        pool_id="gpu",
        home_site=SITE,
        override={"sla": 1.0},
        shape_feasible=vm_shape_feasibility(),
    ) == {}
