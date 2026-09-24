"""Domain-neutral Resource Pool policy-tag vocabulary.

Resource Pool ``policy_tags`` is the one administration and projection
channel for pool policy. This module owns the stable key names plus the
domain-neutral validation that can be applied without knowing a consumer's
market vocabulary.

``deliverable_modes`` is an authoritative set of opaque offering-mode names
the pool's provider can deliver; every execution layer rechecks it. This
package validates only that the declaration is a JSON-compatible set of
unique, non-empty strings. Domains decide which names are meaningful. Absence
and an explicit empty list both mean that the pool declares no deliverable
mode; neither is a permissive default.

``advertisable_modes`` and ``capacity_backing`` are the pool's advertisement
and admission declarations, and every pool must carry both:

- ``advertisable_modes`` names the modes the pool's listings may advertise.
  It has the same shape as ``deliverable_modes`` and is a separate claim:
  advertising a mode never requires proving delivery of it, because a seller
  trading by private arrangement can prove nothing and must still be able to
  list.
- ``capacity_backing`` is ``backed`` when an admission authority stands behind
  the pool and ``unbacked`` when none does. It is a discriminator, so an
  unrecognized value is refused rather than resolved to either side.
- A backed pool may advertise only what it delivers, otherwise a buyer could
  reach admission for a mode the provider will refuse. An unbacked pool must
  deliver nothing: no layer reads backing at admission, so an empty
  deliverable set is what keeps every capacity path unreachable for it.

An absent declaration is reported as absent, never defaulted, so a consumer
reading projected tags can tell a producer that predates these tags from one
that omitted them for a single pool. For the same reason advertisement
membership is offered only on a resolved `PoolDeclarations`, never on raw
tags where absence would read as empty.

``max_reservation_hold_seconds`` and ``sla`` have universally interpretable
numeric values and are validated here. ``listing_cardinality_mode``, ``region``,
and ``pricing`` remain domain-owned values exposed through raw readers.

``listing_cardinality_mode`` carries how many listing candidates a pool yields
and how each is independently identified -- not what is offered, how a deal
settles, or whether an admission authority backs the listing. The reader below
accepts one deprecated spelling of that key; see its docstring for why the
concession is on the read path only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from market_capability_shape import shape_structure_problems


DELIVERABLE_MODES_POLICY_TAG = "deliverable_modes"
ADVERTISABLE_MODES_POLICY_TAG = "advertisable_modes"
CAPACITY_BACKING_POLICY_TAG = "capacity_backing"
CAPACITY_BACKED = "backed"
CAPACITY_UNBACKED = "unbacked"
CAPACITY_BACKING_VALUES = frozenset({CAPACITY_BACKED, CAPACITY_UNBACKED})
CapacityBacking = Literal["backed", "unbacked"]

# Structured problem codes shared by the pool models, document validation,
# stored-state checks, and the projection resolver.
MISSING_DECLARATION = "missing_declaration"
INVALID_DELIVERABLE_MODES = "invalid_deliverable_modes"
INVALID_ADVERTISABLE_MODES = "invalid_advertisable_modes"
INVALID_CAPACITY_BACKING = "invalid_capacity_backing"
ADVERTISABLE_EXCEEDS_DELIVERABLE = "advertisable_exceeds_deliverable"
UNBACKED_POOL_DELIVERS = "unbacked_pool_delivers"
LISTING_CARDINALITY_MODE_POLICY_TAG = "listing_cardinality_mode"
# Producers emit LISTING_CARDINALITY_MODE_POLICY_TAG. This spelling is accepted
# on read so a pool written by an older producer resolves to the cardinality it
# declared instead of falling through to a consumer's structural default: the
# key is optional, so rejecting it would be indistinguishable from absence and
# would silently reclassify the pool rather than refuse it.
DEPRECATED_LISTING_MODE_POLICY_TAG = "listing_mode"
MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG = "max_reservation_hold_seconds"
REGION_POLICY_TAG = "region"
SLA_POLICY_TAG = "sla"
PRICING_POLICY_TAG = "pricing"
LISTING_SHAPES_POLICY_TAG = "listing_shapes"


def _declared_mode_set(policy_tags: Mapping[str, Any], tag: str) -> frozenset[str]:
    """Read one mode-set declaration, absent meaning empty.

    Stored as a JSON list so order is stable in exported pool documents, but
    its semantics are a set. Unknown mode names remain valid and opaque.
    Malformed declarations raise rather than widening or silently becoming
    empty.
    """
    if tag not in policy_tags:
        return frozenset()
    raw = policy_tags[tag]
    message = f"{tag} must be a list of unique non-empty strings"
    if not isinstance(raw, list):
        raise ValueError(message)
    modes: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(message)
        modes.append(value)
    if len(modes) != len(set(modes)):
        raise ValueError(message)
    return frozenset(modes)


def declared_deliverable_modes(policy_tags: Mapping[str, Any]) -> frozenset[str]:
    """Return the pool's authoritative deliverable-mode declaration."""
    return _declared_mode_set(policy_tags, DELIVERABLE_MODES_POLICY_TAG)


