"""Scheme-agnostic settlement affordances.

Exposes the storefront's settlement wallet so peers can verify they're
about to settle to the expected EVM address. This is the only
identity-related endpoint that survived the pluggable-identity refactor —
the ERC-8004 registration file and the A2A agent card were both deleted
in Phase 4 along with the rest of the ERC-8004 machinery.
"""

from __future__ import annotations

from fastapi import APIRouter

from market_storefront.utils.config import settings

router = APIRouter()


@router.get(
    "/.well-known/agent-wallet.json",
    summary="Storefront's settlement wallet address",
)
def agent_wallet() -> dict[str, str]:
    """Return the storefront's settlement wallet.

    Peers fetch this before settling on-chain to confirm the address
    they're about to send a payment-bound demand to matches the seller
    they negotiated with.
    """
    return {"agent_wallet_address": settings.wallet.address or ""}
