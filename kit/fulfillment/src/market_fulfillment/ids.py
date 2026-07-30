"""Opaque UUIDv7 identifiers for the fulfillment lifecycle.

Authority and routing remain explicit fields such as ``site_id`` and
``pool_id``; callers must not decode those values from an identifier. UUIDv7
provides time-local insertion order while preserving opaque string contracts on
supported Python versions.

See ``openspec/specs/fulfillment/spec.md#identities``.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from uuid6 import uuid7


def new_capacity_reservation_id() -> str:
    """Return an ID for admitted capacity and scheduling idempotency."""

    return str(uuid7())


def new_fulfillment_id() -> str:
    """Return an ID for one post-acceptance fulfillment aggregate."""

    return str(uuid7())


def new_provisioned_resource_id() -> str:
    """Return an ID for one provider-created output of a fulfillment."""

    return str(uuid7())


def new_settlement_resource_id() -> str:
    """Return an ID for selected underlying physical supply."""

    return str(uuid7())


def new_result_id() -> str:
    """Return an ID for one recorded fulfillment result."""

    return str(uuid7())


def derive_provisioned_resource_id(*, identity_scope: str, provider_output_key: str) -> str:
    """Derive a stable opaque output ID from stable fulfillment-owned coordinates.

    ``identity_scope`` identifies the durable aggregate or legacy ledger entry
    that owns the output. ``provider_output_key`` distinguishes outputs within
    that scope but is not exposed as the fulfillment identity itself.
    """

    return str(uuid5(NAMESPACE_URL, f"provisioned-resource:{identity_scope}:{provider_output_key}"))