def _declared_advertisable_modes(policy_tags: Mapping[str, Any]) -> frozenset[str]:
    # Private on purpose: it reads absence as empty, which erases the
    # distinction a reader of projected declarations must keep. Readers go
    # through `resolve_pool_declarations` and `PoolDeclarations.advertises`.
    return _declared_mode_set(policy_tags, ADVERTISABLE_MODES_POLICY_TAG)


def pool_delivers_offering_mode(
    policy_tags: Mapping[str, Any],
    requested_mode: str,
) -> bool:
    """The shared reservation/scheduling/provisioning capability predicate."""
    if not isinstance(requested_mode, str) or not requested_mode.strip():
        return False
    return requested_mode in declared_deliverable_modes(policy_tags)


def validate_deliverable_modes(policy_tags: Mapping[str, Any]) -> list[str]:
    """Return a write-side problem for a malformed mode declaration."""
    try:
        declared_deliverable_modes(policy_tags)
    except ValueError as exc:
        return [str(exc)]
    return []


@dataclass(frozen=True)
class PoolDeclarationProblem:
    """One reason a pool's advertisement or backing declaration is invalid."""

    tag: str
    code: str
    message: str


@dataclass(frozen=True)
class PoolDeclarations:
    """A pool's resolved advertisement and admission declarations."""

    advertisable_modes: frozenset[str]
    capacity_backing: CapacityBacking

    @property
    def backed(self) -> bool:
        return self.capacity_backing == CAPACITY_BACKED

    def advertises(self, requested_mode: str) -> bool:
        """Whether the pool's listings may advertise `requested_mode`.

        Advertisement only: whether the pool can deliver the mode is decided
        by every execution layer from `deliverable_modes`. Offered only on a
        resolved declaration, so no reader can test membership against a pool
        whose declaration was absent.
        """
        if not isinstance(requested_mode, str) or not requested_mode.strip():
            return False
        return requested_mode in self.advertisable_modes


