"""Default VM listing shapes for a pool that states none.

A pool's listing shapes come from a storefront override, the pool's own
``listing_shapes`` hint, or, when neither states any, a default generator. The
generator is a seam: a pool's projected members go in and family-grouped shapes
come out. GPU-count enumeration is the default implementation.

The default declares the GPU family only. Every other dimension is left to
the site, which provisions it from its configured defaults, so a default shape
commits to nothing its members' declarations do not state. See
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from arkhai_vms.compute_requirements import GPU_COUNT_DIMENSION, GPU_MODEL_ATTRIBUTE

Shape = dict[str, dict[str, Any]]


class ListingShapeGenerator(Protocol):
    """Yield the shapes a pool's listings are sold in, from its projected members."""

    def __call__(self, members: Iterable[Mapping[str, Any]]) -> tuple[Shape, ...]: ...


def _declared_gpu_count(member: Mapping[str, Any]) -> int | None:
    value = (member.get("capacity") or {}).get(GPU_COUNT_DIMENSION)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _declared_gpu_model(member: Mapping[str, Any]) -> str | None:
    value = (member.get("attributes") or {}).get(GPU_MODEL_ATTRIBUTE)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def gpu_count_shapes(members: Iterable[Mapping[str, Any]]) -> tuple[Shape, ...]:
    """One GPU-only shape per GPU count, per GPU model among enabled members.

    For each model, counts run from one to the largest count any enabled member
    of that model declares. A member declaring no positive GPU count or no GPU
    model yields nothing: a shape must name both, and nothing here substitutes
    a value a declaration does not carry. Deterministic: ordered by model, then
    count.
    """
    largest: dict[str, int] = {}
    for member in members:
        if not member.get("enabled", True):
            continue
        count = _declared_gpu_count(member)
        model = _declared_gpu_model(member)
        if count is None or model is None:
            continue
        largest[model] = max(largest.get(model, 0), count)
    return tuple(
        {"gpu": {"count": count, "model": model}}
        for model in sorted(largest)
        for count in range(1, largest[model] + 1)
    )


DEFAULT_LISTING_SHAPE_GENERATOR: ListingShapeGenerator = gpu_count_shapes

__all__ = [
    "DEFAULT_LISTING_SHAPE_GENERATOR",
    "ListingShapeGenerator",
    "Shape",
    "gpu_count_shapes",
]
