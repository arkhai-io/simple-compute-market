"""Unit tests for domains.vms.listings.reconciler.

External boundary: a real sqlite3 file DB with a minimal hand-built
schema (not the full SQLiteClient migration chain) -- reconciler.py is
itself plain synchronous sqlite3 code with no async dependencies, so a
minimal schema exercising exactly the tables it reads/writes is the
right level, matching test_compute_allocations.py's precedent.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_migrations import (
    migrate_listing_binding_capacity_backing,
    migrate_listing_binding_capacity_backing_required,
    migrate_listing_closed_by,
    migrate_storefront_domain_bindings_schema,
)
from market_identity import Identity
from market_site.projections import resource_pool_projection

from domains.vms.listings.pricing_resolution import GpuPricingFields
from domains.vms.listings.reconciler import (
    PoolHintResolutionSettings,
    _accumulate_capacity_pool_member,
    _fungible_availability_from_buckets,
    _member_available_units,
    _project_legacy_resource_row,
    _projected_pool_rows as _projected_pool_rows_impl,
    _SiteDerivationReport,
    _projected_resource_usage,
    available_compute_slices as _available_compute_slices,
    closed_available_listing_ids as _closed_available_listing_ids,
    current_available_resource_keys as _current_available_resource_keys,
    listing_pool_key,
    listing_resource_key,
    listing_shape_key,
    open_listing_resource_keys,
    pool_id_for_listing,
    site_id_for_listing,
    stale_open_listing_ids as _stale_open_listing_ids,
)
from domains.vms.listings.listing_shapes import resolve_shape
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.services.shape_feasibility import SiteShapeFeasibility

# Every derivation judges shapes with the storefront's real feasibility, built
# on the site's own predicate, unless a test injects its own.
_FEASIBILITY = SiteShapeFeasibility()


def _judged(function):
    def call(*args, **kwargs):
        kwargs.setdefault("shape_feasible", _FEASIBILITY)
        return function(*args, **kwargs)

    return call


available_compute_slices = _judged(_available_compute_slices)
closed_available_listing_ids = _judged(_closed_available_listing_ids)
current_available_resource_keys = _judged(_current_available_resource_keys)
stale_open_listing_ids = _judged(_stale_open_listing_ids)


def _gpu_key(site_id: str, *, gpu_count: int, model: str, pool_id=None, resource_id=None) -> str:
    """The key of a default GPU-only shape."""
    return listing_shape_key(
        site_id,
        shape_digest=resolve_shape({"gpu": {"count": gpu_count, "model": model}}).digest,
        pool_id=pool_id,
        resource_id=resource_id,
    )


_VM_DOMAIN = build_vm_storefront_domain()
_VM_REGISTRY = build_vm_storefront_registry(_VM_DOMAIN)
_VM_REGISTRATION = _VM_REGISTRY.resolve_mode("vm")
_VM_BINDING = _VM_REGISTRATION.binding
assert _VM_REGISTRY.resolve(_VM_BINDING) is _VM_DOMAIN


def _vm_pool(pool: dict) -> dict:
    """Return a projection row with the exact VM deliverable declaration."""
    projected = dict(pool)
    metadata = dict(projected.get("pool_metadata") or {})
    policy_tags = dict(metadata.get("policy_tags") or {})
    policy_tags["deliverable_modes"] = ["vm"]
    metadata["policy_tags"] = policy_tags
    projected["pool_metadata"] = metadata
    return projected


def _available_vm_slices(db_path: str, **kwargs):
    projection = kwargs.get("site_pool_projection")
    if projection is not None:
        kwargs["site_pool_projection"] = {
            site_id: [_vm_pool(pool) for pool in pools]
            for site_id, pools in projection.items()
        }
    return available_compute_slices(db_path, **kwargs)


def _project_vm_pool_rows(pool: dict, **kwargs):
    return _projected_pool_rows(_vm_pool(pool), **kwargs)



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _projected_pool_rows(pool, **kwargs):
    """Call the row builder the way a projection pass does for one pool.

    The declaration is read from the pool's own projected tags under the same
    per-site rule, so a test pool carrying no declarations reads under the
    compatibility rule exactly as a lone pool from an older producer would.
    """
    from market_resource_pools import ResolvedPool, read_site_declarations

    pool_id = str(pool.get("resource_pool_id") or "").strip()
    declaration = read_site_declarations([pool]).resolved.get(pool_id) or ResolvedPool(
        "backed", frozenset(), True
    )
    kwargs.setdefault("declaration", declaration)
    kwargs.setdefault("holds", set())
    kwargs.setdefault("report", _SiteDerivationReport())
    kwargs.setdefault("shape_feasible", _FEASIBILITY)
    return _projected_pool_rows_impl(pool, **kwargs)


def _term(row: dict, field: str):
    """A row's listing term, as a slice takes it: its shapes' model's terms.

    Terms resolve per GPU model; a projection row carries no row-level price.
    The model is the one its feasible shapes name, else the only one it has
    terms for.
    """
    models = {shape.gpu_model for shape in row["feasible_shapes"]} or set(
        row["pricing_by_model"]
    )
    (model,) = models
    return getattr(row["pricing_by_model"][model], field)


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "reconciler_test.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              listing_resource TEXT,
              accepted_escrows TEXT,
              demands TEXT,
              max_duration_seconds INTEGER,
              seller TEXT,
              paused INTEGER,
              updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE negotiation_threads (
              negotiation_id TEXT PRIMARY KEY
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE compute_capacity_pools (
              pool_id TEXT PRIMARY KEY,
              resource_type TEXT,
              gpu_model TEXT,
              region TEXT,
              sla REAL,
              total_gpu_count INTEGER,
              status TEXT,
              min_price TEXT,
              token TEXT,
              max_duration_seconds INTEGER,
              accepted_escrows TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE compute_pool_members (
              pool_id TEXT,
              resource_id TEXT,
              gpu_count INTEGER,
              status TEXT,
              attributes TEXT,
              site TEXT
            )
            """
        )
        migrate_storefront_domain_bindings_schema(conn)
        migrate_listing_binding_capacity_backing(conn)
        migrate_listing_binding_capacity_backing_required(conn)
        migrate_listing_closed_by(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _seed_fungible_pool(
    db_path: str,
    *,
    pool_id: str = "gpu-pool",
    member_gpu_counts: tuple[int, ...] = (2, 2),
    pool_status: str = "active",
    member_status: str = "active",
):
    """A pool with more than one member, so available_compute_slices
    treats it as genuinely fungible (pool-keyed) rather than collapsing
    to a single-resource-keyed pool -- see is_fungible_pool."""
    total = sum(member_gpu_counts)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO compute_capacity_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, min_price, token, max_duration_seconds, accepted_escrows
            ) VALUES (?, 'compute.gpu', 'H100', 'us-east', 99.9, ?, ?, '10', '0xtoken', 3600, '[]')
            """,
            (pool_id, total, pool_status),
        )
        for i, count in enumerate(member_gpu_counts):
            conn.execute(
                """
                INSERT INTO compute_pool_members(
                  pool_id, resource_id, gpu_count, status, attributes, site
                ) VALUES (?, ?, ?, ?, '{}', NULL)
                """,
                (pool_id, f"resource-{i}", count, member_status),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_pool(
    db_path: str,
    *,
    pool_id: str = "gpu-pool",
    resource_id: str = "resource-1",
    gpu_count: int = 4,
    pool_status: str = "active",
    member_status: str = "active",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO compute_capacity_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, min_price, token, max_duration_seconds, accepted_escrows
            ) VALUES (?, 'compute.gpu', 'H100', 'us-east', 99.9, ?, ?, '10', '0xtoken', 3600, '[]')
            """,
            (pool_id, gpu_count, pool_status),
        )
        conn.execute(
            """
            INSERT INTO compute_pool_members(
              pool_id, resource_id, gpu_count, status, attributes, site
            ) VALUES (?, ?, ?, ?, '{}', NULL)
            """,
            (pool_id, resource_id, gpu_count, member_status),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_listing_binding(
    db_path: str,
    *,
    listing_id: str,
    site_id: str,
    pool_id: str | None,
    resource_id: str | None,
    gpu_count: int,
    gpu_model: str = "H100",
    schema_version: int = 2,
) -> None:
    """Bind a listing as publication does: version 2 carries the listing's
    shape; version 1 is how listings were bound before shapes."""
    payload: dict = {"site_id": site_id, "pool_id": pool_id, "resource_id": resource_id}
    if schema_version == 1:
        payload["gpu_count"] = gpu_count
    else:
        payload["listing_shape"] = {"gpu": {"count": gpu_count, "model": gpu_model}}
    source = {
        "kind": "compute.listing_source",
        "schema_version": schema_version,
        "payload": payload,
    }
    binding = StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=site_id,
        binding=_VM_BINDING,
        derivation_key=build_storefront_derivation_key(
            site_id=site_id,
            offering_mode=_VM_BINDING.offering_mode,
            binding=_VM_BINDING,
            source_identity=source,
        ),
        source_envelope=source,
        last_reconciled_at="2026-08-15T00:00:00Z",
        capacity_backing="backed",
        pool_id=pool_id,
        physical_resource_id=resource_id,
    )
    values = binding.as_record()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO storefront_listing_bindings(
              listing_id, site_id, pool_id, physical_resource_id,
              offering_mode, domain_identity, contract_major, contract_minor,
              derivation_key, source_envelope_json, last_reconciled_at,
              capacity_backing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(values.values()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_listing(
    db_path: str,
    *,
    listing_id: str,
    status: str = "open",
    closed_by: str | None = None,
    pool_id: str | None = "gpu-pool",
    resource_id: str | None = None,
    gpu_count: int = 2,
    site_id: str | None = None,
    gpu_model: str = "H100",
    schema_version: int = 2,
):
    listing_resource = {"offering_mode": "vm", "gpu_count": gpu_count, "gpu_model": gpu_model}
    if pool_id:
        listing_resource["pool_id"] = pool_id
    if resource_id:
        listing_resource["resource_id"] = resource_id
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO listings(listing_id, status, listing_resource, closed_by) "
            "VALUES (?, ?, ?, ?)",
            (
                listing_id,
                status,
                json.dumps(listing_resource),
                closed_by
                if closed_by is not None or status != "closed"
                else "reconciliation",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if site_id is not None:
        _seed_listing_binding(
            db_path,
            listing_id=listing_id,
            site_id=site_id,
            pool_id=pool_id,
            resource_id=resource_id,
            gpu_count=gpu_count,
            gpu_model=gpu_model,
            schema_version=schema_version,
        )


# ---------------------------------------------------------------------------
# listing_pool_key / listing_resource_key -- validation
# ---------------------------------------------------------------------------

class TestKeyValidation:
    def test_pool_key_requires_nonempty_site_id(self):
        with pytest.raises(ValueError):
            listing_pool_key("", "pool-a", 2)

    def test_resource_key_requires_nonempty_site_id(self):
        with pytest.raises(ValueError):
            listing_resource_key("   ", "resource-a", 2)

    def test_different_sites_produce_different_keys_for_the_same_pool(self):
        assert listing_pool_key("site-a", "pool-a", 2) != listing_pool_key("site-b", "pool-a", 2)

    def test_same_site_and_pool_are_deterministic(self):
        assert listing_pool_key("site-a", "pool-a", 2) == listing_pool_key("site-a", "pool-a", 2)

    def test_no_collision_when_a_colon_shifts_the_field_boundary(self):
        """site_id/pool_id are operator-chosen strings with no character
        restrictions -- a naive colon-delimited join would let
        (site_id='a', pool_id='b:c') and (site_id='a:b', pool_id='c')
        produce an identical string. The length-prefixed encoding must
        not collide here."""
        assert listing_pool_key("a", "b:c", 2) != listing_pool_key("a:b", "c", 2)
        assert listing_resource_key("a", "b:c", 2) != listing_resource_key("a:b", "c", 2)

    def test_no_collision_with_digit_and_colon_adversarial_inputs(self):
        """A field value that looks like a length prefix itself (e.g.
        "3:xyz") must not be confusable with the real encoding."""
        assert listing_pool_key("1:a", "b", 2) != listing_pool_key("1", "a:b", 2)

    def test_no_collision_across_many_boundary_shifts(self):
        """Broader sweep: many different (site_id, pool_id) splits of the
        same underlying characters must all produce distinct keys."""
        pairs = [
            ("a", "bcde"), ("ab", "cde"), ("abc", "de"), ("abcd", "e"),
        ]
        keys = {listing_pool_key(site, pool, 2) for site, pool in pairs}
        assert len(keys) == len(pairs)


# ---------------------------------------------------------------------------
# available_compute_slices
# ---------------------------------------------------------------------------

class TestAvailableComputeSlices:
    def test_every_slice_is_tagged_with_home_site(self, db_path):
        _seed_pool(db_path)
        slices = _available_vm_slices(db_path, home_site="site-a")
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)

    def test_resource_key_is_site_scoped(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        slices = _available_vm_slices(db_path, home_site="site-a")
        assert slices[0]["resource_key"] == _gpu_key(
            "site-a", gpu_count=1, model="H100", resource_id="resource-1",
        )

    def test_different_home_site_produces_different_keys_for_identical_data(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        keys_a = {r["resource_key"] for r in _available_vm_slices(db_path, home_site="site-a")}
        keys_b = {r["resource_key"] for r in _available_vm_slices(db_path, home_site="site-b")}
        assert keys_a and keys_b
        assert keys_a.isdisjoint(keys_b)

    def test_a_site_mapped_to_an_authoritative_empty_projection_does_not_fall_back(
        self, db_path,
    ):
        """The downstream half of the site_pool_projection() None-vs-[]
        fix: {"site-a": []} is a non-empty mapping (one key), so it must
        take the projection path and correctly contribute zero rows for
        that site -- not be treated the same as {} (no site data at
        all), which would incorrectly fall back to stale local data even
        though the authoritative answer is "this site has zero pools
        right now"."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)  # local data exists
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection={"site-a": []},)
        assert slices == []

    def test_projection_sourced_pool_uses_local_pricing_for_home_site(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)  # local pricing row
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            # The local row publishes region us-east; a claim
                            # matches it against the declaration.
                            "attributes": {"gpu_model": "H100", "region": "us-east"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)
        # Structure/GPU model from the projection (8, not the local
        # table's seeded 4), pricing from the local table.
        assert max(row["gpu_count"] for row in slices) == 8
        assert all(row["gpu_model"] == "H100" for row in slices)
        assert all(row["min_price"] == "10" for row in slices)  # _seed_pool's fixed price

    def test_projection_pool_for_non_home_site_never_uses_another_sites_local_row(
        self, db_path,
    ):
        """The core safety property: a non-home-site pool must never pick
        up another site's local pricing row, even when the pool_id
        happens to match -- compute_capacity_pools is not site-scoped,
        so this is the only thing preventing a cross-site mix-up. It
        still publishes (priceless, since it has no hint/config default
        of its own either) -- a missing storefront override is not a
        reason to suppress the pool."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-b": [  # not home_site
                {
                    "resource_pool_id": "gpu-pool",  # same pool_id as the local row
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(s.get("min_price") is None for s in slices)
        assert all(s.get("region") is None for s in slices)

    def test_projection_pool_with_no_local_pricing_row_publishes_priceless(
        self, db_path,
    ):
        """A home-site pool with no matching local compute_capacity_pools
        row has no storefront-override price -- it still publishes,
        priceless, rather than being excluded."""
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "unpriced-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 4},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(s.get("min_price") is None for s in slices)

    def test_projection_disabled_resource_excluded_from_capacity(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            "attributes": {},
                            "enabled": False,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices == []

    def test_multiple_sites_both_publish_but_only_home_site_gets_local_pricing(
        self, db_path,
    ):
        """Corrected from an earlier "only home_site pool is published"
        expectation: both sites' pools now publish (a missing storefront
        override is not a reason to suppress a pool), but only the
        home-site pool's local `compute_capacity_pools` row is ever
        consulted -- site-b's pool has no hint/config default either, so
        it publishes priceless, not with site-a's price."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-a": [{
                "resource_pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100", "region": "us-east"},
                    "enabled": True,
                }],
            }],
            "site-b": [{
                "resource_pool_id": "other-pool",
                "resources": [{
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                }],
            }],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        by_site = {}
        for row in slices:
            by_site.setdefault(row["site_id"], []).append(row)
        assert set(by_site) == {"site-a", "site-b"}
        assert all(row["min_price"] == "10" for row in by_site["site-a"])
        assert all(row["min_price"] is None for row in by_site["site-b"])

    def test_resource_keys_are_identical_regardless_of_hint_resolution(self, db_path):
        """The invariant `current_available_resource_keys`/
        `stale_open_listing_ids`/`closed_available_listing_ids` all rely
        on without any of them threading `hint_resolution` through:
        `resource_key`/`legacy_resource_key` never depend on resolved
        region/SLA/pricing, however different `hint_resolution` makes
        those fields. Capacity-delta reconciliation compares structural
        derivation keys and availability; it never recomputes or
        republishes commercial listing terms -- this proves that holds,
        rather than only asserting it in a comment. No local
        `compute_capacity_pools` row on purpose -- a storefront override
        would win regardless of `hint_resolution` and this test would
        prove nothing about the tiers that actually vary."""
        projection = {
            "site-a": [{
                "resource_pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                }],
            }],
        }
        default_rows = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        varied_rows = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=7.0,
            gpu_pricing_defaults_by_model={
                "H100": GpuPricingFields(min_price="0.01"),
            },
        ),)
        default_keys = {r["resource_key"] for r in default_rows}
        varied_keys = {r["resource_key"] for r in varied_rows}
        assert default_keys == varied_keys
        assert default_keys  # not vacuously true
        # Confirm the two runs actually resolved *different* commercial
        # values -- otherwise this test wouldn't be exercising anything.
        assert {r["sla"] for r in default_rows} != {r["sla"] for r in varied_rows}


# ---------------------------------------------------------------------------
# site_id_for_listing
# ---------------------------------------------------------------------------

class TestSiteIdForListing:
    def test_returns_none_when_listing_has_no_durable_binding(self, db_path):
        assert site_id_for_listing(db_path, "listing-1") is None

    def test_returns_the_registry_owned_binding_site(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        assert site_id_for_listing(db_path, "listing-1") == "site-a"


# ---------------------------------------------------------------------------
# record_derived_listing / load_derived_listing_for_slice round trip
# ---------------------------------------------------------------------------

class TestPoolIdForListing:
    def test_returns_registry_owned_pool_id(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"

    def test_none_for_unmapped_listing(self, db_path):
        assert pool_id_for_listing(db_path, "listing-none") is None

    def test_resource_only_binding_does_not_invent_a_pool_id(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id=None,
            resource_id="res-1",
            gpu_count=4,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") is None

    def test_returns_the_real_pool_id_for_a_specific_resource_within_a_pool(
        self, db_path,
    ):
        """A specific-resource binding preserves its pool and resource IDs."""
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            resource_id="res-1",
            gpu_count=4,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"


# ---------------------------------------------------------------------------
# open_listing_resource_keys -- only durable registry bindings are authoritative
# ---------------------------------------------------------------------------

class TestOpenListingResourceKeys:
    def test_bound_open_listing_is_covered(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-a", gpu_count=2, model="H100", pool_id="gpu-pool") in covered

    def test_unbound_listing_is_excluded_even_with_one_configured_site(
        self, db_path,
    ):
        """A single configured site never substitutes for durable ownership."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert covered == set()

    def test_unbound_listing_is_excluded_with_multiple_sites(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert covered == set()

    def test_a_bound_listing_is_covered_at_whichever_site_it_names(
        self, db_path,
    ):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-b",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-b", gpu_count=2, model="H100", pool_id="gpu-pool") in covered

    def test_bound_listing_does_not_require_a_derived_row(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-a", gpu_count=2, model="H100", pool_id="gpu-pool") in covered

# ---------------------------------------------------------------------------
# stale_open_listing_ids -- unbound listings are never attributed to a site
# ---------------------------------------------------------------------------

class TestStaleOpenListingIds:
    def test_listing_that_still_fits_is_not_stale(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        assert stale == []

    def test_listing_whose_slice_no_longer_fits_is_stale(self, db_path):
        _seed_pool(db_path, gpu_count=1)  # only 1 GPU available
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        assert stale == ["listing-1"]

    def test_unbound_listing_is_skipped_even_with_one_configured_site(
        self, db_path,
    ):
        _seed_pool(db_path, gpu_count=1)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
        )
        assert stale == []

    def test_unbound_listing_is_skipped_with_multiple_sites(self, db_path):
        """Configured topology never supplies a missing durable binding."""
        _seed_pool(db_path, gpu_count=1)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a", "site-b"), backed_only=False)
        assert stale == []

    def test_listing_bound_to_a_different_site_uses_that_site(self, db_path):
        _seed_pool(db_path, gpu_count=4)
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-b",
        )
        # Only site-a has capacity data seeded.
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        # VM availability is scoped to site-a, so the site-b-bound listing
        # is stale rather than silently reassigned.
        assert stale == ["listing-1"]

    def test_bound_listing_uses_its_site_regardless_of_site_count(
        self, db_path,
    ):
        """Configured site count cannot override the durable site binding."""
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a", "site-b", "site-c", "site-d", "site-e"), backed_only=False)
        assert stale == []


# ---------------------------------------------------------------------------
# closed_available_listing_ids
# ---------------------------------------------------------------------------

class TestClosedAvailableListingIds:
    def test_closed_listing_that_now_fits_is_reopenable(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            status="closed",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        reopenable = closed_available_listing_ids(db_path, home_site="site-a")
        assert reopenable == ["listing-1"]

    def test_empty_when_nothing_is_available(self, db_path):
        assert closed_available_listing_ids(db_path, home_site="site-a") == []


# ---------------------------------------------------------------------------
# reopen_local_derived_listing
# ---------------------------------------------------------------------------

class TestSchema:
    def test_domain_binding_schema_migration_is_idempotent(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            migrate_storefront_domain_bindings_schema(conn)
            migrate_storefront_domain_bindings_schema(conn)
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(storefront_listing_bindings)"
                )
            }
        finally:
            conn.close()
        assert {
            "listing_id",
            "site_id",
            "offering_mode",
            "domain_identity",
            "contract_major",
            "contract_minor",
        } <= columns

    def test_fresh_storefront_database_has_no_legacy_mapping_table(self, tmp_path):
        """The common listing binding is the only VM listing mapping.

        A fresh database never creates ``derived_compute_listings``; only a
        database written before the binding existed still carries it, for the
        storefront-domain migration tool to read.
        """
        from market_storefront.utils.sqlite_client import SQLiteClient

        client = SQLiteClient(
            db_path=str(tmp_path / "sqlite-client.db"),
            registry=_VM_REGISTRY,
        )
        assert client.domain_registry.resolve(_VM_BINDING) is _VM_DOMAIN
        conn = sqlite3.connect(client.db_path)
        try:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='derived_compute_listings'"
            ).fetchone() is None
        finally:
            conn.close()


class TestMemberAvailableUnits:
    def test_none_availability_means_fully_available(self):
        assert _member_available_units(8, ("site-a", "res-1"), None) == 8

    def test_capped_by_the_availability_lookup(self):
        avail = {("site-a", "res-1"): 3}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 3

    def test_capped_by_member_total_even_if_availability_says_more(self):
        avail = {("site-a", "res-1"): 99}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 8

    def test_missing_key_in_availability_means_zero(self):
        avail = {("site-a", "other-res"): 5}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 0

    def test_never_negative(self):
        avail = {("site-a", "res-1"): -5}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 0


# ---------------------------------------------------------------------------
# _accumulate_capacity_pool_member -- local capacity-pools aggregation
# ---------------------------------------------------------------------------

class TestAccumulateCapacityPoolMember:
    def _fresh_pool(self):
        return {
            "total_gpu_count": 0, "available_gpu_count": 0,
            "max_member_available_gpu_count": 0, "single_resource_id": None,
            "member_count": 0,
        }

    def test_first_member_sets_single_resource_id(self):
        pool = self._fresh_pool()
        row = {"gpu_count": 4, "site": None, "resource_id": "res-1"}
        _accumulate_capacity_pool_member(pool, row, None, home_site="site-a")
        assert pool["single_resource_id"] == "res-1"
        assert pool["member_count"] == 1
        assert pool["total_gpu_count"] == 4
        assert pool["available_gpu_count"] == 4

    def test_second_member_clears_single_resource_id(self):
        """A pool with more than one member is fungible, not
        single-resource-keyed -- single_resource_id must become None
        again once a second member is folded in."""
        pool = self._fresh_pool()
        _accumulate_capacity_pool_member(
            pool,
            {"gpu_count": 4, "site": None, "resource_id": "res-1"},
            None,
            home_site="site-a",
        )
        _accumulate_capacity_pool_member(
            pool,
            {"gpu_count": 4, "site": None, "resource_id": "res-2"},
            None,
            home_site="site-a",
        )
        assert pool["single_resource_id"] is None
        assert pool["member_count"] == 2
        assert pool["total_gpu_count"] == 8

    def test_max_member_available_tracks_the_largest_single_member(self):
        pool = self._fresh_pool()
        avail = {("site-a", "res-1"): 2, ("site-a", "res-2"): 6}
        _accumulate_capacity_pool_member(
            pool,
            {"gpu_count": 4, "site": None, "resource_id": "res-1"},
            avail,
            home_site="site-a",
        )
        _accumulate_capacity_pool_member(
            pool,
            {"gpu_count": 8, "site": None, "resource_id": "res-2"},
            avail,
            home_site="site-a",
        )
        assert pool["max_member_available_gpu_count"] == 6
        assert pool["available_gpu_count"] == 8  # sum, not max

    def test_site_tagged_member_uses_its_own_site_in_the_availability_key(self):
        pool = self._fresh_pool()
        avail = {("dc-b", "res-1"): 3}
        _accumulate_capacity_pool_member(
            pool,
            {"gpu_count": 4, "site": "dc-b", "resource_id": "res-1"},
            avail,
            home_site="site-a",
        )
        assert pool["available_gpu_count"] == 3


# ---------------------------------------------------------------------------
# _project_legacy_resource_row -- one legacy `resources` row -> pool_rows entry
# ---------------------------------------------------------------------------

class TestProjectLegacyResourceRow:
    def _row(self, **overrides):
        base = {
            "resource_id": "res-1",
            "attributes": '{"gpu_model": "H100", "region": "us-east", "sla": 99.9}',
            "value": 4,
            "min_price": "10",
            "token": "0xtoken",
            "accepted_escrows": "[]",
            "max_duration_seconds": 3600,
        }
        base.update(overrides)
        return base

    def test_reads_descriptive_attributes(self):
        row = self._project(self._row())
        assert row["gpu_model"] == "H100"
        assert row["region"] == "us-east"
        assert row["sla"] == 99.9

    def test_defaults_pool_id_to_resource_id_when_attributes_lack_it(self):
        row = self._project(self._row())
        assert row["pool_id"] == "res-1"
        assert row["single_resource_id"] == "res-1"

    def test_uses_attributes_pool_id_when_present(self):
        row = self._project(self._row(
            attributes='{"pool_id": "shared-pool", "gpu_model": "H100"}',
        ))
        assert row["pool_id"] == "shared-pool"

    def test_malformed_attributes_json_does_not_raise(self):
        row = self._project(self._row(attributes="not json"))
        assert row["gpu_model"] is None

    def test_missing_optional_columns_become_none(self):
        row = self._project(
            self._row(), has_accepted=False, has_max_duration=False,
        )
        assert row["accepted_escrows"] is None
        assert row["max_duration_seconds"] is None

    def test_availability_caps_total(self):
        row = self._project(
            self._row(value=8),
            member_availability={("site-a", "res-1"): 3},
        )
        assert row["available_gpu_count"] == 3
        assert row["total_gpu_count"] == 8

    def _project(
        self, row, *, has_accepted=True, has_max_duration=True, member_availability=None,
    ):
        return _project_legacy_resource_row(
            row, has_accepted=has_accepted, has_max_duration=has_max_duration,
            member_availability=member_availability,
            home_site="site-a",
        )


# ---------------------------------------------------------------------------
# _projected_resource_usage -- pure per-resource derivation
# ---------------------------------------------------------------------------

class TestProjectedResourceUsage:
    def test_returns_none_without_a_physical_resource_id(self):
        usage = _projected_resource_usage(
            {}, site_id="site-a", member_availability=None,
        )
        assert usage is None

    def test_none_availability_means_fully_available(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8}},
            site_id="site-a", member_availability=None,
        )
        assert usage.total == 8
        assert usage.available == 8

    def test_prefers_the_projections_own_available_field_when_present(self):
        """When the projection row already carries live availability,
        that value is used directly, not the member_availability lookup
        (which is only a fallback for when it's absent)."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 8},
                "available": {"gpu_count": 5},
            },
            site_id="site-a",
            member_availability={("site-a", "res-1"): 1},  # would give a different answer
        )
        assert usage.available == 5

    def test_prefers_the_projections_own_available_field_even_when_member_availability_is_none(self):
        """The projection's own available field must be used even when
        member_availability is None -- it is authoritative live data
        from the projection itself, not conditional on whether a
        *different* fallback source happens to be present."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 8},
                "available": {"gpu_count": 5},
            },
            site_id="site-a",
            member_availability=None,
        )
        assert usage.available == 5

    def test_a_derived_declarations_projection_is_read_as_live_availability(self):
        """A host formerly projected from its host row (no ``available``)
        now projects its declaration, which always reports availability.
        Built through the site's own projection so the row is the one the
        storefront receives: the reported figure is used, not a stale
        member lookup, and a present value is never mistaken for unknown."""
        declared = {
            "resource_id": "kvm1",
            "pool_id": "gpu-pool",
            "resource_type": "compute.gpu",
            "capacity": {"gpu_count": 4},
            "available": {"gpu_count": 3},
            "attributes": {"gpu_model": "H200", "host_id": "kvm1"},
            "enabled": True,
        }
        unreported = {**declared, "resource_id": "kvm2"}
        del unreported["available"]
        (pool,) = resource_pool_projection([declared, unreported])
        by_id = {row["physical_resource_id"]: row for row in pool["resources"]}

        live = _projected_resource_usage(
            by_id["kvm1"],
            site_id="site-a",
            member_availability={("site-a", "kvm1"): 4},
        )
        fallback = _projected_resource_usage(
            by_id["kvm2"],
            site_id="site-a",
            member_availability={("site-a", "kvm2"): 1},
        )

        assert (live.total, live.available) == (4, 3)
        assert "available" not in by_id["kvm2"]
        assert fallback.available == 1

    def test_falls_back_to_member_availability_when_no_available_field(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8}},
            site_id="site-a",
            member_availability={("site-a", "res-1"): 2},
        )
        assert usage.available == 2

    def test_usage_carries_no_gpu_model(self):
        """A listing's model comes from its shape, so a member's usage is
        counts alone; a model on the usage would be a second, unread source."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1},
                "attributes": {"gpu_model": "A100"},
            },
            site_id="site-a", member_availability=None,
        )
        assert not hasattr(usage, "gpu_model")


# ---------------------------------------------------------------------------
# _fungible_availability_from_buckets -- direct contract tests, isolated
# from _projected_pool_rows' pricing/resource-walk scaffolding
# ---------------------------------------------------------------------------

class TestFungibleAvailabilityFromBuckets:
    def test_none_family_falls_back(self):
        assert _fungible_availability_from_buckets("gpu-pool", None) is None

    def test_loaded_empty_family_is_trusted_zero(self):
        assert _fungible_availability_from_buckets("gpu-pool", []) == (0, 0)

    def test_loaded_family_with_no_matching_pool_is_trusted_zero(self):
        buckets = [
            {"resource_pool_id": "other-pool", "available": {"gpu_count": 9}, "resource_count": 2},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (0, 0)

    def test_matching_readable_bucket_is_used(self):
        buckets = [
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 6},
                "resource_count": 2,
                "grouping_attributes": {"gpu_model": "H100"},
            },
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (6, 12)

    def test_max_across_multiple_matching_buckets_not_sum(self):
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 2}, "resource_count": 1},
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 6}, "resource_count": 1},
        ]
        max_available, total_available = _fungible_availability_from_buckets(
            "gpu-pool", buckets,
        )
        assert max_available == 6
        assert total_available == 2 + 6

    def test_matching_but_unreadable_bucket_falls_back(self):
        """A bucket entry exists for this pool but predates per-resource
        `available` (empty dict, no `gpu_count` key) -- not the same as
        a confirmed absence, must fall back rather than read as zero."""
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) is None

    def test_one_readable_and_one_unreadable_matching_bucket_uses_the_readable_one(self):
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 4}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (4, 4)


# ---------------------------------------------------------------------------
# _projected_pool_rows -- one projected pool -> zero or more pool_rows entries
# ---------------------------------------------------------------------------

class TestProjectedPoolRows:
    def _pricing_row(self, **overrides):
        base = {
            "gpu_model": "H100", "region": "us-east", "sla": 99.9,
            "min_price": "10", "token": "0xtoken", "accepted_escrows": "[]",
            "max_duration_seconds": 3600,
        }
        base.update(overrides)
        return base

    def test_empty_without_a_pool_id(self):
        rows = _project_vm_pool_rows({}, site_id="site-a", home_site="site-a",
        local_pricing={}, member_availability=None, capacity_buckets=None,)
        assert rows == []

    def test_pool_without_vm_deliverable_mode_is_excluded(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "pool-1",
                "resources": [],
                "pool_metadata": {
                    "policy_tags": {"deliverable_modes": ["bare_metal"]}
                },
            },
            site_id="site-a",
            home_site="site-a",
            local_pricing={},
            member_availability=None,
            capacity_buckets=None,
        )
        assert rows == []

    def test_non_home_site_pool_with_a_matching_local_pool_id_never_uses_it(self):
        """`compute_capacity_pools` is never consulted for a non-home-site
        pool (cross-site pool_id collision risk -- see `_local_pool_pricing`),
        even when a same-named local row exists -- but the pool still
        publishes, priceless, since a missing storefront-override tier is
        not a reason to suppress the pool entirely."""
        rows = _project_vm_pool_rows({"resource_pool_id": "gpu-pool", "resources": [
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1}, "attributes": {"gpu_model": "H100"},
                "enabled": True,
            },
        ]},
        site_id="site-b", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert _term(rows[0], "min_price") is None
        assert rows[0]["region"] is None

    def test_non_home_site_pool_publishes_from_a_complete_hint_alone(self):
        """The actual point of the three-tier mechanism: a pool this
        storefront has never locally priced still publishes with real
        commercial terms, sourced entirely from its own projected hint."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {
                    "region": "Nevada, US",
                    "pricing": {
                        "gpu": {
                            "H100": {
                                "min_price": "5.00", "token": "0xhint",
                                "max_duration_seconds": 3600,
                            },
                        },
                    },
                },
            },
        },
        site_id="site-b", home_site="site-a",
        local_pricing={}, member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["region"] == "Nevada, US"
        assert _term(rows[0], "min_price") == "5.00"
        assert _term(rows[0], "token") == "0xhint"

    def test_home_site_pool_with_no_local_row_publishes_priceless_by_default(self):
        rows = _project_vm_pool_rows({"resource_pool_id": "unpriced", "resources": [
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1}, "attributes": {"gpu_model": "H100"},
                "enabled": True,
            },
        ]},
        site_id="site-a", home_site="site-a",
        local_pricing={}, member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert _term(rows[0], "min_price") is None
        assert rows[0]["region"] is None
        assert rows[0]["sla"] == 0.0

    def test_home_site_pool_with_no_local_row_publishes_from_config_default(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "unpriced",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={}, member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_defaults_by_model={
                "A100": GpuPricingFields(min_price="3.00"),
            },
        ),)
        assert len(rows) == 1
        assert _term(rows[0], "min_price") == "3.00"

    def test_home_site_pool_with_local_row_still_uses_it_as_the_override(self):
        """The corrected behavior doesn't disturb the ordinary case: a
        real local row still wins as the top-precedence override."""
        rows = _project_vm_pool_rows({"resource_pool_id": "gpu-pool", "resources": [
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1}, "attributes": {"gpu_model": "H100"},
                "enabled": True,
            },
        ]},
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price="10")},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert _term(rows[0], "min_price") == "10"

    def test_builds_one_fungible_row_for_home_site_pool_with_pricing(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            # Explicit tag: a single-member pool's *structural*
            # default is specific_resource (backward compatibility,
            # see test_single_member_pool_defaults_to_specific_resource_without_a_tag
            # below) -- an explicit fungible tag is what this test
            # actually wants to exercise.
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        row = rows[0]
        assert row["pool_id"] == "gpu-pool"
        assert row["site_id"] == "site-a"
        assert row["total_gpu_count"] == 4
        assert _term(row, "min_price") == "10"
        assert row["listing_cardinality_mode"] == "fungible"
        assert row["listing_cardinality_mode_explanation"] is None
        assert row["single_resource_id"] is None

    def test_single_member_pool_defaults_to_specific_resource_without_a_tag(self):
        """Backward compatibility: `available_compute_slices` always
        treated a single-member pool as specific-resource before
        the cardinality tag existed (`member_count == 1` heuristic). An
        untagged pool with exactly one member must keep resolving that
        way, or an existing derived-listing mapping keyed on that
        resource's identity would silently break the moment a
        projection without `pool_metadata` reaches this function."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"
        assert rows[0]["single_resource_id"] == "res-1"

    def test_multi_member_pool_defaults_to_fungible_without_a_tag(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "fungible"
        assert rows[0]["single_resource_id"] is None

    def test_disabled_resources_are_excluded(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": False,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["total_gpu_count"] == 0
        assert rows[0]["member_count"] == 0

    def test_the_listing_model_is_the_members_never_the_legacy_rows(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(gpu_model="H100")},
        member_availability=None, capacity_buckets=None,)
        assert {shape.gpu_model for shape in rows[0]["listing_shapes"]} == {"A100"}
        assert set(rows[0]["pricing_by_model"]) == {"A100"}

    def test_a_member_without_a_model_takes_none_from_the_legacy_row(self):
        """A shape names a model only from a declaration; the legacy row's
        model would advertise hardware no member declares."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(gpu_model="H100")},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["listing_shapes"] == ()
        assert rows[0]["pricing_by_model"] == {}

    # -- region/sla hint resolution ---------------------------------------

    def test_region_hint_overrides_local_pricing_fallback(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"region": "Nevada, US"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(region="us-east")},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["region"] == "Nevada, US"

    def test_region_falls_back_to_local_pricing_without_a_hint(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(region="us-east")},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["region"] == "us-east"

    def test_sla_storefront_override_wins_over_pool_hint_by_default(self):
        """No hint_resolution passed -- the default settings apply, and
        the local pricing row's sla acts as the storefront's per-pool
        override, taking precedence over any pool-declared hint
        regardless of the (default-closed) trust gate."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 50.0}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(sla=99.9)},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["sla"] == 99.9

    def test_sla_pool_hint_used_when_no_local_override_and_gate_open(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 95.0}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(sla=None)},
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=0.0,
        ),)
        assert rows[0]["sla"] == 95.0

    def test_sla_pool_hint_ignored_when_gate_closed_even_with_no_override(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 95.0}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(sla=None)},
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=False, default_sla=12.5,
        ),)
        assert rows[0]["sla"] == 12.5

    def test_sla_falls_back_to_config_default_with_no_override_or_hint(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(sla=None)},
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=42.0,
        ),)
        assert rows[0]["sla"] == 42.0

    # -- pricing hint resolution ------------------------------------------

    def test_pricing_storefront_override_wins_over_pool_hint(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price="10")},
        member_availability=None, capacity_buckets=None,)
        assert _term(rows[0], "min_price") == "10"

    def test_pricing_pool_hint_used_when_no_storefront_override(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
        member_availability=None, capacity_buckets=None,)
        assert _term(rows[0], "min_price") == "5.00"

    def test_pricing_falls_back_to_per_model_config_default(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_defaults_by_model={
                "H100": GpuPricingFields(min_price="3.00"),
            },
        ),)
        assert _term(rows[0], "min_price") == "3.00"

    def test_pricing_falls_back_to_flat_config_default_as_last_resort(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_flat_default=GpuPricingFields(min_price="1.00"),
        ),)
        assert _term(rows[0], "min_price") == "1.00"

    def test_specific_resource_multi_member_prices_each_by_its_own_model(self):
        """Two members with different GPU models must resolve pricing
        independently -- proving pricing resolution is per-row, not
        computed once for the whole pool."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "A100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {
                    "listing_cardinality_mode": "specific_resource",
                    "pricing": {
                        "gpu": {
                            "H100": {"min_price": "5.00"},
                            "A100": {"min_price": "3.00"},
                        },
                    },
                },
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
        member_availability=None, capacity_buckets=None,)
        # Every row carries each model's terms; a listing takes its shape's.
        pricing = rows[0]["pricing_by_model"]
        assert (pricing["H100"].min_price, pricing["A100"].min_price) == ("5.00", "3.00")

    # -- listing_cardinality_mode resolution --------------------------------------

    def test_unrecognized_cardinality_mode_falls_back_with_explanation(self):
        """One member -> structural default is specific_resource (see
        test_single_member_pool_defaults_to_specific_resource_without_a_tag)
        -- an unrecognized explicit value falls back to *that* default,
        not a hardcoded constant."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"
        assert rows[0]["listing_cardinality_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_cardinality_mode_explanation"]

    def test_unrecognized_cardinality_mode_falls_back_to_fungible_for_multi_member(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
                {"physical_resource_id": "res-2", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "fungible"
        assert rows[0]["listing_cardinality_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_cardinality_mode_explanation"]

    # -- specific_resource, including multi-member ----------------------

    def test_specific_resource_single_member_yields_one_resource_keyed_row(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"

    def test_specific_resource_multi_member_yields_one_row_per_member(self):
        """A multi-member pool declared specific_resource must publish
        one independently identified row per member, not collapse to a
        single aggregate the way fungible mode does."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 6},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-3", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 0},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 3
        by_resource = {row["single_resource_id"]: row for row in rows}
        assert set(by_resource) == {"res-1", "res-2", "res-3"}
        assert by_resource["res-1"]["available_gpu_count"] == 8
        assert by_resource["res-2"]["available_gpu_count"] == 6
        assert by_resource["res-3"]["available_gpu_count"] == 0
        # Each row's own availability, not summed/maxed across the pool.
        assert by_resource["res-1"]["max_member_available_gpu_count"] == 8
        assert by_resource["res-2"]["max_member_available_gpu_count"] == 6

    def test_specific_resource_disabled_member_excluded(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": False,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"

    # -- fungible mode sourced from site_capacity_buckets ----------------

    def test_fungible_prefers_bucket_availability_over_resource_walk(self):
        """The max_member_available ceiling must reflect a single bucket's
        (i.e. a single member's) availability, not a sum across buckets,
        and must come from the bucket data when it's usable."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None,
        capacity_buckets=[
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 2},
                "resource_count": 1,
                "grouping_attributes": {"gpu_model": "H100"},
            },
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 6},
                "resource_count": 1,
                "grouping_attributes": {"gpu_model": "H100"},
            },
        ],)
        assert len(rows) == 1
        row = rows[0]
        assert row["max_member_available_gpu_count"] == 6
        assert row["available_gpu_count"] == 2 * 1 + 6 * 1

    def test_fungible_trusts_zero_when_family_loaded_with_no_matching_entries(self):
        """Corrected behavior: a *loaded* capacity-bucket family (however
        many entries it has) that contains no entry for this specific
        pool is itself the authoritative answer -- zero -- not missing
        data. `capacity_bucket_projection` covers the site's complete
        enabled-resource inventory, so a pool with any enabled member
        would necessarily contribute at least one matching entry once
        the family has loaded; absence means the pool currently has none.
        Falling back to a separately-fetched resource-pool projection
        here would let two independently-polled projection generations
        silently contradict each other."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None,
        capacity_buckets=[
            {
                "resource_pool_id": "other-pool",
                "available": {"gpu_count": 99},
                "resource_count": 5,
            },
        ],)
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_trusts_zero_when_family_loaded_as_a_whole_empty_list(self):
        """The site-wide "authoritative zero buckets anywhere" case --
        e.g. the capacity-bucket family loaded successfully but the site
        currently has no enabled resources at all. Must be trusted the
        same way a per-pool absence is, not treated as unknown."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None,
        capacity_buckets=[],)
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_falls_back_to_resource_walk_when_no_bucket_data(self):
        """No site_capacity_buckets supplied at all (None) -- must not
        publish zero capacity, must use the pre-existing computation."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 3},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["max_member_available_gpu_count"] == 3

    def test_fungible_falls_back_when_bucket_predates_available_field(self):
        """A bucket whose `available` dict lacks `gpu_count` entirely
        (an older producer that never emitted per-resource availability)
        must not be read as an authoritative zero -- falls back to the
        resource-list computation instead."""
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None,
        capacity_buckets=[
            {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
        ],)
        assert rows[0]["max_member_available_gpu_count"] == 4

    def test_fungible_trusts_a_genuine_zero_from_buckets(self):
        rows = _project_vm_pool_rows({
            "resource_pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a", home_site="site-a",
        local_pricing={"gpu-pool": self._pricing_row()},
        member_availability=None,
        capacity_buckets=[
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 0},
                "resource_count": 1,
            },
        ],)
        # A real zero from a usable bucket is trusted, even though the
        # resource-list walk (never consulted for max/available once a
        # usable bucket exists) would have said 4.
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0



