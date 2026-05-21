"""AlkahestService — factory for the AlkahestClient singleton.

Wraps all alkahest client initialisation so the logic lives in one
testable place and is kept out of the container and server modules.
"""
from __future__ import annotations

import logging

from market_storefront.utils.config import settings

logger = logging.getLogger(__name__)


def build_client():
    """Build and return an AlkahestClient, or None if keys are not configured.

    Returns
    -------
    AlkahestClient | None
    """
    priv_key = (settings.wallet.private_key or "").strip()
    rpc_url = (settings.chain.rpc_url or "").strip()
    if not priv_key or not rpc_url:
        logger.debug("[ALKAHEST] wallet.private_key or chain.rpc_url not set; skipping client init.")
        return None
    alkahest_path = settings.chain.alkahest_address_config_path
    chain_name = settings.chain.name
    try:
        from alkahest_py import AlkahestClient
        from service.clients.alkahest import (
            get_alkahest_network,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
        )

        prewarm_alkahest_address_config_cache(alkahest_path)
        network = get_alkahest_network(chain_name)
        address_config = resolve_alkahest_address_config(
            network, config_path=alkahest_path
        )
        client = AlkahestClient(
            private_key=priv_key,
            rpc_url=rpc_url,
            address_config=address_config,
        )
        logger.info("[ALKAHEST] Client initialized on network=%s", network)
        return client
    except Exception as exc:
        logger.warning("[ALKAHEST] Failed to initialize client: %s. Continuing without.", exc)
        return None
