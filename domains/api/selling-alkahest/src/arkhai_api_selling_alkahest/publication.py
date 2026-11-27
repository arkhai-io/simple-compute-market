"""What a listing publishes for the Alkahest escrow: its accepted escrows and their release conditions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from market_alkahest import ALKAHEST_CONFIG_KEY, escrow_release_conditions
from market_alkahest.alkahest import get_erc20_escrow_obligation_default

SEED_ESCROW_SETTINGS = frozenset({"chain", "escrow_address", "token", "price_per_token"})
"""The ``[seed]`` keys that state the seeded listing's escrow rather than its listing."""


def accepted_escrow(
    *,
    chain_name: str,
    address_config_path: str | None,
    token: str,
    price_per_token: str,
    escrow_address: str | None = None,
    rate_unit: str = "token",
) -> dict[str, Any]:
    """One accepted escrow paying ``price_per_token`` base units of ``token`` per ``rate_unit``.

    The unit is the domain's word for what one credit buys. Without
    ``escrow_address``, the chain's address book names the ERC-20 escrow
    obligation.
    """
    resolved = escrow_address or get_erc20_escrow_obligation_default(
        chain_name, config_path=address_config_path
    )
    return {
        "chain_name": chain_name,
        "escrow_address": str(resolved).lower(),
        "literal_fields": {"token": token},
        "rates": [{"field": "amount", "per": rate_unit, "value": price_per_token}],
    }


def seed_accepted_escrows(
    seed: Mapping[str, Any],
    chains: Mapping[str, Any],
    address_books: Mapping[str, str | None],
    *,
    rate_unit: str = "token",
) -> list[dict[str, Any]]:
    """The one escrow a ``[seed]`` table's listing accepts, on its configured chain."""
    chain = str(seed.get("chain", "anvil"))
    if chain not in chains:
        raise RuntimeError(f"seed chain {chain!r} is not configured")
    return [
        accepted_escrow(
            chain_name=chain,
            address_config_path=address_books.get(chain),
            token=str(seed["token"]),
            price_per_token=str(seed.get("price_per_token", "1")),
            escrow_address=seed.get("escrow_address"),
            rate_unit=rate_unit,
        )
    ]


def release_conditions(
    settlement_config: Any,
    *,
    chains: Mapping[str, Any],
    wallet_address: str,
    accepted_escrows: Sequence[Mapping[str, Any]],
    readiness: Sequence[Any],
) -> list[dict[str, Any]]:
    """The release conditions a listing publishing ``accepted_escrows`` advertises.

    The Alkahest mechanism's own derivation, over the configured section, the
    seller wallet, and the configured chains: nothing while ``readiness``
    reports Alkahest unready, and otherwise one condition per chain the escrows
    name, refusing a chain this storefront does not configure.
    """
    return escrow_release_conditions(
        settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY),
        accepted_escrows,
        readiness=readiness,
        chains=chains,
        wallet_address=wallet_address,
    )


__all__ = [
    "SEED_ESCROW_SETTINGS",
    "accepted_escrow",
    "release_conditions",
    "seed_accepted_escrows",
]
