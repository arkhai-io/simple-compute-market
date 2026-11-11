"""The capacity shape a VM buyer opens a negotiation with.

A buyer states the quantities it wants as a round-zero ``compute_resource``;
the seller fills every dimension the buyer omits from its listing. A seller
refuses a shape larger than its listing advertises on any quantity until it
can probe whether a larger shape fits, so the buyer refuses one first rather
than open a negotiation that cannot agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import typer
from arkhai_vms import DIMENSION_KEYS
from arkhai_vms_listings import extract_compute_from_order

SHAPE_OPTION = "--shape"
SHAPE_HELP = (
    "Capacity to open the negotiation with, as comma-separated quantities, "
    "for example 'gpu_count=1,vcpu_count=8,ram_gb=64'. Quantities are "
    f"{', '.join(DIMENSION_KEYS)}; an omitted one is the listing's own. "
    "Each must be a positive whole number no larger than the listing "
    "advertises. Resumed runs reuse the shape their negotiation opened with."
)


def parse_shape_option(raw: str | None) -> dict[str, int] | None:
    """The quantities a ``--shape`` value states, or ``None`` when it is absent."""
    if raw is None:
        return None
    shape: dict[str, int] = {}
    for item in raw.split(","):
        name, separator, value = (part.strip() for part in item.partition("="))
        if not separator or not name or not value:
            raise typer.BadParameter(
                f"{item.strip()!r} is not a quantity=value pair", param_hint=SHAPE_OPTION
            )
        if name not in DIMENSION_KEYS:
            raise typer.BadParameter(
                f"{name!r} is not a capacity quantity; expected one of "
                f"{', '.join(DIMENSION_KEYS)}",
                param_hint=SHAPE_OPTION,
            )
        if name in shape:
            raise typer.BadParameter(f"{name} is stated twice", param_hint=SHAPE_OPTION)
        if not (value.isascii() and value.isdigit()) or int(value) <= 0:
            raise typer.BadParameter(
                f"{name} must be a positive whole number, not {value!r}",
                param_hint=SHAPE_OPTION,
            )
        shape[name] = int(value)
    return shape


def shape_excess(shape: Mapping[str, int], listing: Mapping[str, Any]) -> tuple[str, ...]:
    """Each quantity of ``shape`` above what ``listing`` advertises; empty when none is.

    A quantity the listing does not state is advertised as zero, so a GPU count
    asked of a listing without GPUs exceeds it.
    """
    try:
        advertised = extract_compute_from_order(dict(listing))
    except ValueError:
        return ("the listing advertises no compute shape",)
    return tuple(
        f"{name} {value} exceeds the advertised {advertised.get(name) or 0}"
        for name, value in shape.items()
        if value > (advertised.get(name) or 0)
    )
