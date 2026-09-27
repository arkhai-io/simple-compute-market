"""VM-owned request models for Alkahest settlement routes."""

from core_storefront.models.settle_models import SettleRequest


class VmSettleRequest(SettleRequest):
    """Strict EVM settlement input for VM fulfillment.

    Settlement names the accepted negotiation and adds only what negotiation did
    not settle: the buyer's EVM settlement-effect address. The SSH key and the
    chain are negotiated terms, read from the accepted negotiation; a request
    restating them is refused as an unknown field.
    """

    buyer_evm_address: str
