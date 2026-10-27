"""The API-credits settle request: the family's, under the component name this storefront serves."""

from __future__ import annotations

from arkhai_api_selling.route_services import QuotaSettleRequest


class ApiCreditsSettleRequest(QuotaSettleRequest):
    """Settlement input for Alkahest or payments by negotiation ID."""
