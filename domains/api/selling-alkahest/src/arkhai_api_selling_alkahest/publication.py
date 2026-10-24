"""What a listing publishes for the Alkahest escrow: its accepted escrows and their release conditions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from market_alkahest import ALKAHEST_CONFIG_KEY, release_conditions as derive_release_conditions
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
) -> dict[str, Any]:
    """One accepted escrow paying ``price_per_token`` per credit in ``token``.

    Without ``escrow_address``, the chain's address book names the ERC-20
    escrow obligation.
    """
    resolved = escrow_address or get_erc20_escrow_obligation_default(
        chain_name, config_path=address_config_path
    )
    return {
        "chain_name": chain_name,
        "escrow_address": str(resolved).lower(),
        "literal_fields": {"token": token},
        "rates": [{"field": "amount", "per": "token", "value": price_per_token}],
    }


def seed_accepted_escrows(
    seed: Mapping[str, Any], chains: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The one escrow a ``[seed]`` table's listing accepts."""
    chain = str(seed.get("chain", "anvil"))
    chain_cfg = chains.get(chain)
    if chain_cfg is None:
        raise RuntimeError(f"seed chain {chain!r} is not configured")
    return [
        accepted_escrow(
            chain_name=chain,
            address_config_path=chain_cfg.alkahest_address_config_path,
            token=str(seed["token"]),
            price_per_token=str(seed.get("price_per_token", "1")),
            escrow_address=seed.get("escrow_address"),
        )
    ]


def release_conditions(
    settlement_config: Any,
    *,
    chains: Mapping[str, Any],
    wallet_address: str,
    accepted_escrows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The release conditions a listing publishing ``accepted_escrows`` advertises.

    Each escrow's chain gets the condition the Alkahest mechanism derives from
    the configured section, the seller wallet, and that chain's address book.
    An escrow on a chain the storefront does not configure is refused, since
    nothing could settle it. An unset wallet still derives a condition, with no
    recipient; materialization refuses every deal under it as unreadable.
    """
    chain_names = {str(escrow["chain_name"]) for escrow in accepted_escrows}
    if not chain_names:
        return []
    unconfigured = sorted(name for name in chain_names if name not in chains)
    if unconfigured:
        raise ValueError(
            f"accepted escrow names chain {unconfigured[0]!r}, which this "
            "storefront does not configure under [chains]"
        )
    return derive_release_conditions(
        settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY),
        chain_names=chain_names,
        chains=chains,
        wallet_address=wallet_address,
    )


__all__ = [
    "SEED_ESCROW_SETTINGS",
    "accepted_escrow",
    "release_conditions",
    "seed_accepted_escrows",
]
