"""Deal recovery over core's mechanism-opaque run-log payloads."""

from typing import Any

from core_buyer.deal_helpers import load_deal_context as _core_load_deal_context

from arkhai_api_buying.settlement_composition import BuyerSettlementComposition


def load_deal_context(settlement: BuyerSettlementComposition, run_id: str, **kwargs: Any):
    """Recover a deal and let its accepted mechanism's stage decode its enrichments."""
    deal = _core_load_deal_context(run_id, **kwargs)
    settlement.stage(deal.agreement).enrich(deal)
    return deal
