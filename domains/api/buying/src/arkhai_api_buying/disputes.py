"""The buyer's dispute authorities, resolved per registry for selection and approval."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.registry_config import (
    registry_descriptors, resolve_indexer_urls, resolve_registry_authorities,
)
from market_deal_lifecycle.configuration import (
    DisputeEntry, authorities_by_registry, dispute_config,
)


def buyer_dispute_authorities(
    document: Mapping[str, Any], identity: ResolvedBuyerIdentity | None,
    urls: Sequence[str],
) -> dict[str, tuple[DisputeEntry, ...]]:
    config = dispute_config(document, role="buyer")
    descriptors = (
        registry_descriptors(
            signer=identity.signer, urls=list(urls),
            authorities=resolve_registry_authorities(resolve_indexer_urls()),
        )
        if identity is not None and config.use_registry_dispute_authorities else {}
    )
    return authorities_by_registry(
        config,
        {url: descriptor.recommended_dispute_authorities or [] if descriptor else []
         for url, descriptor in descriptors.items()},
        role="buyer", report=logging.getLogger(__name__).warning if identity else lambda _: None,
    )
