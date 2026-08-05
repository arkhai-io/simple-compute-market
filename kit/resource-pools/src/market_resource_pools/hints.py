"""Domain-neutral publication and reservation-hold hint keys.

Resource Pool `policy_tags` is an opaque dict as far as this package's own
CRUD/reconciliation logic is concerned (see `service.py`). This module owns
the stable key names two hints are projected under, plus generic read-side
interpretation and write-side validation that applies regardless of which
domain (VM, bare metal, ...) ends up consuming a given tag. Domains own
their own accepted `listing_mode` values and structural defaults; this
module never defines or validates a value for that key, only the key's
name and the fact that an unrecognized value must remain forward-compatible
opaque metadata rather than a validation failure.

`max_reservation_hold_seconds` is the one hint with a domain-neutral,
universally interpretable value (a nonnegative duration), so it is the only
one validated for content here.
"""

from __future__ import annotations

from typing import Any, Mapping


LISTING_MODE_POLICY_TAG = "listing_mode"
MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG = "max_reservation_hold_seconds"


def raw_listing_mode(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `listing_mode` value, or None if absent.

    Returned as-is -- this package does not know which values a domain
    accepts. Callers resolve it through their own domain-owned resolver.
    """
    return policy_tags.get(LISTING_MODE_POLICY_TAG)


def max_reservation_hold_seconds(policy_tags: Mapping[str, Any]) -> int | None:
    """The pool's advisory hold-TTL cap, or None if absent or invalid.

    Invalid here means "not a nonnegative integer" -- the same rule
    `validate_hold_preference` enforces at write time. A pool written before
    validation existed, or written through a path that doesn't call it,
    could still carry a bad value; a caller must not raise on it, only
    ignore it, matching the "unknown/invalid hint never changes admission
    authority" requirement.
    """
    raw = policy_tags.get(MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG)
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, int):
        return None
    if raw < 0:
        return None
    return raw


def capped_hold_seconds(requested_seconds: float, policy_tags: Mapping[str, Any]) -> float:
    """Cap a caller-requested hold TTL by the pool's advisory preference.

    Falls back to `requested_seconds` unchanged whenever the preference is
    absent or invalid -- this hint is advisory, never authoritative, and a
    missing/bad value must never block hold placement (the caller's own
    fail-open posture, preserved here rather than re-implemented per call
    site).
    """
    cap = max_reservation_hold_seconds(policy_tags)
    if cap is None:
        return requested_seconds
    return min(requested_seconds, float(cap))


def validate_hold_preference(policy_tags: Mapping[str, Any]) -> list[str]:
    """Return human-readable problems with a supplied hold preference.

    Empty list means valid (including "not supplied at all" -- this hint
    is optional). A present value must be a nonnegative integer; `bool` is
    rejected even though it is technically an `int` subtype, since a
    True/False hold preference is never a meaningful value.
    """
    if MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG not in policy_tags:
        return []
    raw = policy_tags[MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG]
    if isinstance(raw, bool) or not isinstance(raw, int):
        return [
            f"{MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG} must be a nonnegative integer",
        ]
    if raw < 0:
        return [
            f"{MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG} must be a nonnegative integer",
        ]
    return []
