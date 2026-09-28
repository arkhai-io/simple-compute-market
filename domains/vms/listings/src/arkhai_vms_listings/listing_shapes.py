"""Which shapes a pool's VM listings are sold in.

A pool's shapes come from exactly one source, in this precedence: the
storefront's own override for the pool's site and pool, the pool's
``listing_shapes`` hint for the ``vm`` offering mode, and otherwise the
domain's default generator. A stated list replaces every lower source as a
whole. A stated list the VM vocabulary cannot read is reported as unreadable
and never replaced by a lower source, because an unreadable declaration is not
a withdrawn one.

See openspec/specs/storefront-publication/spec.md, "Every VM listing is a listing
shape".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_vms import (
    DEFAULT_LISTING_SHAPE_GENERATOR,
    ListingShapeGenerator,
    canonical_vm_shape,
    flatten_vm_shape,
    vm_shape_digest,
    vm_shape_problems,
)

VM_OFFERING_MODE = "vm"

SHAPE_SOURCE_OVERRIDE = "storefront_override"
SHAPE_SOURCE_HINT = "pool_hint"
SHAPE_SOURCE_DEFAULT = "default"


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
class ShapeResolution:
    """A pool's shapes and where they came from, or why they cannot be read."""

    source: str
    shapes: tuple[ResolvedShape, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def unreadable(self) -> bool:
        return bool(self.problems)

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


def resolve_stated_shapes(raw: Any, *, source: str) -> ShapeResolution:
    """Resolve a stated shape list, or report it unreadable naming each problem."""
    if not isinstance(raw, list) or not raw:
        return ShapeResolution(source, problems=("must be a non-empty list of shapes",))
    problems: list[str] = []
    for index, shape in enumerate(raw):
        for problem in vm_shape_problems(shape):
            problems.append(f"[{index}] {problem}")
    if problems:
        return ShapeResolution(source, problems=tuple(problems))
    return ShapeResolution(source, shapes=_deduplicated(resolve_shape(s) for s in raw))


def resolve_vm_listing_shapes(
    policy_tags: Mapping[str, Any],
    members: Iterable[Mapping[str, Any]],
    *,
    generator: ListingShapeGenerator = DEFAULT_LISTING_SHAPE_GENERATOR,
    override_shapes: Any = None,
) -> ShapeResolution:
    """A pool's VM shapes: the storefront override's, else its stated hint,
    else the default generator.

    ``override_shapes`` is the stored override's shape list, or ``None`` when
    the override states none.
    """
    if override_shapes is not None:
        return resolve_stated_shapes(override_shapes, source=SHAPE_SOURCE_OVERRIDE)
    # Local import: buyers install this package without the resource-pool kit,
    # and only storefront derivation reads pool hints.
    from market_resource_pools import LISTING_SHAPES_POLICY_TAG, raw_listing_shapes

    declared = policy_tags.get(LISTING_SHAPES_POLICY_TAG)
    if declared is not None and not isinstance(declared, Mapping):
        return ShapeResolution(
            SHAPE_SOURCE_HINT,
            problems=("must be a mapping of offering mode to a list of shapes",),
        )
    stated = raw_listing_shapes(policy_tags, VM_OFFERING_MODE)
    if stated is not None:
        return resolve_stated_shapes(stated, source=SHAPE_SOURCE_HINT)
    return ShapeResolution(
        SHAPE_SOURCE_DEFAULT,
        shapes=_deduplicated(resolve_shape(shape) for shape in generator(members)),
    )


__all__ = [
    "SHAPE_SOURCE_DEFAULT",
    "SHAPE_SOURCE_HINT",
    "SHAPE_SOURCE_OVERRIDE",
    "ResolvedShape",
    "ShapeResolution",
    "resolve_shape",
    "resolve_stated_shapes",
    "resolve_vm_listing_shapes",
]
