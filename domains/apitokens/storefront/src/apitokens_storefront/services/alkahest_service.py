"""AlkahestService — per-chain AlkahestClient factory.

Same shape as the VM storefront's: one ``AlkahestClient`` per
configured ``[chains.<name>]`` entry, keyed by chain name; chains whose
client fails to initialise are omitted with a warning.
"""

from __future__ import annotations

import logging
from typing import Any

from apitokens_storefront.utils.config import CHAINS, settings

logger = logging.getLogger(__name__)


def build_clients() -> dict[str, Any]:
    priv_key = (settings.wallet.private_key or "").strip()
    if not priv_key:
        logger.warning(
            "[ALKAHEST] wallet.private_key not set; no chain clients will "
            "be initialised."
        )
        return {}
    if not CHAINS:
        logger.warning(
            "[ALKAHEST] no [chains.<name>] tables configured; nothing to build."
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
                "This chain will not be available at runtime.", name, exc,
            )
    return out
