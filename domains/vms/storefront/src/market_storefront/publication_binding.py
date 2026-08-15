"""VM publication provenance persisted through the common storefront binding."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
    canonical_source_envelope,
)

from .domain_runtime import build_vm_storefront_registry
from .utils.sqlite_client import SQLiteClient


def prepare_vm_listing_binding(
    *,
    listing_id: str,
    candidate: dict[str, Any],
) -> StorefrontListingBinding:
    """Validate one VM candidate and return its immutable public-safe binding."""

    site_id = candidate.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("VM publication candidate requires an exact trusted site_id")
    pool_id = candidate.get("pool_id")
    resource_id = candidate.get("resource_id")
    if pool_id is None and resource_id is None:
        raise ValueError("VM publication candidate requires pool or resource provenance")
    registry = build_vm_storefront_registry()
    registration = registry.resolve_mode("vm")
    source = {
        "kind": "compute.listing_source",
        "schema_version": 1,
        "payload": {
            "site_id": site_id,
            "pool_id": str(pool_id) if pool_id is not None else None,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "gpu_count": int(candidate.get("gpu_count") or 1),
        },
    }
    return StorefrontListingBinding(
        listing_id=listing_id,
        site_id=site_id,
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id=site_id,
            binding=registration.binding,
            offering_mode=registration.binding.offering_mode,
            source_identity=source,
        ),
        source_envelope_json=canonical_source_envelope(source),
        last_reconciled_at=datetime.now(UTC).isoformat(),
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
