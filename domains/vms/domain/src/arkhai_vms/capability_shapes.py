"""VM capability shapes, for VM concept packages.

Every operation here binds the VM schema to the shared capability-shape kit, so
the schema is bound in one place and the kit stays schema-free. Every
function here binds the VM schema; the shared utility stays schema-free.
"""

from __future__ import annotations

from typing import Any

from market_capability_shape import (
    CapabilityShapeError,
    FlatShape,
    ShapeProblem,
    canonical_shape,
    flatten_shape,
    shape_digest,
    shape_problems,
)
from arkhai_vms.compute_requirements import VM_CAPABILITY_SCHEMA


def vm_shape_problems(shape: Any) -> tuple[ShapeProblem, ...]:
    """Every problem with ``shape`` in the VM vocabulary; empty when valid."""
    return shape_problems(shape, VM_CAPABILITY_SCHEMA)


def flatten_vm_shape(shape: Any) -> FlatShape:
    """A VM shape's published quantities and attributes by wire name."""
    return flatten_shape(shape, VM_CAPABILITY_SCHEMA)


def canonical_vm_shape(shape: Any) -> dict[str, dict[str, Any]]:
    """A valid VM shape in canonical form. Refuses one outside the vocabulary."""
    problems = vm_shape_problems(shape)
    if problems:
        raise CapabilityShapeError(problems)
    return canonical_shape(shape)


def vm_shape_digest(shape: Any) -> str:
    """The digest of a valid VM shape. Refuses one outside the vocabulary."""
    return shape_digest(canonical_vm_shape(shape))


__all__ = [
    "CapabilityShapeError",
    "FlatShape",
    "ShapeProblem",
    "canonical_vm_shape",
    "flatten_vm_shape",
    "vm_shape_digest",
    "vm_shape_problems",
]
