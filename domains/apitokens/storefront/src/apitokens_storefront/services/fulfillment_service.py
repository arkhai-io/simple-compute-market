"""Token fulfillment orchestration for settled escrows.

Binds the concept module's ``fulfill_api_tokens_obligation`` to this
process's parts: settings, the capacity-hold lookup placed at
acceptance, and the configured failure policy.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.apitokens.settlement import fulfill_api_tokens_obligation

from apitokens_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)


async def _apply_fulfillment_failure_policy_adapter(
    *,
    allocation_id: str | None,
    escrow_uid: str,
    listing_id: str | None,
    resource_id: str | None,
    reason: str,
    message: str,
    source: str,
) -> None:
    from apitokens_storefront.services.capacity_client import build_capacity_client
    from apitokens_storefront.utils.failure_policy import (
        FulfillmentFailureContext,
        apply_fulfillment_failure_policy,
    )

    await apply_fulfillment_failure_policy(
        get_sqlite_client(),
        FulfillmentFailureContext(
            allocation_id=allocation_id,
            escrow_uid=escrow_uid,
            listing_id=listing_id,
            resource_id=resource_id,
            reason=reason,
            message=message,
            source=source,
        ),
        capacity=build_capacity_client(lambda: get_sqlite_client()),
    )


async def fulfill_token_obligation(
    *,
    client: Any | None,
    escrow_uid: str,
    order: dict[str, Any],
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
    buyer_wallet: str | None = None,
    listing_id: str | None = None,
    negotiation_id: str | None = None,
) -> dict[str, Any]:
    """Issue credits for a settled escrow and fulfill the obligation.

    When the negotiation's acceptance placed a TTL quota hold (two-phase
    reserve), its allocation_id rides the issuance call — the tokens
    service commits that hold open-ended instead of racing a fresh
    reserve. Consume-once: the hold row's job is done either way.
    """
    from core_storefront.stage_log import stage_event
    from domains.apitokens.listings.models import coerce_resource_dict

    from apitokens_storefront.utils import config

    held_allocation: dict | None = None
    if negotiation_id:
        db = get_sqlite_client()
        hold = await db.load_capacity_hold(negotiation_id=negotiation_id)
        if hold:
            held_allocation = dict(hold.get("payload") or {})
            held_allocation.setdefault("allocation_id", hold.get("allocation_id"))
            await db.delete_capacity_hold(negotiation_id=negotiation_id)

    return await fulfill_api_tokens_obligation(
        client=client,
        escrow_uid=escrow_uid,
        offer_resource=coerce_resource_dict(order.get("offer_resource")),
        quantity=quantity,
        key_mode=key_mode,
        key_id=key_id,
        buyer_wallet=buyer_wallet,
        listing_id=listing_id,
        service_url=config.tokens_service_url(),
        admin_key=config.tokens_admin_key(),
        stage_event=stage_event,
        apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
        held_allocation=held_allocation,
    )
