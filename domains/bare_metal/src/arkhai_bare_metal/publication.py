"""Bare-metal listing derivation from site-authority capacity snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .schema import (
    EXCLUSIVE_ALLOCATION_MODE,
    PHYSICAL_HOST_ID_REF_KEY,
    BareMetalListing,
)

ALLOCATION_MODE_ATTR = "allocation_mode"
MACHINE_ID_ATTR = "machine_id"

_CAPABILITY_SKIP_KEYS = {
    ALLOCATION_MODE_ATTR,
    MACHINE_ID_ATTR,
    PHYSICAL_HOST_ID_REF_KEY,
}


def bare_metal_listing_key(machine_id: str) -> str:
    """Stable derivation key for one whole-machine bare-metal listing."""
    return f"bare-metal:{machine_id}"


def available_bare_metal_listings(
    resources: Iterable[dict[str, Any]],
    *,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    site: dict[str, str] | None = None,
) -> list[BareMetalListing]:
    """Derive whole-host bare-metal listings from site snapshot rows.

    A resource is publishable when it is enabled, has at least one available
    unit, and declares ``allocation_mode=exclusive`` plus ``physical_host_id``.
    ``machine_id`` defaults to the site resource id so the provisioning host
    registry can use the same name as the ledger resource when no separate
    executor-local name is needed.
    """
    listings: list[BareMetalListing] = []
    for row in resources:
        attrs = _attributes(row)
        if str(attrs.get(ALLOCATION_MODE_ATTR) or "") != EXCLUSIVE_ALLOCATION_MODE:
            continue
        if not bool(row.get("enabled", True)):
            continue
        if int(row.get("available_units") or 0) < 1:
            continue
        physical_host_id = str(attrs.get(PHYSICAL_HOST_ID_REF_KEY) or "").strip()
        if not physical_host_id:
            continue
        machine_id = str(attrs.get(MACHINE_ID_ATTR) or row.get("resource_id") or "").strip()
        if not machine_id:
            continue
        listings.append(
            BareMetalListing(
                machine_id=machine_id,
                physical_host_id=physical_host_id,
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                site=site,
                capabilities=_capabilities(attrs),
            )
        )
    return listings


def _attributes(row: dict[str, Any]) -> dict[str, Any]:
    attrs = row.get("attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def _capabilities(attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in attrs.items()
        if key not in _CAPABILITY_SKIP_KEYS
    }
