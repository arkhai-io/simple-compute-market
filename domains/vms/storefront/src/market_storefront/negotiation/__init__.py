"""Storefront-side VM negotiation machinery.

The per-round seller hook and its chain assembly. Both read storefront-local
listing and settlement state, so they stay with the storefront rather than moving
to the distribution both roles share.

The policies themselves — the guards a chain names, and the reinforcement-learning
strategy — are reached by both roles and live in ``arkhai_vms.negotiation``.
"""

from market_storefront.negotiation.storefront_round import (
    SellerRoundHook,
    SellerRoundResult,
    default_seller_round_hook,
)

__all__ = [
    "SellerRoundHook",
    "SellerRoundResult",
    "default_seller_round_hook",
]
