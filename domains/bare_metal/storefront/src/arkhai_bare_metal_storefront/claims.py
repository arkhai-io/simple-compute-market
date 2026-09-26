"""The capacity claim a whole-machine bare-metal reservation makes.

A bare-metal listing is held by exclusive allocation of one unit of its
Physical Resource, so the claim requests exactly one ``units``. Its shape's
quantities describe that unit and are not requested; its attributes are, so
admission refuses a declaration that no longer states what the listing
published. They come from the storefront's trusted listing record, carried in
the accepted agreement's fulfillment context, never from buyer input. See
openspec/specs/storefront-publication/spec.md, "A bare-metal listing sells one
whole unit".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_bare_metal import BARE_METAL_OFFERING_MODE, UNITS_DIMENSION


class ClaimAttributesMissing(ValueError):
    """The accepted listing's trusted record names no attribute to claim."""


def whole_machine_claim(
    context: Mapping[str, Any], *, offering_mode: str = BARE_METAL_OFFERING_MODE
) -> dict[str, Any]:
    """One unit, the listing's attributes, and the offering mode.

    The caller adds the Physical Resource or pool the claim selects.
    """
    attributes = context.get("claimed_attributes")
    if not isinstance(attributes, Mapping) or not attributes:
        raise ClaimAttributesMissing(
            "accepted bare-metal listing names no attributes to claim"
        )
    return {
        **{str(name): str(value) for name, value in attributes.items()},
        "dimensions": {UNITS_DIMENSION: 1},
        "offering_mode": offering_mode,
    }


__all__ = ["ClaimAttributesMissing", "whole_machine_claim"]