# ---------------------------------------------------------------------------
# Unbacked supply, held sources, and withdrawn listings
# ---------------------------------------------------------------------------

_BACKED = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}
_UNBACKED = {
    "deliverable_modes": [],
    "advertisable_modes": ["vm"],
    "capacity_backing": "unbacked",
}


def _declared_pool(
    pool_id: str,
    members: list[tuple[str, object, int]],
    *,
    tags: dict,
    enabled: bool = True,
    cardinality: str = "fungible",
) -> dict:
    """One projected pool; each member is (resource_id, gpu_count, available)."""
    return {
        "resource_pool_id": pool_id,
        "pool_metadata": {
            "enabled": enabled,
            "policy_tags": {
                **tags,
                "listing_cardinality_mode": cardinality,
                "region": "us-east",
            },
        },
        "resources": [
            {
                "physical_resource_id": resource_id, "resource_type": "compute.gpu",
                "enabled": True,
                "capacity": {} if count is None else {"gpu_count": count},
                "available": {"gpu_count": available},
                # Claims match region against the declaration itself, so a
                # reservable member declares the region its pool advertises.
                "attributes": {"gpu_model": "H100", "region": "us-east"},
            }
            for resource_id, count, available in members
        ],
    }


def _slices(db_path, pools, *, holds=None):
    return available_compute_slices(
        db_path,
        home_site="site-a",
        site_pool_projection={"site-a": pools},
        holds=holds,
    )


