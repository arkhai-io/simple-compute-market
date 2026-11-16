"""Capacity-bound publication hints, independent of commercial entitlements."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictInt

CAPACITY_BOUNDS_POLICY_TAG = "capacity_bounds"


def utc_availability(value: Any) -> str:
    """Read an ISO datetime in UTC without guessing a timezone or epoch unit."""
    if isinstance(value, str):
        try:
            instant = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("available_until_utc must be an ISO datetime in UTC") from exc
    elif isinstance(value, datetime):
        instant = value
    else:
        raise ValueError("available_until_utc must be an ISO datetime in UTC")
    if instant.utcoffset() != timedelta(0):
        raise ValueError("available_until_utc must be timezone-aware UTC (Z or +00:00)")
    return instant.isoformat().replace("+00:00", "Z")


UtcAvailability = Annotated[str, BeforeValidator(utc_availability)]


def positive_duration_bound(value: Any) -> int | None:
    """Normalize a relative bound only after its precedence tier is selected."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("max_duration_seconds must be an integer or null")
    return value if value > 0 else None


class CapacityBounds(BaseModel):
    """One tier's bounds for an offering mode.

    A nonpositive relative value explicitly removes the relative limit, so it
    stays stated until resolution; null/absent fields defer to a lower tier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_duration_seconds: StrictInt | None = None
    available_until_utc: UtcAvailability | None = None

    @property
    def positive_max_duration_seconds(self) -> int | None:
        return positive_duration_bound(self.max_duration_seconds)


def capacity_bound_hint(policy_tags: Mapping[str, Any], offering_mode: str) -> CapacityBounds:
    """Read validated hints for one mode, refusing malformed stored projections."""
    raw = policy_tags.get(CAPACITY_BOUNDS_POLICY_TAG, {})
    if not isinstance(raw, Mapping):
        raise ValueError("capacity_bounds must map offering modes to bounds")
    bounds: dict[str, CapacityBounds] = {}
    for mode, value in raw.items():
        if not isinstance(mode, str) or not mode.strip() or mode != mode.strip():
            raise ValueError("capacity_bounds offering modes must be non-empty trimmed strings")
        if not isinstance(value, Mapping):
            raise ValueError(f"capacity_bounds.{mode} must be a mapping of bounds")
        try:
            bounds[mode] = CapacityBounds.model_validate(dict(value))
        except ValueError as exc:
            raise ValueError(f"capacity_bounds.{mode}: {exc}") from exc
    return bounds.get(offering_mode, CapacityBounds())


def validate_capacity_bounds(policy_tags: Mapping[str, Any]) -> list[str]:
    """Problems reported by pool writes before hints reach a storefront."""
    try:
        capacity_bound_hint(policy_tags, "")
    except ValueError as exc:
        return [str(exc)]
    return []


def resolve_capacity_bounds(*tiers: CapacityBounds) -> CapacityBounds:
    """Resolve each field independently, from highest to lowest precedence."""
    return CapacityBounds(
        **{
            name: next(
                (getattr(tier, name) for tier in tiers if getattr(tier, name) is not None),
                None,
            )
            for name in CapacityBounds.model_fields
        }
    )
