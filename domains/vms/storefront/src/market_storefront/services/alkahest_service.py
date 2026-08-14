"""AlkahestService — per-chain AlkahestClient factory.

Builds one ``AlkahestClient`` per configured ``[chains.<name>]`` entry.
Downstream call sites pick the right client by ``chain_name`` (sourced
from the listing's ``accepted_escrows[].chain_name`` or the incoming
escrow's chain).
"""

from __future__ import annotations

import logging
from typing import Any

from market_storefront.utils.config import (
    CHAINS,
    get_evm_wallet_address,
    get_evm_wallet_private_key,
)

logger = logging.getLogger(__name__)


def build_clients() -> dict[str, Any]:
    """Build one ``AlkahestClient`` per chain in ``CHAINS``.

    Returns a dict keyed by chain name. Chains whose client fails to
    initialise (missing key, unreachable RPC, malformed address config)
    are omitted with a warning — the storefront keeps serving the
    chains it can.
    """
    if not CHAINS:
        return {}
    missing = []
    if not get_evm_wallet_address():
        missing.append("wallet.address")
    priv_key = get_evm_wallet_private_key()
    if not priv_key:
        missing.append("wallet.private_key")
    if missing:
        logger.warning(
            "[ALKAHEST] Mechanism unavailable; required EVM settings are missing: %s",
            ", ".join(missing),
        )
        return {}

    from alkahest_py import AlkahestClient
    from market_alkahest.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )

    out: dict[str, Any] = {}
    for name, cc in CHAINS.items():
        try:
            prewarm_alkahest_address_config_cache(cc.alkahest_address_config_path)
            network = get_alkahest_network(name)
            address_config = resolve_alkahest_address_config(
                network, config_path=cc.alkahest_address_config_path
            )
            out[name] = AlkahestClient(
                private_key=priv_key,
                rpc_url=cc.rpc_url,
                address_config=address_config,
            )
            logger.info("[ALKAHEST] Client initialised for chain %s", name)
        except Exception as exc:
            logger.warning(
                "[ALKAHEST] Failed to initialise client for chain %s: %s. "
                "This chain will not be available at runtime.",
                name,
                exc,
            )
    return out