class TestUnbackedDerivation:
    def test_unbacked_pool_ranges_over_declared_not_available_quantity(self, db_path):
        pool = _declared_pool("broker-a", [("res-1", 8, 0)], tags=_UNBACKED)

        counts = sorted(s["gpu_count"] for s in _slices(db_path, [pool]))

        assert counts == list(range(1, 9))
        assert {s["capacity_backing"] for s in _slices(db_path, [pool])} == {
            "unbacked"
        }

    def test_backed_pool_ranges_over_available_quantity(self, db_path):
        pool = _declared_pool("pool-b", [("res-1", 8, 2)], tags=_BACKED)

        assert sorted(s["gpu_count"] for s in _slices(db_path, [pool])) == [1, 2]

    def test_unbacked_fungible_range_is_one_members_declared_count(self, db_path):
        pool = _declared_pool(
            "broker-a", [("res-1", 8, 0), ("res-2", 4, 0)], tags=_UNBACKED
        )

        assert max(s["gpu_count"] for s in _slices(db_path, [pool])) == 8

    def test_a_pool_that_does_not_advertise_vm_yields_nothing(self, db_path):
        pool = _declared_pool(
            "broker-a",
            [("res-1", 8, 8)],
            tags={**_UNBACKED, "advertisable_modes": ["bare_metal"]},
        )

        assert _slices(db_path, [pool]) == []

    def test_a_disabled_pool_yields_nothing(self, db_path):
        pool = _declared_pool("broker-a", [("res-1", 8, 8)], tags=_UNBACKED, enabled=False)

        assert _slices(db_path, [pool]) == []


