"""
Auto-registration module for a2a-agent-trader.

Supports both Indexer (via Indexer API) and on-chain (via smart contract) registration.
Registration happens automatically on agent startup when AUTO_REGISTER=true.
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

from .utils.registry.onchain_registration import register_onchain
from .utils.registry.offchain_registration import register_offchain, check_indexer_registration
from .utils.registry.heartbeat_logic import heartbeat_loop, HEARTBEAT_INTERVAL
from .utils.registry.blockchain_utils import build_erc8004_canonical_id

if TYPE_CHECKING:
    from .utils.config import Config

logger = logging.getLogger(__name__)

# Delay before attempting registration (seconds)
# This allows the server to fully start before registration
REGISTRATION_DELAY = 5


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


async def register_agent_on_startup(config: "Config") -> Optional[str]:
    """
    Main registration function called on agent startup.

    Uses wallet address as the primary agent identifier. Ensures idempotent registration
    by checking if the wallet is already registered before attempting registration.

    Args:
        config: Agent configuration object

    Returns:
        Wallet address if registration succeeded, None otherwise
    """
    if not config.auto_register:
        logger.debug("[REGISTRATION] Auto-registration disabled")
        return None

    # Get wallet address - this will be our agent identifier
    wallet_address = config.agent_wallet_address
    if not wallet_address:
        logger.error("[REGISTRATION] No wallet address configured - cannot register agent")
        return None

    # Wait for server to be ready before attempting registration
    logger.info(f"[REGISTRATION] Waiting {REGISTRATION_DELAY}s for server to start...")
    await asyncio.sleep(REGISTRATION_DELAY)

    logger.info(f"[REGISTRATION] Starting registration for wallet: {wallet_address}")

    # Build agent card URL using shared helper
    agent_card_url = build_agent_card_url(config.base_url_override)
    
    # Initialize indexer_agent_id to None
    indexer_agent_id = None
    
    # Attempt on-chain registration if configured
    onchain_agent_id = None
    if (config.agent_priv_key and
        config.chain_rpc_url and
        config.identity_registry_address):

        try:
            # Register on-chain (handles idempotent check internally)
            result = await register_onchain(
                agent_card_url=agent_card_url,
                private_key=config.agent_priv_key,
                rpc_url=config.chain_rpc_url,
                contract_address=config.identity_registry_address,
                owner_address=wallet_address,
                explicit_agent_id=config.onchain_agent_id,
                indexer_url=config.indexer_url
            )
            if result:
                tx_hash, agent_id_from_reg = result
                onchain_agent_id = agent_id_from_reg
                if tx_hash:
                    logger.info(f"[ONCHAIN REGISTRATION] ✓ On-chain registration/update complete. TX: {tx_hash}, Agent ID: {onchain_agent_id}")
                else:
                    logger.info(f"[ONCHAIN REGISTRATION] ✓ Using existing agent ID: {onchain_agent_id} (no changes detected)")
        except Exception as e:
            logger.warning(f"[ONCHAIN REGISTRATION] On-chain registration failed: {e}")
    elif config.identity_registry_address:
        # Contract configured but missing credentials
        missing = []
        if not config.agent_priv_key:
            missing.append("AGENT_PRIV_KEY")
        if not config.chain_rpc_url:
            missing.append("CHAIN_RPC_URL")
        logger.warning(
            f"[ONCHAIN REGISTRATION] On-chain registration skipped. Missing: {', '.join(missing)}"
        )

    # Register with Indexer after on-chain registration (if configured)
    # NOTE: Offchain registration is commented out - relying on event sync instead
    indexer_agent_id = None
    canonical_id = None
    
    # Build canonical ID for heartbeat even if offchain registration is disabled
    if config.indexer_url and onchain_agent_id is not None:
        try:
            # Build ERC-8004 canonical ID: eip155:{chainId}:{identityRegistry}:{agentId}
            # Get chain_id from web3 connection
            if HAS_WEB3:
                try:
                    http_url = config.chain_rpc_url.replace("ws://", "http://").replace("wss://", "https://")
                    w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 10}))
                    chain_id = w3.eth.chain_id
                except Exception as e:
                    logger.warning(f"[REGISTRATION] Could not get chain_id from RPC: {e}, using default")
                    chain_id = 1337  # Default for Anvil/local
            else:
                logger.warning(f"[REGISTRATION] web3 not available, using default chain_id")
                chain_id = 1337  # Default for Anvil/local
            
            # Build canonical ID
            canonical_id = build_erc8004_canonical_id(
                chain_id=chain_id,
                identity_registry=config.identity_registry_address,
                agent_id=onchain_agent_id
            )
            logger.info(f"[REGISTRATION] Built canonical ID: {canonical_id}")
            logger.info(f"[REGISTRATION] Offchain registration disabled - Indexer will discover agent via event sync")

            # Offchain registration commented out - testing event sync
            # indexer_agent_id = await register_offchain(
            #     agent_card_url=agent_card_url,
            #     indexer_url=config.indexer_url,
            #     owner=wallet_address,
            #     agent_id=canonical_id,  # Pass ERC-8004 canonical ID
            #     private_key=config.agent_priv_key,
            #     onchain_agent_id=onchain_agent_id
            # )
            # if indexer_agent_id:
            #     logger.info(f"[OFFCHAIN REGISTRATION] Indexer registration complete. Agent ID: {indexer_agent_id}")
            # else:
            #     logger.warning("[OFFCHAIN REGISTRATION] Indexer registration returned no agent ID")
        except Exception as e:
            logger.warning(f"[REGISTRATION] Error building canonical ID: {e}")

    # Start heartbeat loop if we have an agent ID
    # The heartbeat endpoint accepts canonical IDs, so we can use that even without offchain registration
    # This allows heartbeats to work when testing event sync (offchain registration disabled)
    heartbeat_agent_id = None
    if indexer_agent_id:
        # Use indexer's agent ID if available (from offchain registration)
        heartbeat_agent_id = indexer_agent_id
    elif canonical_id and config.indexer_url:
        # Use canonical ID for heartbeat when offchain registration is disabled (event sync mode)
        heartbeat_agent_id = canonical_id
        logger.info(f"[REGISTRATION] Using canonical ID for heartbeat: {heartbeat_agent_id}")
    
    if heartbeat_agent_id and config.indexer_url:
        asyncio.create_task(heartbeat_loop(heartbeat_agent_id, config.indexer_url, config.agent_priv_key, wallet_address))
        logger.info(f"[REGISTRATION] Started heartbeat loop for agent {heartbeat_agent_id}")

    logger.info(f"[REGISTRATION] Registration complete using wallet address as identifier: {wallet_address}")
    return wallet_address

