"""VM-owned request models for Alkahest settlement routes."""

from core_storefront.models.settle_models import SettleRequest


class VmSettleRequest(SettleRequest):
    """Strict EVM settlement input for VM fulfillment."""

    buyer_evm_address: str
    ssh_public_key: str = ""
    chain_name: str