class TestEnumerationQuantity:
    def test_absent_count_yields_nothing_and_is_reported(self, db_path):
        from domains.vms.listings.reconciler import derivation_reports

        pool = _declared_pool("broker-a", [("res-1", None, 0)], tags=_UNBACKED)

        assert _slices(db_path, [pool]) == []
        assert derivation_reports()["site-a"]["members_without_gpu_count"] == {
            "res-1": "broker-a"
        }

    def test_declared_zero_yields_nothing_silently(self, db_path):
        from domains.vms.listings.reconciler import derivation_reports

        pool = _declared_pool("broker-a", [("res-1", 0, 0)], tags=_UNBACKED)

        assert _slices(db_path, [pool]) == []
        assert derivation_reports()["site-a"]["members_without_gpu_count"] == {}

    def test_malformed_count_holds_a_whole_fungible_pool(self, db_path):
        pool = _declared_pool(
            "broker-a", [("res-1", 8, 8), ("res-2", "eight", 0)], tags=_UNBACKED
        )
        holds: set = set()

        assert _slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "broker-a") in holds

    def test_malformed_count_holds_only_its_member_in_a_specific_pool(self, db_path):
        pool = _declared_pool(
            "broker-a",
            [("res-1", 2, 2), ("res-2", "two", 0)],
            tags=_UNBACKED,
            cardinality="specific_resource",
        )
        holds: set = set()

        slices = _slices(db_path, [pool], holds=holds)

        assert {s["resource_id"] for s in slices} == {"res-1"}
        assert holds == {("resource", "site-a", "res-2")}

    def test_key_builders_never_substitute_a_count(self):
        for bad in (None, 0, "1", True):
            with pytest.raises(ValueError):
                listing_pool_key("site-a", "pool-a", bad)


