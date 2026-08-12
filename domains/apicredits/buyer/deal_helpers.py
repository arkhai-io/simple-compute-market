"""API-credit deal recovery over core's mechanism-opaque run-log payloads."""

from core_buyer.deal_helpers import (
    load_deal_context as _core_load_deal_context,
)


def load_deal_context(run_id: str, **kwargs):
    """Recover a deal and decode its Alkahest settlement enrichments."""
    deal = _core_load_deal_context(run_id, **kwargs)
    if deal.accepted_escrow_proposal is not None:
        from market_alkahest.schemas import (
            accepted_recipient_address,
            accepted_token_address,
        )

        recipient = accepted_recipient_address(deal.accepted_escrow_proposal)
        if recipient:
            deal.seller_wallet_address = recipient
        token = accepted_token_address(deal.accepted_escrow_proposal)
        if token:
            deal.token_contract = token
    if deal.settlement_plan is not None and not deal.accepted_escrow_terms:
        from market_alkahest.plans import escrow_terms_from_settlement_plan

        deal.accepted_escrow_terms = [
            terms.model_dump()
            for terms in escrow_terms_from_settlement_plan(deal.settlement_plan)
        ]
    return deal
