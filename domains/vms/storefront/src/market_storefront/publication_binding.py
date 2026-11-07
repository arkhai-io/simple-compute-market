"""VM publication provenance persisted through the common storefront binding."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
    canonical_source_envelope,
)
from market_resource_pools_contracts.backing import (
    UnknownCapacityBackingError,
    capacity_backing,
)

from arkhai_vms_listings.listing_shapes import resolve_shape
from arkhai_vms_listings.reconciler import (
    LISTING_SOURCE_KIND,
    LISTING_SOURCE_SCHEMA_VERSION,
)

from .domain_runtime import build_vm_storefront_registry
from .utils.sqlite_client import SQLiteClient


def vm_candidate_derivation_key(candidate: dict[str, Any]) -> str:
    """The derivation key the listing a VM candidate derives is bound under."""
    site_id, binding, source = _derivation_source(candidate)
    return build_storefront_derivation_key(
        site_id=site_id,
        binding=binding,
        offering_mode=binding.offering_mode,
        source_identity=source,
    )


def _derivation_source(candidate: dict[str, Any]) -> tuple[str, Any, dict[str, Any]]:
    """A VM candidate's site, domain binding, and derivation source, validated."""
    site_id = candidate.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("VM publication candidate requires an exact trusted site_id")
    pool_id = candidate.get("pool_id")
    resource_id = candidate.get("resource_id")
    if pool_id is None and resource_id is None:
        raise ValueError("VM publication candidate requires pool or resource provenance")
    # Every derivation path produces a shape; a candidate without a valid one
    # is a programming error, not a default shape to be assumed.
    listing_shape = resolve_shape(candidate.get("listing_shape")).shape
    registration = build_vm_storefront_registry().resolve_mode("vm")
    # The derivation identity includes the canonical shape, whichever source
    # produced it, so identity depends only on what is offered.
    source = {
        "kind": LISTING_SOURCE_KIND,
        "schema_version": LISTING_SOURCE_SCHEMA_VERSION,
        "payload": {
            "site_id": site_id,
            "pool_id": str(pool_id) if pool_id is not None else None,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "listing_shape": {family: dict(fields) for family, fields in listing_shape.items()},
        },
    }
    return site_id, registration.binding, source


def prepare_vm_listing_binding(
    *,
    listing_id: str,
    candidate: dict[str, Any],
) -> StorefrontListingBinding:
    """Validate one VM candidate and return its immutable public-safe binding."""

    site_id, binding, source = _derivation_source(candidate)
    try:
        backing = capacity_backing(candidate.get("capacity_backing"))
    except UnknownCapacityBackingError as exc:
        raise ValueError(
            f"VM publication candidate requires an explicit capacity_backing: {exc}"
        ) from exc
    pool_id = candidate.get("pool_id")
    resource_id = candidate.get("resource_id")
    return StorefrontListingBinding(
        listing_id=listing_id,
        site_id=site_id,
        binding=binding,
        derivation_key=build_storefront_derivation_key(
            site_id=site_id,
            binding=binding,
            offering_mode=binding.offering_mode,
            source_identity=source,
        ),
        source_envelope_json=canonical_source_envelope(source),
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing=backing.label,
        pool_id=str(pool_id) if pool_id is not None else None,
        physical_resource_id=(
            str(resource_id) if resource_id is not None else None
        ),
    )


async def record_vm_listing_binding(
    *,
    db_path: str,
    listing_id: str,
    candidate: dict[str, Any],
) -> None:
    """Attach VM provenance after the common listing row is durably present."""

    registry = build_vm_storefront_registry()
    repository = SQLiteClient(db_path=db_path, registry=registry)
    await repository.record_listing_binding(
        binding=prepare_vm_listing_binding(
            listing_id=listing_id,
            candidate=candidate,
        )
    )