class TestHeldAndWithdrawnListings:
    def test_listings_of_an_unresolvable_pool_are_held_not_closed(self, db_path):
        _seed_listing(db_path, listing_id="held-1", pool_id="broker-a", site_id="site-a")
        declared = _declared_pool("other", [("res-9", 8, 8)], tags=_UNBACKED)
        undeclared = _declared_pool("broker-a", [("res-1", 8, 8)], tags={})

        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
            site_pool_projection={"site-a": [declared, undeclared]},
        )

        assert "held-1" not in stale

    def test_a_disabled_pools_listings_are_stale(self, db_path):
        _seed_listing(db_path, listing_id="gone-1", pool_id="broker-a", site_id="site-a")
        pool = _declared_pool("broker-a", [("res-1", 8, 8)], tags=_BACKED, enabled=False)

        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
            site_pool_projection={"site-a": [pool]},
        )

        assert stale == ["gone-1"]

    def test_a_seller_closed_listing_is_never_offered_for_reopen(self, db_path):
        _seed_listing(
            db_path,
            listing_id="withdrawn",
            status="closed",
            closed_by="seller",
            pool_id="pool-b",
            site_id="site-a",
        )
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert (
            closed_available_listing_ids(
                db_path,
                home_site="site-a",
                site_pool_projection={"site-a": [pool]},
            )
            == []
        )

    def test_a_reconciliation_closed_listing_reopens_when_its_slice_returns(
        self, db_path
    ):
        _seed_listing(
            db_path,
            listing_id="returns",
            status="closed",
            pool_id="pool-b",
            site_id="site-a",
        )
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert closed_available_listing_ids(
            db_path,
            home_site="site-a",
            site_pool_projection={"site-a": [pool]},
        ) == ["returns"]

    def test_a_listing_whose_published_model_diverged_is_not_reopened(self, db_path):
        _seed_listing(
            db_path,
            listing_id="diverged",
            status="closed",
            pool_id="pool-b",
            site_id="site-a",
        )
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE listings SET listing_resource = ? WHERE listing_id = ?",
                (
                    json.dumps(
                        {
                            "offering_mode": "vm",
                            "gpu_count": 2,
                            "pool_id": "pool-b",
                            "gpu_model": "A100",
                        }
                    ),
                    "diverged",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert (
            closed_available_listing_ids(
                db_path,
                home_site="site-a",
                site_pool_projection={"site-a": [pool]},
            )
            == []
        )

    def test_a_stored_key_comes_from_the_binding_not_the_published_fields(self, db_path):
        _seed_listing(db_path, listing_id="countless", pool_id="pool-b", site_id="site-a")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE listings SET listing_resource = ? WHERE listing_id = ?",
                (json.dumps({"offering_mode": "vm", "pool_id": "pool-b"}), "countless"),
            )
            conn.commit()
        finally:
            conn.close()

        # Flattening need not be invertible, so a key is never rebuilt from what
        # the listing publishes.
        assert open_listing_resource_keys(
            db_path, home_site="site-a"
        ) == {_gpu_key("site-a", gpu_count=2, model="H100", pool_id="pool-b")}

    def test_a_listing_bound_before_shapes_keeps_a_key_no_derivation_produces(
        self, db_path
    ):
        _seed_listing(
            db_path, listing_id="v1", pool_id="pool-b", site_id="site-a", schema_version=1
        )

        assert open_listing_resource_keys(
            db_path, home_site="site-a"
        ) == {listing_pool_key("site-a", "pool-b", 2)}


