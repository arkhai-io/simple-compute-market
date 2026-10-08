"""Which shapes a pool's VM listings are sold in.

A pool's shapes come from exactly one source, in this precedence: the
storefront's own override for the pool's site and pool, the pool's
``listing_shapes`` hint for the ``vm`` offering mode, and otherwise the
domain's default generator. A stated list replaces every lower source as a
whole, together with any constraints its shapes carry. A stated list the VM
vocabulary cannot read is reported as unreadable and never replaced by a lower
source, because an unreadable declaration is not a withdrawn one.

A stated shape may carry inline ``{offer, min, max}`` constraints. Only the
admissibility kit reads them: it splits each stated list into base shapes,
which are the listings and carry their identity, and constraints, which govern
only admissibility. Each listing's policy resolves from its own constraints,
labelled by the source that stated them, over the storefront's configured
default. A list whose base shapes cannot all be read is unreadable; a listing
whose policy cannot be computed carries the problems instead of a policy, so
it is told apart from the pool's other listings. A generated shape has no constraints
of its own, so its policy is the configured default alone.

See openspec/specs/storefront-publication/spec.md, "Every VM listing is a listing
shape".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from market_capability_admissibility import (
    AdmissibilityProblem,
    AdmissibilityRequestError,
    Declaration,
    ResolvedPolicy,
    resolve,
    split_listing_shapes,
)

from arkhai_vms import (
    DEFAULT_LISTING_SHAPE_GENERATOR,
    VM_CAPABILITY_SCHEMA,
    ListingShapeGenerator,
    canonical_vm_shape,
    flatten_vm_shape,
    vm_shape_digest,
)

VM_OFFERING_MODE = "vm"

SHAPE_SOURCE_OVERRIDE = "storefront_override"
SHAPE_SOURCE_HINT = "pool_hint"
SHAPE_SOURCE_DEFAULT = "default"

# The tier label of the storefront's configured admissibility default.
CONFIGURED_DEFAULT_TIER = "configured_default"


@dataclass(frozen=True)
class ResolvedShape:
    """One VM listing shape, canonical, with its digest and flattened fields."""

    shape: Mapping[str, Mapping[str, Any]]
    digest: str
    quantities: Mapping[str, int]
    attributes: Mapping[str, str]

    @property
    def gpu_count(self) -> int:
        return int(self.quantities["gpu_count"])

    @property
    def gpu_model(self) -> str:
        return str(self.attributes["gpu_model"])


@dataclass(frozen=True)
class ListingShape:
    """One VM listing's base shape and its admissibility policy.

    ``policy`` is ``None`` exactly when the policy cannot be computed, and
    ``policy_problems`` then says why: unreadable constraints, an empty merged
    range, or a base shape its list states twice with different constraints.
    Both are opaque here; only the admissibility kit reads them.
    """

    shape: ResolvedShape
    policy: ResolvedPolicy | None
    policy_problems: tuple[AdmissibilityProblem, ...] = ()


@dataclass(frozen=True)
class ShapeResolution:
    """A pool's listings and where they came from, or why they cannot be read."""

    source: str
    listings: tuple[ListingShape, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def unreadable(self) -> bool:
        return bool(self.problems)

    @property
    def shapes(self) -> tuple[ResolvedShape, ...]:
        """Every listing's base shape, whether or not its policy is computable."""
        return tuple(listing.shape for listing in self.listings)

    @property
    def stated(self) -> bool:
        """Whether the shapes were declared rather than generated."""
        return self.source != SHAPE_SOURCE_DEFAULT


def resolve_shape(shape: Any) -> ResolvedShape:
    """Resolve one valid VM shape. Raises ``CapabilityShapeError`` otherwise."""
    canonical = canonical_vm_shape(shape)
    flat = flatten_vm_shape(canonical)
    return ResolvedShape(
        shape=canonical,
        digest=vm_shape_digest(canonical),
        quantities=dict(flat.quantities),
        attributes=dict(flat.attributes),
    )


def _deduplicated(shapes: Iterable[ResolvedShape]) -> tuple[ResolvedShape, ...]:
    seen: set[str] = set()
    out: list[ResolvedShape] = []
    for shape in shapes:
        if shape.digest not in seen:
            seen.add(shape.digest)
            out.append(shape)
    return tuple(out)


def _tiers(configured_default: Declaration | None) -> list[Declaration]:
    return [] if configured_default is None else [configured_default]


def default_only_policy(configured_default: Declaration | None) -> ResolvedPolicy:
    """The policy of a listing with no constraints of its own.

    The configured default resolved alone, or a policy constraining nothing
    when the storefront configures none. A default the storefront parsed
    against the VM schema always resolves; raises ``AdmissibilityRequestError``
    otherwise rather than leaving generated listings unconstrained.
    """
    resolution = resolve(_tiers(configured_default), VM_CAPABILITY_SCHEMA)
    if resolution.policy is None:
        raise AdmissibilityRequestError(resolution.problems)
    return resolution.policy


def resolve_stated_shapes(
    raw: Any, *, source: str, configured_default: Declaration | None
) -> ShapeResolution:
    """Resolve a stated shape list per listing, or report it unreadable.

    The list is split through the admissibility kit with the VM schema and
    ``source`` as the tier label. Any entry whose base shape cannot be read
    makes the whole list unreadable, naming each problem. Otherwise each
    distinct base shape is one listing, with its constraints resolved over
    ``configured_default``, or the problems that prevent a policy.
    """
    if not isinstance(raw, list) or not raw:
        return ShapeResolution(source, problems=("must be a non-empty list of shapes",))
    split = split_listing_shapes(raw, tier=source, schema=VM_CAPABILITY_SCHEMA)
    if split.base_problems:
        return ShapeResolution(
            source,
            problems=tuple(
                f"[{', '.join(str(entry) for entry in problem.entries)}] {problem}"
                for problem in split.base_problems
            ),
        )
    listings: list[ListingShape] = []
    for entry in split.shapes:
        shape = resolve_shape(entry.base_shape)
        if entry.declaration is None:
            listings.append(ListingShape(shape, None, entry.constraint_problems))
            continue
        resolution = resolve(
            [entry.declaration, *_tiers(configured_default)], VM_CAPABILITY_SCHEMA
        )
        listings.append(ListingShape(shape, resolution.policy, resolution.problems))
    return ShapeResolution(source, listings=tuple(listings))


def resolve_vm_listing_shapes(
    policy_tags: Mapping[str, Any],
    members: Iterable[Mapping[str, Any]],
    *,
    configured_default: Declaration | None,
    generator: ListingShapeGenerator = DEFAULT_LISTING_SHAPE_GENERATOR,
    override_shapes: Any = None,
) -> ShapeResolution:
    """A pool's VM listings: the storefront override's, else its stated hint,
    else the default generator's.

    ``override_shapes`` is the stored override's shape list, or ``None`` when
    the override states none. ``configured_default`` is the storefront's
    parsed ``[admissibility.defaults.vm]``, or ``None`` when it configures
    none; it is the lower tier of every listing's policy. An override's shapes
    never merge with the hint's constraints.
    """
    if override_shapes is not None:
        return resolve_stated_shapes(
            override_shapes,
            source=SHAPE_SOURCE_OVERRIDE,
            configured_default=configured_default,
        )
    # Local import: buyers install this package without the resource-pool kit,
    # and only storefront derivation reads pool hints.
    from market_resource_pools_contracts import (
        LISTING_SHAPES_POLICY_TAG,
        raw_listing_shapes,
    )

    declared = policy_tags.get(LISTING_SHAPES_POLICY_TAG)
    if declared is not None and not isinstance(declared, Mapping):
        return ShapeResolution(
            SHAPE_SOURCE_HINT,
            problems=("must be a mapping of offering mode to a list of shapes",),
        )
    stated = raw_listing_shapes(policy_tags, VM_OFFERING_MODE)
    if stated is not None:
        return resolve_stated_shapes(
            stated, source=SHAPE_SOURCE_HINT, configured_default=configured_default
        )
    policy = default_only_policy(configured_default)
    return ShapeResolution(
        SHAPE_SOURCE_DEFAULT,
        listings=tuple(
            ListingShape(shape, policy)
            for shape in _deduplicated(
                resolve_shape(shape) for shape in generator(members, policy)
            )
        ),
    )


__all__ = [
    "CONFIGURED_DEFAULT_TIER",
    "ListingShape",
    "SHAPE_SOURCE_DEFAULT",
    "SHAPE_SOURCE_HINT",
    "SHAPE_SOURCE_OVERRIDE",
    "ResolvedShape",
    "ShapeResolution",
    "default_only_policy",
    "resolve_shape",
    "resolve_stated_shapes",
    "resolve_vm_listing_shapes",
]
