"""
Agent heartbeat setup. Requires ONCHAIN_AGENT_ID from `make register-onchain`.
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
from .utils.registry.blockchain_utils import build_erc8004_canonical_id

if TYPE_CHECKING:
    from .utils.config import Config

logger = logging.getLogger(__name__)

# Delay before starting heartbeat (seconds)
# This allows the server to fully start before heartbeat begins
HEARTBEAT_DELAY = 5


def build_agent_card_url(base_url: str) -> str:
    """
    Build the agent card URL (token_uri) consistently.
    
    Args:
        base_url: Base URL of the agent (e.g., http://localhost:8000)
    
    Returns:
        Agent card URL (e.g., http://localhost:8000/.well-known/agent-card.json)
    """
    return f"{base_url.rstrip('/')}/.well-known/agent-card.json"


def build_erc8004_metadata_json(
    agent_card_data: dict,
    labels: Optional[dict] = None,
    onchain_agent_id: Optional[int] = None,
    chain_id: Optional[int] = None,
    identity_registry: Optional[str] = None
) -> dict:
    """
    Build full ERC-8004 registration file JSON from agent card data.
    
    This ensures consistency between on-chain and off-chain metadata and compliance with ERC-8004 spec.
    
    Args:
        agent_card_data: Agent card JSON data (from /.well-known/agent-card.json)
        labels: Optional labels/metadata (e.g., {"category": "compute", "type": "trader"})
        onchain_agent_id: Optional on-chain numeric agent ID (if registered on-chain)
        chain_id: Optional chain ID for registrations array
        identity_registry: Optional registry address for registrations array
    
    Returns:
        Full ERC-8004 registration file JSON with all required fields:
        - type (MUST): "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
        - name, description (MUST)
        - endpoints (MUST): Array matching spec format
        - registrations (MUST): Array with {agentId, agentRegistry} if onchain_agent_id provided
        - supportedTrust (OPTIONAL)
    """
    # Build endpoints array matching ERC-8004 spec format
    endpoints = []
    if "url" in agent_card_data:
        # A2A endpoint
        endpoint_obj = {
            "name": "A2A",
            "endpoint": agent_card_data["url"],
            "version": agent_card_data.get("version", "0.1.0"),
        }
        # Add capabilities if available (for MCP endpoints)
        if agent_card_data.get("capabilities"):
            endpoint_obj["capabilities"] = agent_card_data["capabilities"]
        endpoints.append(endpoint_obj)
    
    # Build registrations array if we have on-chain registration info
    registrations = []
    if onchain_agent_id is not None and chain_id is not None and identity_registry:
        registrations.append({
            "agentId": onchain_agent_id,
            "agentRegistry": f"eip155:{chain_id}:{identity_registry}"
        })
    
    # Build full ERC-8004 registration file JSON
    registration_file = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",  # MUST field
        "name": agent_card_data.get("name", "A2A Agent"),  # MUST field
        "description": agent_card_data.get("description", ""),  # MUST field
        "endpoints": endpoints,  # MUST field
        "supportedTrust": agent_card_data.get("supportedTrust", ["reputation"]),  # OPTIONAL
    }
    
    # Add image if available (OPTIONAL)
    if agent_card_data.get("image"):
        registration_file["image"] = agent_card_data["image"]
    
    # Add registrations array if we have on-chain info (MUST when agent is registered)
    if registrations:
        registration_file["registrations"] = registrations
    
    # Add active field (not in spec but useful for our metadata)
    registration_file["active"] = agent_card_data.get("active", True)
    
    # Add category and type from labels (for our internal metadata, not in spec)
    if labels:
        if "category" in labels:
            registration_file["category"] = labels["category"]
        if "type" in labels:
            registration_file["type"] = labels["type"]
    
    # Add on-chain agent ID in metadata (for internal use, not in spec registration file)
    if onchain_agent_id is not None:
        registration_file["onChainAgentId"] = onchain_agent_id
    
    # Add any additional labels (excluding category and type which are already handled)
    if labels:
        for k, v in labels.items():
            if k not in ["category", "type"]:
                registration_file[k] = v
    
    return registration_file


async def start_agent_heartbeat(config: "Config") -> Optional[str]:
    """
    Start agent heartbeat loop. Requires ONCHAIN_AGENT_ID from `make register-onchain`.
    """
    if not config.auto_register or not config.indexer_url or not config.identity_registry_address:
        return None

    if not config.agent_wallet_address:
        logger.error("[HEARTBEAT] No wallet address configured")
        return None

    if not config.onchain_agent_id:
        logger.warning("[HEARTBEAT] ONCHAIN_AGENT_ID not set. Run 'make register-onchain' first.")
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
            http_url = config.chain_rpc_url.replace("ws://", "http://").replace("wss://", "https://")
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

