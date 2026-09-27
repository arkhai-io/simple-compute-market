"""A bare-metal listing's shape, read from its Physical Resource's declaration.

A bare-metal seller sells one whole machine, so there is no shape to choose:
the listing's shape is what the declaration admission matches says the machine
contains. Quantities are the declared capacity dimensions other than ``units``;
attributes are the declared attributes the compute-family schema names, and no
other attribute is shape input — ``physical_host_id``, ``allocation_mode``, and
the like are the site's accounting facts. ``units`` is the machine itself: a
bare-metal claim reserves exactly one, exclusively, and the shape describes
what that one unit contains. See openspec/specs/storefront-publication/spec.md,
"A bare-metal listing's shape is derived from its declaration" and "A
bare-metal listing sells one whole unit".
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from arkhai_compute import COMPUTE_CAPABILITY_SCHEMA
from market_capability_shape import CapabilityShapeError, FieldKind, unflatten_shape

#: The whole-machine dimension a bare-metal claim reserves.
UNITS_DIMENSION = "units"


class BareMetalShapeError(ValueError):
    """A declaration that does not read as a bare-metal shape, with every reason."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def _integral(value: Any) -> int | None:
    """``value`` as an integer when it is one, whatever numeric type carried it."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def derive_bare_metal_shape(
    declared_capacity: Mapping[str, Any],
    declared_attributes: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """The family-grouped shape a declaration states, or ``BareMetalShapeError``.

    Refuses, naming each reason: a ``units`` dimension other than exactly one; a
    capacity dimension the compute schema does not define; a quantity that is
    not a positive integer; and a missing GPU count or model.
    """
    problems: list[str] = []
    units = _integral(declared_capacity.get(UNITS_DIMENSION))
    if units != 1:
        problems.append(
            f"capacity.{UNITS_DIMENSION}: a whole machine declares exactly one, "
            f"not {declared_capacity.get(UNITS_DIMENSION)!r}"
        )
    quantities: dict[str, Any] = {}
    for name, raw in declared_capacity.items():
        if name == UNITS_DIMENSION:
            continue
        value = _integral(raw)
        quantities[name] = raw if value is None else value
    attributes = {
        name: declared_attributes[name]
        for name in COMPUTE_CAPABILITY_SCHEMA.flat_names(FieldKind.ATTRIBUTE)
        if name in declared_attributes
    }
    try:
        shape = unflatten_shape(quantities, attributes, COMPUTE_CAPABILITY_SCHEMA)
    except CapabilityShapeError as exc:
        problems.extend(str(problem) for problem in exc.problems)
        shape = {}
    if problems:
        raise BareMetalShapeError(tuple(problems))
    return shape


__all__ = ["UNITS_DIMENSION", "BareMetalShapeError", "derive_bare_metal_shape"]
