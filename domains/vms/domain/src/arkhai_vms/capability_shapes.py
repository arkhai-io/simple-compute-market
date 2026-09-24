"""VM capability shapes and listing identifiers, for VM concept packages.

VM concept packages (listing derivation, negotiation, settlement) import no
core package, so they reach the identifier encoding in ``market_core`` through
this module, and use the shared capability-shape kit through it as well so the
VM schema is bound in one place. Every
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
from market_core.identifier_encoding import length_prefixed, length_prefixed_join

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
    "length_prefixed",
    "length_prefixed_join",
    "vm_shape_digest",
    "vm_shape_problems",
]
