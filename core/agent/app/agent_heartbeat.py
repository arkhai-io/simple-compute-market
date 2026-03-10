# DEPRECATED — kept for backward compat. Import from service.clients.erc8004.heartbeat directly.
from service.clients.erc8004.heartbeat import (  # noqa: F401
    HEARTBEAT_INTERVAL,
    HEARTBEAT_DELAY,
    send_heartbeat,
    heartbeat_loop,
    start_agent_heartbeat as _start_agent_heartbeat,
)
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .utils.config import Config


async def start_agent_heartbeat(config: "Config") -> Optional[str]:
    """Backward-compat wrapper: accepts Config, converts to dict for service layer."""
    return await _start_agent_heartbeat({
        "indexer_url": config.indexer_url,
        "identity_registry_address": config.identity_registry_address,
        "agent_wallet_address": config.agent_wallet_address,
        "onchain_agent_id": config.onchain_agent_id,
        "chain_rpc_url": config.chain_rpc_url,
        "agent_priv_key": config.agent_priv_key,
    })
