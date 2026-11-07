"""Contact exchange composed into the VM storefront.

The mechanism's accepted-state interpretation, persistence, retention, and
reveal belong to the contact-exchange kit, and seller-side delivery to the
delivery kit. What this module supplies is the VM storefront's half: its
negotiation and obligation reads, the origin its negotiation bindings record,
its configured sites as the known origins, its ``[Delivery]`` section, and its
signer.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any

from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_contact_exchange import (
    CONTACT_CONFIG_KEY,
    ContactExchangeComposition,
    ContactSettlementConfig,
    SQLiteIntroductionStore,
)
from market_delivery import (
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
    load_delivery_config,
)
from market_identity import Signer

from market_storefront.utils import config as storefront_config

logger = logging.getLogger(__name__)


def _negotiation_origin(sqlite_client: Any):
    async def load_origin(negotiation_id: str) -> str | None:
        """The site recorded on the negotiation's binding, or None if unbound."""
        try:
            binding = await sqlite_client.load_thread_binding(negotiation_id=negotiation_id)
        except (KeyError, ValueError):
            return None
        return binding.site_id

    return load_origin


def build_vm_introduction_delivery(
    *,
    known_origins: Collection[str],
    signer: Signer,
) -> SellerIntroductionDelivery | None:
    """The storefront's seller-side delivery from its ``[Delivery]`` section."""

    return build_seller_introduction_delivery(
        load_delivery_config(storefront_config.delivery_config_mapping(), role="seller"),
        known_origins=known_origins,
        signer=signer,
        logger=logger,
    )


def build_vm_contact_exchange(
    *,
    sqlite_client: Any,
    settlement_composition: Any,
    known_origins: Collection[str],
    delivery: SellerIntroductionDelivery | None,
) -> ContactExchangeComposition:
    """Compose contact exchange over this storefront's state and configuration."""

    def config() -> ContactSettlementConfig | None:
        settlement = settlement_composition.settlement_config
        if CONTACT_MECHANISM not in settlement.priority:
            return None
        section = settlement.mechanism_config(CONTACT_CONFIG_KEY)
        return section if isinstance(section, ContactSettlementConfig) else None

    return ContactExchangeComposition(
        config=config,
        store=SQLiteIntroductionStore(sqlite_client.db_path),
        load_thread=sqlite_client.load_negotiation_thread_row,
        load_obligation=settlement_composition.repository.load_settlement_obligation,
        load_origin=_negotiation_origin(sqlite_client),
        settlement_runtime=settlement_composition.runtime,
        known_origins=known_origins,
        deliver=delivery,
    )


__all__ = ["build_vm_contact_exchange", "build_vm_introduction_delivery"]
