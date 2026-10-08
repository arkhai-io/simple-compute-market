"""Shared cases for the VM reconciler's unit and integration tests.

Helpers, constants, and the minimal SQLite schema fixture both levels use.
The database-backed derivation tests live in
``tests/integration/test_reconciler_derivation.py``; pure transformation
tests in ``tests/unit/test_reconciler.py``.
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
from arkhai_vms_listings.pricing_resolution import GpuPricingFields
from arkhai_vms_listings.reconciler import (
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
    vm_override_view,
)
from arkhai_vms_listings.listing_shapes import resolve_shape
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


def _keyed(function):
    """A key reader as these cases call it: judged, and under no configured
    admissibility default unless a test states one."""
    judged = _judged(function)

    def call(*args, **kwargs):
        kwargs.setdefault("admissibility_default", None)
        return judged(*args, **kwargs)

    return call


closed_available_listing_ids = _keyed(_closed_available_listing_ids)


current_available_resource_keys = _keyed(_current_available_resource_keys)


stale_open_listing_ids = _keyed(_stale_open_listing_ids)


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


def _projected_pool_rows(pool, **kwargs):
    """Call the row builder the way a projection pass does for one pool.

    The declaration is read from the pool's own projected tags under the same
    per-site rule, so a test pool carrying no declarations reads under the
    compatibility rule exactly as a lone pool from an older producer would.
    """
    from market_resource_pools import ResolvedPool, read_site_declarations

    pool_id = str(pool.get("pool_id") or "").strip()
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
        "pool_id": pool_id,
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
        "pool_id": pool_id,
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
    from arkhai_vms_listings.reconciler import derivation_reports

    return derivation_reports()["site-a"]


_BIG = {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 2000}


_SMALL_SHAPE = {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
                "memory": {"gib": 64}, "storage": {"gib": 100}}


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


_TOKEN = "0x" + "11" * 20


def _rate(rate: str, asset: str = _TOKEN) -> list[dict[str, str]]:
    return [{"asset": asset, "rate": rate, "per": "hour"}]
