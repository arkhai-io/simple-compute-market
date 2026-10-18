"""The bare-metal storefront's seller-side delivery, from its ``[Delivery]`` section.

Seller-side delivery itself -- routing by origin, dispatch off the request
path, and re-delivery -- is the delivery kit's. The section is the one every
side states, read from the storefront's configuration files, so only building
it over this storefront's sites and signer is the storefront's own.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from typing import Any

from market_delivery import (
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
    load_delivery_config,
)
from market_identity import Signer

logger = logging.getLogger(__name__)


def storefront_introduction_delivery(
    section: Mapping[str, Any] | None,
    *,
    known_origins: Collection[str],
    signer: Signer,
) -> SellerIntroductionDelivery | None:
    """Build this storefront's seller-side delivery, failing at startup on a mistake.

    ``section`` is the configured ``[Delivery]`` table, or None when there is none.
    """

    return build_seller_introduction_delivery(
        load_delivery_config(section, role="seller"),
        known_origins=known_origins,
        signer=signer,
        logger=logger,
    )


__all__ = ["storefront_introduction_delivery"]