class PoolDeclarationError(ValueError):
    """A pool's declarations cannot be resolved; carries every problem found."""

    def __init__(self, problems: tuple[PoolDeclarationProblem, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(problem.message for problem in problems))


class MissingPoolDeclarationError(PoolDeclarationError):
    """Every problem is an absent tag, none a malformed one.

    Kept distinct so a consumer can apply a producer-version rule to a
    producer that emits these tags for no pool, while a pool whose tags are
    present but wrong still fails closed.
    """


def pool_declaration_problems(
    policy_tags: Mapping[str, Any],
) -> tuple[PoolDeclarationProblem, ...]:
    """Every problem with a pool's mode and backing declarations.

    The one owner of the declaration invariant: deliverable shape, the
    presence and shape of both advertisement and backing, and the two
    cross-tag rules. The pool models, the service, document validation, and
    the resolver all use it, so they cannot disagree about what a valid
    declaration is. A cross-tag rule is not judged against a set or value
    that did not parse; the parse failure is reported instead.
    """
    problems: list[PoolDeclarationProblem] = []

    try:
        deliverable: frozenset[str] | None = declared_deliverable_modes(policy_tags)
    except ValueError as exc:
        deliverable = None
        problems.append(PoolDeclarationProblem(
            DELIVERABLE_MODES_POLICY_TAG, INVALID_DELIVERABLE_MODES, str(exc),
        ))

    advertisable: frozenset[str] | None = None
    if ADVERTISABLE_MODES_POLICY_TAG not in policy_tags:
        problems.append(PoolDeclarationProblem(
            ADVERTISABLE_MODES_POLICY_TAG,
            MISSING_DECLARATION,
            f"{ADVERTISABLE_MODES_POLICY_TAG} is required",
        ))
    else:
        try:
            advertisable = _declared_advertisable_modes(policy_tags)
        except ValueError as exc:
            problems.append(PoolDeclarationProblem(
                ADVERTISABLE_MODES_POLICY_TAG, INVALID_ADVERTISABLE_MODES, str(exc),
            ))

    backing: str | None = None
    if CAPACITY_BACKING_POLICY_TAG not in policy_tags:
        problems.append(PoolDeclarationProblem(
            CAPACITY_BACKING_POLICY_TAG,
            MISSING_DECLARATION,
            f"{CAPACITY_BACKING_POLICY_TAG} is required",
        ))
    else:
        raw = policy_tags[CAPACITY_BACKING_POLICY_TAG]
        if isinstance(raw, str) and raw in CAPACITY_BACKING_VALUES:
            backing = raw
        else:
            problems.append(PoolDeclarationProblem(
                CAPACITY_BACKING_POLICY_TAG,
                INVALID_CAPACITY_BACKING,
                f"{CAPACITY_BACKING_POLICY_TAG} must be "
                f"'{CAPACITY_BACKED}' or '{CAPACITY_UNBACKED}'",
            ))

    if backing == CAPACITY_BACKED and advertisable is not None and deliverable is not None:
        excess = advertisable - deliverable
        if excess:
            problems.append(PoolDeclarationProblem(
                ADVERTISABLE_MODES_POLICY_TAG,
                ADVERTISABLE_EXCEEDS_DELIVERABLE,
                f"a backed pool may advertise only modes it delivers; "
                f"{ADVERTISABLE_MODES_POLICY_TAG} names undelivered "
                f"{', '.join(sorted(excess))}",
            ))
    if backing == CAPACITY_UNBACKED and deliverable:
        problems.append(PoolDeclarationProblem(
            DELIVERABLE_MODES_POLICY_TAG,
            UNBACKED_POOL_DELIVERS,
            f"an unbacked pool must deliver nothing; "
            f"{DELIVERABLE_MODES_POLICY_TAG} names {', '.join(sorted(deliverable))}",
        ))
    return tuple(problems)


def validate_pool_declarations(policy_tags: Mapping[str, Any]) -> list[str]:
    """Return write-side problems with the pool's mode and backing declarations."""
    return [problem.message for problem in pool_declaration_problems(policy_tags)]


def resolve_pool_declarations(policy_tags: Mapping[str, Any]) -> PoolDeclarations:
    """Resolve a pool's advertisement and backing declarations, or fail.

    The one reader of these tags for any consumer, including a storefront
    reading the resource-pool projection, so the site that writes a
    declaration and every reader agree on what a valid one is. Nothing is
    defaulted: absence raises `MissingPoolDeclarationError`, and anything
    malformed or inconsistent raises `PoolDeclarationError`. How to treat a
    producer that emits these tags for no pool is the caller's decision.
    """
    problems = pool_declaration_problems(policy_tags)
    if problems:
        if all(problem.code == MISSING_DECLARATION for problem in problems):
            raise MissingPoolDeclarationError(tuple(problems))
        raise PoolDeclarationError(tuple(problems))
    return PoolDeclarations(
        advertisable_modes=_declared_advertisable_modes(policy_tags),
        capacity_backing=cast(CapacityBacking, policy_tags[CAPACITY_BACKING_POLICY_TAG]),
    )


def raw_listing_cardinality_mode(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `listing_cardinality_mode` value, or None if absent.

    Returned as-is -- this package does not know which values a domain
    accepts. Callers resolve it through their own domain-owned resolver.

    The deprecated spelling is read only when the settled key is absent, so a
    pool carrying both resolves to the settled one. A caller that needs to tell
    an operator the deprecated key was taken uses
    `listing_cardinality_mode_source` rather than re-reading both keys.
    """
    if LISTING_CARDINALITY_MODE_POLICY_TAG in policy_tags:
        return policy_tags[LISTING_CARDINALITY_MODE_POLICY_TAG]
    return policy_tags.get(DEPRECATED_LISTING_MODE_POLICY_TAG)


def listing_cardinality_mode_source(policy_tags: Mapping[str, Any]) -> str | None:
    """Which key supplied the cardinality value, or None when neither did.

    Exists so a consumer can emit a deprecation notice without duplicating the
    precedence rule above. Returning the key name rather than a boolean keeps
    the notice able to name what an operator must change.
    """
    if LISTING_CARDINALITY_MODE_POLICY_TAG in policy_tags:
        return LISTING_CARDINALITY_MODE_POLICY_TAG
    if DEPRECATED_LISTING_MODE_POLICY_TAG in policy_tags:
        return DEPRECATED_LISTING_MODE_POLICY_TAG
    return None


def raw_region(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `region` value, or None if absent.

    A free-form descriptive value (e.g. "California, US") -- there is no
    universal validity rule for a region string this package can usefully
    enforce, so this is a bare read, matching
    `raw_listing_cardinality_mode`.
    """
    return policy_tags.get(REGION_POLICY_TAG)


def raw_pricing(policy_tags: Mapping[str, Any]) -> Any:
    """The unvalidated `pricing` value, or None if absent.

    Structured per resource family (e.g. `{"gpu": {"H100": {...}}}`) --
    the accepting domain owns both the family/dimension vocabulary and
    validating its contents, so this is a bare read, the same as
    `raw_listing_cardinality_mode` and `raw_region`.
    """
    return policy_tags.get(PRICING_POLICY_TAG)


def raw_listing_shapes(policy_tags: Mapping[str, Any], offering_mode: str) -> Any:
    """The unvalidated shape list a pool states for ``offering_mode``, or None.

    None when the pool states no ``listing_shapes`` at all, when the value is
    not a mapping, or when it names no list for this mode. The domain selling
    ``offering_mode`` owns the shape vocabulary and validates each shape; this
    package checks only structure, at write time (``validate_listing_shapes``).
    """
    shapes = policy_tags.get(LISTING_SHAPES_POLICY_TAG)
    if not isinstance(shapes, Mapping):
        return None
    return shapes.get(offering_mode)


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


def validate_listing_shapes(policy_tags: Mapping[str, Any]) -> list[str]:
    """Return human-readable problems with a supplied ``listing_shapes`` value.

    Empty list means valid, including "not supplied at all": the hint is
    optional. A present value must map each offering mode to a non-empty list
    of structurally well-formed family-grouped capability shapes. Which
    families and fields exist, and which are required, is the reading domain's
    to validate, so a well-formed shape naming a field no domain defines is
    accepted here. An empty list is refused because stopping sales is done by
    closing listings, not by declaring nothing.
    """
    if LISTING_SHAPES_POLICY_TAG not in policy_tags:
        return []
    raw = policy_tags[LISTING_SHAPES_POLICY_TAG]
    tag = LISTING_SHAPES_POLICY_TAG
    if not isinstance(raw, Mapping):
        return [f"{tag} must be a mapping of offering mode to a list of shapes"]
    problems: list[str] = []
    for mode, shapes in raw.items():
        if not isinstance(mode, str) or not mode:
            problems.append(f"{tag} offering modes must be non-empty strings, not {mode!r}")
            continue
        if not isinstance(shapes, list) or not shapes:
            problems.append(f"{tag}.{mode} must be a non-empty list of shapes")
            continue
        for index, shape in enumerate(shapes):
            for problem in shape_structure_problems(shape):
                location = f"{tag}.{mode}[{index}]"
                if problem.path:
                    location += f".{problem.path}"
                problems.append(f"{location}: {problem.message}")
    return problems
