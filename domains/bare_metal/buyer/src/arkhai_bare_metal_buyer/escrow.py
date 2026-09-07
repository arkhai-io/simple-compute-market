"""Buyer-side Alkahest escrow funding for an accepted bare-metal agreement.

Every on-chain primitive here comes from `market_alkahest`: the address-config
resolution, the network lookup, and the per-kind codec that knows how to build
the obligation for the escrow contract the seller advertised. This module only
sequences them for one accepted obligation, so a new escrow kind is supported by
the kit rather than by a change here.

The chain itself is read through `market_config`, the same `[chains.<name>]`
tables every other buyer role reads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from market_config.config_loader import ChainConfig, chains_from_config


class BareMetalEscrowError(RuntimeError):
    """An accepted obligation cannot be funded as described."""


def resolve_buyer_chain(chain_name: str) -> ChainConfig:
    """Return the buyer's configuration for *chain_name*.

    `chains_from_config` drops malformed entries rather than half-loading them,
    so a missing name here means the operator has not configured that chain, not
    that it was configured badly.
    """
    chains = chains_from_config()
    chain = chains.get(chain_name)
    if chain is None:
        raise BareMetalEscrowError(
            f"no [chains.{chain_name}] configuration is available to this buyer"
        )
    if not getattr(chain, "rpc_url", ""):
        raise BareMetalEscrowError(f"chain {chain_name!r} has no rpc_url")
    return chain


def funding_address(private_key: str) -> str:
    """The address a funding key controls.

    Checked against the address the buyer tells the seller to record as payer:
    if they differ the seller records an account that did not fund the escrow,
    and settlement verification looks for a payment from the wrong party.
    """
    from eth_account import Account

    try:
        return str(Account.from_key(private_key).address)
    except Exception as exc:
        raise BareMetalEscrowError("funding key is not a usable EVM key") from exc


def _obligation_parts(obligation: Mapping[str, Any]) -> tuple[str, str, dict, int]:
    if str(obligation.get("mechanism") or "") != "alkahest.v1":
        raise BareMetalEscrowError("accepted obligation is not an Alkahest obligation")
    params = obligation.get("params")
    if not isinstance(params, Mapping):
        raise BareMetalEscrowError("accepted obligation carries no mechanism params")
    chain_name = str(params.get("chain_name") or "")
    escrow_contract = str(params.get("escrow_contract") or "")
    obligation_data = params.get("obligation_data")
    expiration_unix = obligation.get("expiration_unix")
    if not chain_name or not escrow_contract:
        raise BareMetalEscrowError(
            "accepted obligation names no chain or escrow contract"
        )
    if not isinstance(obligation_data, Mapping) or not obligation_data:
        raise BareMetalEscrowError("accepted obligation carries no obligation data")
    if isinstance(expiration_unix, bool) or not isinstance(expiration_unix, int):
        raise BareMetalEscrowError("accepted obligation has no integer expiry")
    return chain_name, escrow_contract, dict(obligation_data), expiration_unix


def fund_accepted_obligation(
    obligation: Mapping[str, Any],
    *,
    private_key: str,
    chain: ChainConfig | None = None,
) -> str:
    """Create the escrow the seller accepted and return its on-chain uid.

    The escrow contract is the one named in the accepted obligation, and the
    codec is looked up from that address rather than assumed, so an escrow kind
    the buyer does not recognise fails here instead of being funded with data
    shaped for a different kind.
    """
    from alkahest_py import AlkahestClient
    from market_alkahest.alkahest import (
        get_alkahest_network,
        get_escrow_kind_codec_by_address,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )

    chain_name, escrow_contract, obligation_data, expiration_unix = _obligation_parts(
        obligation
    )
    resolved = chain if chain is not None else resolve_buyer_chain(chain_name)
    # Read as an attribute, not with a defaulting `getattr`: a misspelled field
    # would otherwise resolve to None and silently fall back to the bundled
    # address set, which points the codec at different deployed contracts than
    # the operator configured.
    address_config_path = resolved.alkahest_address_config_path or None

    prewarm_alkahest_address_config_cache(address_config_path)
    address_config = resolve_alkahest_address_config(
        get_alkahest_network(chain_name),
        config_path=address_config_path,
    )
    client = AlkahestClient(
        private_key=private_key,
        rpc_url=resolved.rpc_url,
        address_config=address_config,
    )
    codec = get_escrow_kind_codec_by_address(
        escrow_contract,
        chain_name,
        config_path=address_config_path,
    )

    async def _create() -> str:
        return await codec.create_obligation(
            client, obligation_data, expiration_unix
        )

    return asyncio.run(_create())


__all__ = [
    "BareMetalEscrowError",
    "fund_accepted_obligation",
    "resolve_buyer_chain",
]
