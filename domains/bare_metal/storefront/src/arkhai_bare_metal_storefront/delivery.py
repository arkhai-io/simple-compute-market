"""The bare-metal storefront's seller-side delivery, from its ``[Delivery]`` section.

Seller-side delivery itself -- routing by origin, dispatch off the request
path, and re-delivery -- is the delivery kit's. The section is the one every
side states, read from the storefront's configuration files, so only building
it over this storefront's sites and signer is the storefront's own.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from functools import partial
from collections.abc import Collection, Mapping
from typing import Any

from market_delivery import (
    SellerIntroductionDelivery,
    build_seller_introduction_delivery,
    load_delivery_config,
)
from market_identity import Signer
from market_contact_exchange.delivery_runtime import ContactDeliveryWorker
from market_contact_exchange.introduction_routes import introduction_projection
from market_delivery import introduction_delivery_event
from market_delivery import send_bounded_smtp

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


def _owns_contact_attempt(db_path: str, intent_id: str, attempt_id: str) -> bool:
    with sqlite3.connect(db_path, timeout=1) as conn:
        return conn.execute(
            "SELECT 1 FROM contact_delivery_intents WHERE intent_id=? AND attempt_id=? AND status='sending'",
            (intent_id, attempt_id),
        ).fetchone() is not None


def explicit_contact_delivery_worker(runtime: Any) -> ContactDeliveryWorker | None:
    """Deliver only immutable recipient-owned intents after successful completion."""
    exchange = runtime.contact_exchange
    if not exchange.explicit_delivery_configured():
        return None

    async def send(record: Any, role: str, route: dict[str, str], intent_id: str, attempt_id: str, deadline: float) -> tuple[str, str | None]:
        agreement = await exchange.prepare_delivery(record.agreement_ref, record.obligation_ref)
        config = exchange.delivery_config(agreement)
        if config is None:
            return "failed", "configuration_unavailable"
        event = introduction_delivery_event(
            introduction_projection(record, for_role=role), role=role,
            agreement_ref=record.agreement_ref,
            counterparty=agreement.seller_principal if role == "buyer" else agreement.buyer_principal,
        )
        return await asyncio.to_thread(
            send_bounded_smtp, config.smtp.model_dump(mode="json"), route["address"],
            event.rendered, record.obligation_ref, intent_id, deadline=deadline,
            before_data=partial(_owns_contact_attempt, runtime.db.db_path, intent_id, attempt_id),
        )

    return ContactDeliveryWorker(
        transaction=exchange.store.transaction, prepare=exchange.prepare_delivery,
        complete=exchange.complete_delivery, send=send,
    )