def test_structural_keys_are_byte_identical_to_stored_keys():
    # Stored listings are found by these exact strings; the shared encoding must
    # reproduce them byte for byte, including for delimiter-bearing identifiers.
    assert listing_pool_key("site-a", "b:c", 2) == "pool:6:site-a:3:b:c:gpus:2"
    assert listing_resource_key("s", "r:1", 1) == "1:s:3:r:1:gpus:1"


# ---------------------------------------------------------------------------
# Listing shapes: sources, feasibility, identity, and reporting
# ---------------------------------------------------------------------------


def _member(
    resource_id: str,
    *,
    capacity: dict,
    available: dict | None = None,
    attributes: dict | None = None,
    resource_type: str | None = "compute.gpu",
) -> dict:
    member = {
        "physical_resource_id": resource_id,
        "enabled": True,
        "capacity": capacity,
        "attributes": {"gpu_model": "H100", "region": "us-east", **(attributes or {})},
    }
    if resource_type is not None:
        member["resource_type"] = resource_type
    if available is not None:
        member["available"] = available
    return member


def _shaped_pool(
    pool_id: str,
    members: list[dict],
    *,
    tags: dict = _BACKED,
    shapes: list | None = None,
    cardinality: str = "fungible",
    region: str = "us-east",
) -> dict:
    policy_tags = {**tags, "listing_cardinality_mode": cardinality, "region": region}
    if shapes is not None:
        policy_tags["listing_shapes"] = {"vm": shapes}
    return {
        "resource_pool_id": pool_id,
        "pool_metadata": {"enabled": True, "policy_tags": policy_tags},
        "resources": members,
    }


