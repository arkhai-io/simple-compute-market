"""The bare-metal storefront's carrier for its ``[Delivery]`` section.

Seller-side delivery itself -- routing by origin, dispatch off the request
path, and re-delivery -- is the delivery kit's. This storefront is configured
by environment, the way its settlement section arrives, so only the carrier is
its own; the section shape is the one every side uses.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Collection, Mapping
from typing import Any

from market_delivery import (
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
    load_delivery_config,
)
from market_identity import Signer

logger = logging.getLogger(__name__)

DELIVERY_ENVIRONMENT_VARIABLE = "BARE_METAL_STOREFRONT_DELIVERY"


def storefront_delivery_section() -> Mapping[str, Any] | None:
    """Read the ``[Delivery]`` section from this storefront's environment."""

    raw = os.environ.get(DELIVERY_ENVIRONMENT_VARIABLE, "").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, Mapping):
        raise TypeError("delivery configuration must be a JSON object")
    return parsed


def storefront_introduction_delivery(
    *,
    known_origins: Collection[str],
    signer: Signer,
) -> SellerIntroductionDelivery | None:
    """Build this storefront's seller-side delivery, failing at startup on a mistake."""

    return build_seller_introduction_delivery(
        load_delivery_config(storefront_delivery_section(), role="seller"),
        known_origins=known_origins,
        signer=signer,
        logger=logger,
    )


__all__ = [
    "DELIVERY_ENVIRONMENT_VARIABLE",
    "storefront_delivery_section",
    "storefront_introduction_delivery",
]
