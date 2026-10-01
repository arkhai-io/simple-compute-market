"""Strict API-credit Alkahest settlement models."""

from __future__ import annotations

from core_storefront.models.settle_models import SettleRequest


class ApiCreditsSettleRequest(SettleRequest):
    """Strict EVM settlement input for API-credit issuance."""

    buyer_evm_address: str
    chain_name: str