def _shape_slices(db_path, pools, *, buckets=None, holds=None):
    return available_compute_slices(
        db_path,
        home_site="site-a",
        site_pool_projection={"site-a": pools},
        site_capacity_buckets=None if buckets is None else {"site-a": buckets},
        holds=holds,
    )


def _site_report() -> dict:
    from domains.vms.listings.reconciler import derivation_reports

    return derivation_reports()["site-a"]


_BIG = {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 2000}
_SMALL_SHAPE = {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
                "memory": {"gib": 64}, "storage": {"gib": 100}}


class TestListingShapes:
    def test_a_pool_hint_publishes_its_shapes_and_no_default_shapes(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG)],
            shapes=[_SMALL_SHAPE, {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}],
        )

        slices = _shape_slices(db_path, [pool])

        assert len(slices) == 2
        by_count = {row["gpu_count"]: row for row in slices}
        assert (by_count[1]["vcpu_count"], by_count[1]["ram_gb"], by_count[1]["disk_gb"]) == (8, 64, 100)
        # A dimension the shape omits is neither published nor claimed.
        assert "vcpu_count" not in by_count[2] and "disk_gb" not in by_count[2]
        assert by_count[2]["ram_gb"] == 128
        assert {row["shape_source"] for row in slices} == {"pool_hint"}

    def test_a_specific_resource_pool_publishes_per_member_per_feasible_shape(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("big", capacity=_BIG), _member("small", capacity={**_BIG, "ram_gb": 128})],
            shapes=[{"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 256}}],
            cardinality="specific_resource",
        )

        assert [row["resource_id"] for row in _shape_slices(db_path, [pool])] == ["big"]

    def test_default_shapes_reproduce_gpu_only_listings(self, db_path):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)])

        slices = _shape_slices(db_path, [pool])

        assert sorted(row["gpu_count"] for row in slices) == list(range(1, 9))
        for row in slices:
            assert row["listing_shape"] == {"gpu": {"count": row["gpu_count"], "model": "H100"}}
            assert not {"vcpu_count", "ram_gb", "disk_gb"} & set(row)
            assert (row["pool_id"], row["gpu_model"], row["region"]) == ("gpu", "H100", "us-east")

    def test_a_mixed_model_pool_publishes_per_model(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [
                _member("h", capacity={"gpu_count": 2}),
                _member("a", capacity={"gpu_count": 1}, attributes={"gpu_model": "A100"}),
            ],
        )

        published = sorted((row["gpu_model"], row["gpu_count"]) for row in _shape_slices(db_path, [pool]))

        assert published == [("A100", 1), ("H100", 1), ("H100", 2)]

    def test_backed_memory_being_taken_makes_a_stated_shape_unpublishable(self, db_path):
        free = _member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 512})
        taken = _member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 32})

        assert _shape_slices(db_path, [_shaped_pool("gpu", [free], shapes=[_SMALL_SHAPE])])
        assert _shape_slices(db_path, [_shaped_pool("gpu", [taken], shapes=[_SMALL_SHAPE])]) == []

    def test_loaded_buckets_decide_availability_for_every_dimension(self, db_path):
        # The member's own availability says memory is taken, but a loaded bucket
        # family is authoritative for a fungible pool.
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 0})],
            shapes=[_SMALL_SHAPE],
        )
        bucket = {
            "resource_pool_id": "gpu",
            "resource_type": "compute.gpu",
            "resource_subtype": None,
            "available": {**_BIG, "ram_gb": 128},
            "grouping_attributes": {"gpu_model": "H100", "region": "us-east"},
            "resource_count": 1,
        }

        assert len(_shape_slices(db_path, [pool], buckets=[bucket])) == 1
        low = {**bucket, "available": {**_BIG, "ram_gb": 32}}
        assert _shape_slices(db_path, [pool], buckets=[low]) == []
        # A loaded family naming no entry for the pool means nothing is free.
        assert _shape_slices(db_path, [pool], buckets=[]) == []

    def test_unknown_availability_is_judged_on_declared_capacity(self, db_path):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        assert len(_shape_slices(db_path, [pool])) == 1

    def test_an_infeasible_stated_shape_is_reported_with_no_fallback(self, db_path):
        too_big = {"gpu": {"count": 16, "model": "H100"}}
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[too_big])

        assert _shape_slices(db_path, [pool]) == []
        (finding,) = _site_report()["infeasible_shapes"]["gpu"]
        assert finding["shape"] == too_big
        assert finding["not_feasible_against"] == "declared"
        assert finding["shape_digest"] == resolve_shape(too_big).digest

    def test_an_unreadable_hint_holds_the_pool_with_no_fallback(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG)], shapes=[{"tpu": {"count": 1}}]
        )
        holds: set = set()

        assert _shape_slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "gpu") in holds
        assert _site_report()["unreadable_shapes"]["gpu"]

    def test_editing_a_shape_changes_its_key(self, db_path):
        def key(gib):
            pool = _shaped_pool(
                "gpu", [_member("m1", capacity=_BIG)],
                shapes=[{"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": gib}}],
            )
            (row,) = _shape_slices(db_path, [pool])
            return row["resource_key"]

        assert key(64) != key(96)

    def test_stating_a_default_shape_keeps_its_key(self, db_path):
        members = [_member("m1", capacity={"gpu_count": 1})]
        (default,) = _shape_slices(db_path, [_shaped_pool("gpu", members)])
        (stated,) = _shape_slices(
            db_path,
            [_shaped_pool("gpu", members, shapes=[{"gpu": {"model": "H100", "count": 1}}])],
        )

        assert default["resource_key"] == stated["resource_key"]
        assert default["shape_source"] == "default" and stated["shape_source"] == "pool_hint"

    def test_a_region_only_in_the_pool_hint_publishes_nothing_and_is_reported(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 2}, attributes={"region": None})],
            region="us-west",
        )

        assert _shape_slices(db_path, [pool]) == []
        assert _site_report()["undeclared_attributes"] == {
            "gpu": {"attribute": "region", "value": "us-west"}
        }

    def test_a_default_shape_unavailable_only_on_load_is_not_reported(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity={"gpu_count": 2}, available={"gpu_count": 0})]
        )

        assert _shape_slices(db_path, [pool]) == []
        report = _site_report()
        assert report["undeclared_attributes"] == {} and report["infeasible_shapes"] == {}

    def test_a_member_without_resource_type_holds_a_fungible_pool(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 2}),
             _member("m2", capacity={"gpu_count": 2}, resource_type=None)],
        )
        holds: set = set()

        assert _shape_slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "gpu") in holds
        assert _site_report()["members_without_resource_type"] == {"m2": "gpu"}

    def test_a_member_without_resource_type_holds_only_itself_in_a_specific_pool(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 1}),
             _member("m2", capacity={"gpu_count": 1}, resource_type=None)],
            cardinality="specific_resource",
        )
        holds: set = set()

        assert [row["resource_id"] for row in _shape_slices(db_path, [pool], holds=holds)] == ["m1"]
        assert holds == {("resource", "site-a", "m2")}


