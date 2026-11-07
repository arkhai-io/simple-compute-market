"""Strict API-credit settlement request models."""

from __future__ import annotations

from core_storefront.models.settle_models import SettleRequest


class ApiCreditsSettleRequest(SettleRequest):
    """Settlement input for Alkahest or payments by negotiation ID."""

    buyer_evm_address: str | None = None
    chain_name: str | None = None
    settlement_mechanism: str | None = None
