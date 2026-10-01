"""VM capability shapes, for VM concept packages.

Every operation here binds the VM schema to the shared capability-shape kit, so
the schema is bound in one place and the kit stays schema-free. Every
function here binds the VM schema; the shared utility stays schema-free.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from market_capability_pricing import (
    FamilyRate,
    PricedFamily,
    PriceAggregator,
    PricingProjection,
    ShapePrice,
    linear_price,
)
from market_core.schemas import PER_UNIT_SECONDS
from arkhai_vms.compute_requirements import VM_CAPABILITY_SCHEMA

#: The families a VM rate may be stated for and what each is priced by: GPUs per
#: card, per GPU model; vCPUs per vCPU; memory and storage per GiB. Stated, not
#: inferred from the schema, because which attribute a price varies by is a
#: commercial choice; a test checks it agrees with the schema.
VM_PRICING_PROJECTION = PricingProjection(
    {
        "gpu": PricedFamily("count", key="model"),
        "cpu": PricedFamily("count"),
        "memory": PricedFamily("gib"),
        "storage": PricedFamily("gib"),
    }
)

#: The VM domain's price aggregation. Selected here, by the domain, so a
#: deployment has exactly one; operator configuration does not choose it.
VM_PRICE_AGGREGATOR: PriceAggregator = linear_price


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


def vm_family_rate(rate: Any, per: Any) -> FamilyRate:
    """A VM family rate: positive decimal text per unit per time unit.

    VM capacity is leased by time, so a rate's unit must be one settlement can
    scale by a duration.
    """
    family_rate = FamilyRate(rate, per)
    if family_rate.per not in PER_UNIT_SECONDS:
        raise ValueError(f"family rate unit {per!r} is not a time unit")
    return family_rate


def price_vm_shape(
    shape: Any,
    rates: Mapping[str, FamilyRate],
) -> ShapePrice:
    """A valid VM shape's exact price from one asset's family rates.

    Every VM price is reached through this, never by multiplying a family's rate
    by its quantity, so changing ``VM_PRICE_AGGREGATOR`` changes every price.
    Refuses a shape outside the VM vocabulary.
    """
    return VM_PRICE_AGGREGATOR(canonical_vm_shape(shape), rates, VM_PRICING_PROJECTION)


def vm_shape_digest(shape: Any) -> str:
    """The digest of a valid VM shape. Refuses one outside the vocabulary."""
    return shape_digest(canonical_vm_shape(shape))


__all__ = [
    "VM_PRICE_AGGREGATOR",
    "VM_PRICING_PROJECTION",
    "CapabilityShapeError",
    "FamilyRate",
    "FlatShape",
    "ShapePrice",
    "ShapeProblem",
    "canonical_vm_shape",
    "flatten_vm_shape",
    "price_vm_shape",
    "vm_family_rate",
    "vm_shape_digest",
    "vm_shape_problems",
]