_TWO_GPU_SHAPE = {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}


def _override_rows(pool, *, override=None, local_pricing=None, site_id="site-a", **kwargs):
    """One pool's rows with ``override`` as its site-scoped override, and the
    site report the pass recorded into."""
    report = _SiteDerivationReport()
    holds: set = set()
    rows = _projected_pool_rows(
        pool,
        site_id=site_id,
        home_site="site-a",
        local_pricing=local_pricing or {},
        member_availability=None,
        capacity_buckets=None,
        override=override,
        report=report,
        holds=holds,
        **kwargs,
    )
    return rows, report, holds


def _digests(shapes) -> set[str]:
    return {shape.digest for shape in shapes}


class TestStorefrontOverrideTier:
    """The site-scoped override is the first shape and term tier."""

    def test_an_override_replaces_the_pool_hint_whole(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE, _TWO_GPU_SHAPE])

        (row,), _, _ = _override_rows(pool, override={"listing_shapes": [_TWO_GPU_SHAPE]})

        assert row["shape_source"] == "storefront_override"
        assert [shape.shape for shape in row["listing_shapes"]] == [_TWO_GPU_SHAPE]

    def test_an_override_stating_the_hints_shape_keeps_its_key(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        (hinted,), _, _ = _override_rows(pool)
        (overridden,), _, _ = _override_rows(pool, override={"listing_shapes": [_SMALL_SHAPE]})

        # Keys depend only on the shape digest, not on the tier that stated it.
        assert _digests(overridden["feasible_shapes"]) == _digests(hinted["feasible_shapes"])

    def test_an_override_without_shapes_leaves_the_hint_in_place(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        (row,), _, _ = _override_rows(pool, override={"sla": 99.0})

        assert row["shape_source"] == "pool_hint"

    def test_an_unreadable_stored_override_holds_the_pool_and_is_reported(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        rows, report, holds = _override_rows(
            pool, override={"listing_shapes": [{"gpu": {"count": 1, "model": "H100"}, "fpga": {}}]}
        )

        assert rows == []
        assert ("pool", "site-a", "gpu") in holds
        (problem,) = report.unreadable_shapes["gpu"]
        assert problem.startswith("storefront_override: ")

    def test_commercial_fields_merge_over_the_legacy_row_field_by_field(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity={"gpu_count": 1})])
        legacy = {
            "gpu": {
                "gpu_model": "H100", "region": None, "sla": 90.0, "min_price": "10",
                "token": "0xlegacy", "accepted_escrows": None, "settlements": None,
                "max_duration_seconds": 3600,
            }
        }

        (row,), report, _ = _override_rows(
            pool, override={"min_price": "7", "sla": 99.5}, local_pricing=legacy,
            hint_resolution=PoolHintResolutionSettings(),
        )

        terms = row["pricing_by_model"]["H100"]
        assert (terms.min_price, terms.token, terms.max_duration_seconds) == ("7", "0xlegacy", 3600)
        assert row["sla"] == 99.5
        assert report.legacy_overrides_in_effect == {"gpu": ["max_duration_seconds", "token"]}

    def test_the_legacy_report_names_region_and_accepted_escrows(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity={"gpu_count": 1})])
        del pool["pool_metadata"]["policy_tags"]["region"]
        legacy = {
            "gpu": {
                "gpu_model": "H100", "region": "us-east", "sla": None, "min_price": None,
                "token": None, "accepted_escrows": "[]", "settlements": None,
                "max_duration_seconds": None,
            }
        }

        (row,), report, _ = _override_rows(pool, local_pricing=legacy)

        assert row["region"] == "us-east"
        assert report.legacy_overrides_in_effect == {"gpu": ["accepted_escrows", "region"]}

    def test_a_region_hint_leaves_the_legacy_region_unreported(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity={"gpu_count": 1})])
        legacy = {"gpu": {"gpu_model": None, "region": "elsewhere", "sla": None,
                          "min_price": None, "token": None, "accepted_escrows": None,
                          "settlements": None, "max_duration_seconds": None}}

        (row,), report, _ = _override_rows(pool, local_pricing=legacy)

        assert row["region"] == "us-east"
        assert report.legacy_overrides_in_effect == {}

    def test_an_override_at_a_non_home_site_applies(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)])

        (row,), report, _ = _override_rows(
            pool,
            site_id="site-b",
            override={"listing_shapes": [_SMALL_SHAPE], "min_price": "4"},
            # The same-named home-site legacy row must not reach another site.
            local_pricing={"gpu": {"gpu_model": None, "region": None, "sla": None,
                                   "min_price": "10", "token": None, "accepted_escrows": None,
                                   "settlements": None, "max_duration_seconds": None}},
        )

        assert [shape.shape for shape in row["listing_shapes"]] == [_SMALL_SHAPE]
        assert row["pricing_by_model"]["H100"].min_price == "4"
        assert report.legacy_overrides_in_effect == {}

