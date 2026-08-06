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

`max_reservation_hold_seconds` and `sla` are the two hints with a
domain-neutral, universally interpretable value (a nonnegative duration and
a nonnegative percentage-like number, respectively), so they are the ones
validated for content here. `region` is domain-neutral in the same sense
`listing_mode` is -- a free-form value with no universal validity rule this
package can usefully enforce -- so it gets only a bare read, matching
`raw_listing_mode`. `pricing` is domain-specific (its shape depends on what
resource-subtype dimensions a domain prices), so it also gets only a bare
read; the accepting domain owns interpreting and validating its contents.
"""

from __future__ import annotations

from typing import Any, Mapping


LISTING_MODE_POLICY_TAG = "listing_mode"
MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG = "max_reservation_hold_seconds"
REGION_POLICY_TAG = "region"
SLA_POLICY_TAG = "sla"
PRICING_POLICY_TAG = "pricing"


def raw_listing_mode(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `listing_mode` value, or None if absent.

    Returned as-is -- this package does not know which values a domain
    accepts. Callers resolve it through their own domain-owned resolver.
    """
    return policy_tags.get(LISTING_MODE_POLICY_TAG)


def raw_region(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `region` value, or None if absent.

    A free-form descriptive value (e.g. "California, US") -- there is no
    universal validity rule for a region string this package can usefully
    enforce, so this is a bare read, matching `raw_listing_mode`.
    """
    return policy_tags.get(REGION_POLICY_TAG)


def raw_pricing(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `pricing` value, or None if absent.

    Structured per resource family (e.g. `{"gpu": {"H100": {...}}}`) --
    the accepting domain owns both the family/dimension vocabulary and
    validating its contents, so this is a bare read, the same as
    `raw_listing_mode` and `raw_region`.
    """
    return policy_tags.get(PRICING_POLICY_TAG)


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


def sla_value(policy_tags: Mapping[str, Any]) -> float | None:
    """The pool's declared SLA, or None if absent or invalid.

    Invalid means "not a nonnegative number" -- the same rule
    `validate_sla_preference` enforces at write time. Consumers decide for
    themselves whether and how to trust this value (see
    `domains/vms/listings`' region/SLA resolver, which gates it behind a
    storefront-wide trust setting before ever reading it) -- this function
    only performs the domain-neutral type/sign check, the same posture
    `max_reservation_hold_seconds` already takes.
    """
    raw = policy_tags.get(SLA_POLICY_TAG)
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    if raw < 0:
        return None
    return float(raw)


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


def validate_sla_preference(policy_tags: Mapping[str, Any]) -> list[str]:
    """Return human-readable problems with a supplied SLA value.

    Empty list means valid (including "not supplied at all" -- this hint
    is optional). A present value must be a nonnegative number; `bool` is
    rejected for the same reason `validate_hold_preference` rejects it.
    No upper bound is enforced here -- what counts as a sensible SLA
    ceiling (a percentage, a nines-of-uptime count, or something else
    entirely) is a domain-owned interpretation question, not something
    this domain-neutral package should guess at.
    """
    if SLA_POLICY_TAG not in policy_tags:
        return []
    raw = policy_tags[SLA_POLICY_TAG]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return [f"{SLA_POLICY_TAG} must be a nonnegative number"]
    if raw < 0:
        return [f"{SLA_POLICY_TAG} must be a nonnegative number"]
    return []
