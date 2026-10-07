"""Default VM listing shapes for a pool that states none.

A pool's listing shapes come from a storefront override, the pool's own
``listing_shapes`` hint, or, when neither states any, a default generator. The
generator is a seam: a pool's projected members go in and family-grouped shapes
come out. GPU-count enumeration is the default implementation.

The default declares the GPU family only. Every other dimension is left to
the site, which provisions it from its configured defaults, so a default shape
commits to nothing its members' declarations do not state.

A generated shape is nobody's statement, so it carries no constraints of its
own: its admissibility policy is the storefront's configured default alone,
and the generator receives that policy so it generates only what the policy
admits, rather than generating shapes publication would then withhold. See
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from market_capability_admissibility import ResolvedPolicy

from arkhai_vms.compute_requirements import GPU_COUNT_DIMENSION, GPU_MODEL_ATTRIBUTE

Shape = dict[str, dict[str, Any]]

_GPU_COUNT_PATH = "gpu.count"


class ListingShapeGenerator(Protocol):
    """Yield the shapes a pool's listings are sold in, from its projected members.

    ``policy`` is the default-only admissibility policy: the storefront's
    configured default resolved alone, which constrains nothing when the
    storefront configures none. Every shape yielded must be admissible under it.
    """

    def __call__(
        self, members: Iterable[Mapping[str, Any]], policy: ResolvedPolicy
    ) -> tuple[Shape, ...]: ...


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


def gpu_count_shapes(
    members: Iterable[Mapping[str, Any]], policy: ResolvedPolicy
) -> tuple[Shape, ...]:
    """One GPU-only shape per admitted GPU count, per GPU model among enabled members.

    For each model, the counts are those from one to the largest count any
    enabled member of that model declares that ``policy`` admits for that
    model. They are chosen from the policy's admissible values for the model,
    stepping through the answer rather than assuming it is one interval. A
    member declaring no positive GPU count or no GPU model yields nothing: a
    shape must name both, and nothing here substitutes a value a declaration
    does not carry. Deterministic: ordered by model, then count.
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
    shapes: list[Shape] = []
    for model in sorted(largest):
        admitted = policy.admissible_values(_GPU_COUNT_PATH, {"gpu": {"model": model}})
        count = admitted.at_least(1)
        while count is not None and count <= largest[model]:
            shapes.append({"gpu": {"count": count, "model": model}})
            count = admitted.at_least(count + 1)
    return tuple(shapes)


DEFAULT_LISTING_SHAPE_GENERATOR: ListingShapeGenerator = gpu_count_shapes

__all__ = [
    "DEFAULT_LISTING_SHAPE_GENERATOR",
    "ListingShapeGenerator",
    "Shape",
    "gpu_count_shapes",
]
