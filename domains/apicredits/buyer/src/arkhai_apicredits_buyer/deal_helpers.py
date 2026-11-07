"""API-credit deal recovery over core's mechanism-opaque run-log payloads."""

from core_buyer.deal_helpers import (
    load_deal_context as _core_load_deal_context,
)


from .settlement_composition import buyer_stage


def load_deal_context(run_id: str, **kwargs):
    """Recover a deal and decode its Alkahest settlement enrichments."""
    deal = _core_load_deal_context(run_id, **kwargs)
    buyer_stage(deal.agreement).enrich(deal)
    return deal
