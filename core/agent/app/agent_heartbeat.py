"""
Agent heartbeat setup. Requires ONCHAIN_AGENT_ID from `make register`.
"""
import asyncio
import logging
from typing import Optional, TYPE_CHECKING

try:
    from web3 import Web3
    from web3.providers import HTTPProvider
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

from .utils.registry.heartbeat_logic import heartbeat_loop
from .utils.registry.blockchain_utils import build_erc8004_canonical_id, rpc_url_for_http_provider

if TYPE_CHECKING:
    from .utils.config import Config

logger = logging.getLogger(__name__)

# Delay before starting heartbeat (seconds)
# This allows the server to fully start before heartbeat begins
HEARTBEAT_DELAY = 5


async def start_agent_heartbeat(config: "Config") -> Optional[str]:
    """
    Start agent heartbeat loop. Requires ONCHAIN_AGENT_ID from `make register`.
    """
    if not config.indexer_url or not config.identity_registry_address:
        return None

    if not config.agent_wallet_address:
        logger.error("[HEARTBEAT] No wallet address configured")
        return None

    if not config.onchain_agent_id:
        logger.warning("[HEARTBEAT] ONCHAIN_AGENT_ID not set. Run 'make register' first.")
        return None

    # Parse agent ID
    try:
        agent_id = int(config.onchain_agent_id)
    except ValueError:
        logger.error(f"[HEARTBEAT] Invalid ONCHAIN_AGENT_ID: {config.onchain_agent_id}")
        return None

    # Wait for server to be ready
    await asyncio.sleep(HEARTBEAT_DELAY)

    # Get chain_id (from env, RPC, or default)
    chain_id = 1337  # Default
    if HAS_WEB3 and config.chain_rpc_url:
        try:
            http_url = rpc_url_for_http_provider(config.chain_rpc_url)
            w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 5}))
            chain_id = w3.eth.chain_id
        except Exception:
            pass  # Use default

    # Build canonical ID and start heartbeat
    canonical_id = build_erc8004_canonical_id(
        chain_id=chain_id,
        identity_registry=config.identity_registry_address,
        agent_id=agent_id
    )
    
    asyncio.create_task(heartbeat_loop(canonical_id, config.indexer_url, config.agent_priv_key, config.agent_wallet_address))
    logger.info(f"[HEARTBEAT] Started heartbeat for {canonical_id}")
    
    return config.agent_wallet_address
