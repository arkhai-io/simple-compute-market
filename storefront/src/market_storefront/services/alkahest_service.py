"""AlkahestService — factory for the AlkahestClient singleton.

Wraps all alkahest client initialisation so the logic lives in one
testable place and is kept out of the container and server modules.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_client(config):
    """Build and return an AlkahestClient, or None if keys are not configured.

    Parameters
    ----------
    config:
        The storefront CONFIG singleton.

    Returns
    -------
    AlkahestClient | None
    """
    priv_key = (config.agent_priv_key or "").strip()
    rpc_url = (config.chain_rpc_url or "").strip()
    if not priv_key or not rpc_url:
        logger.debug("[ALKAHEST] AGENT_PRIV_KEY or CHAIN_RPC_URL not set; skipping client init.")
        return None
    try:
        from alkahest_py import AlkahestClient
        from service.clients.alkahest import (
            get_alkahest_network,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
        )

        prewarm_alkahest_address_config_cache(config.alkahest_address_config_path)
        network = get_alkahest_network(config.chain_name)
        address_config = resolve_alkahest_address_config(
            network, config_path=config.alkahest_address_config_path
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
