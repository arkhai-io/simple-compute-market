"""
Off-chain registration logic for ERC-8004 Indexer API.
"""
import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

# Try to use aiohttp for async HTTP, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from .blockchain_utils import build_erc8004_canonical_id

logger = logging.getLogger(__name__)


async def query_indexer_for_agent(indexer_url: str, agent_id: str) -> Optional[dict]:
    """Query Indexer API to check if agent exists"""
    try:
        if HAS_AIOHTTP:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{indexer_url.rstrip('/')}/agents/{agent_id}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return await response.json()
        else:
            req = urllib.request.Request(f"{indexer_url.rstrip('/')}/agents/{agent_id}", method='GET')
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.debug(f"[REGISTRATION] Could not query Indexer for agent {agent_id}: {e}")
        return None


async def check_indexer_registration(wallet_address: str, indexer_url: str) -> Optional[str]:
    """
    Check if a wallet address is already registered with the Indexer.

    Args:
        wallet_address: The wallet address to check
        indexer_url: URL of the Indexer API

    Returns:
        Agent ID if found, None otherwise
    """
    try:
        # Query the Indexer API for agents by owner
        if HAS_AIOHTTP:
            async with aiohttp.ClientSession() as session:
                url = f"{indexer_url.rstrip('/')}/agents"
                params = {"owner": wallet_address}
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Check if any agents returned for this owner
                        if data and isinstance(data, list) and len(data) > 0:
                            # Return the first agent ID found
                            agent = data[0]
                            return agent.get("id") or agent.get("agentId")
        else:
            # Fallback to sync method
            url = f"{indexer_url.rstrip('/')}/agents?owner={urllib.parse.quote(wallet_address)}"
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data and isinstance(data, list) and len(data) > 0:
                        agent = data[0]
                        return agent.get("id") or agent.get("agentId")
    except Exception as e:
        logger.debug(f"[REGISTRATION] Failed to check Indexer registration: {e}")

    return None


async def register_offchain(
    agent_card_url: str,
    indexer_url: str,
    owner: str,
    labels: Optional[dict] = None,
    agent_id: Optional[str] = None,
    private_key: Optional[str] = None,
    onchain_agent_id: Optional[int] = None,
    metadata_json: Optional[dict] = None
) -> Optional[str]:
    """
    Register agent with the ERC-8004 Indexer API.

    Args:
        agent_card_url: URL to the agent card (e.g., http://localhost:8000/.well-known/agent-card.json)
        indexer_url: URL of the Indexer API (e.g., http://localhost:8080)
        owner: Wallet address of the agent owner
        labels: Optional labels/metadata for the agent
        agent_id: ERC-8004 canonical ID (e.g., eip155:1337:0xRegistry:22) - REQUIRED for on-chain agents
        private_key: Private key for signing registration
        onchain_agent_id: On-chain numeric agent ID
        metadata_json: Pre-built metadata JSON (optional, will build if not provided)

    Returns:
        Agent ID (canonical format) if successful, None otherwise
    """
    logger.info(f"[OFFCHAIN REGISTRATION] Attempting Indexer registration...")
    logger.info(f"[OFFCHAIN REGISTRATION] Agent card URL: {agent_card_url}")
    logger.info(f"[OFFCHAIN REGISTRATION] Indexer: {indexer_url}")
    
    # Check if already registered (idempotency)
    if agent_id:
        existing = await query_indexer_for_agent(indexer_url, agent_id)
        if existing:
            logger.info(f"[OFFCHAIN REGISTRATION] ✓ Agent already registered with ID: {agent_id}")
            return agent_id
    
    # Fetch agent card ourselves to avoid registry timeout (use async if available)
    agent_card_data = None
    if HAS_AIOHTTP:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(agent_card_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        agent_card_data = await response.json()
                        logger.debug(f"[REGISTRATION] Fetched agent card successfully")
                    else:
                        logger.warning(f"[REGISTRATION] Agent card returned status {response.status}")
        except Exception as e:
            logger.warning(f"[REGISTRATION] Could not fetch agent card: {e}")
            logger.warning(f"[REGISTRATION] Falling back to registrationFileUrl method")
            agent_card_data = None
    else:
        # Fallback to sync method (not ideal but works)
        try:
            card_req = urllib.request.Request(agent_card_url, method='GET')
            with urllib.request.urlopen(card_req, timeout=5) as response:
                agent_card_data = json.loads(response.read().decode('utf-8'))
                logger.debug(f"[REGISTRATION] Fetched agent card successfully")
        except Exception as e:
            logger.warning(f"[REGISTRATION] Could not fetch agent card: {e}")
            logger.warning(f"[REGISTRATION] Falling back to registrationFileUrl method")
            agent_card_data = None
    
    # Use provided metadata_json or build it
    if metadata_json is None and agent_card_data:
        # Import here to avoid circular dependency (lazy import)
        from ...agent_registration import build_erc8004_metadata_json
        
        # Parse canonical ID to get chain_id and identity_registry for registrations array
        chain_id_for_reg = None
        identity_registry_for_reg = None
        if agent_id and agent_id.startswith("eip155:"):
            try:
                parts = agent_id.split(":")
                if len(parts) == 4:
                    chain_id_for_reg = int(parts[1])
                    identity_registry_for_reg = parts[2]
            except (ValueError, IndexError):
                logger.warning(f"[OFFCHAIN REGISTRATION] Could not parse canonical ID: {agent_id}")
        
        metadata_json = build_erc8004_metadata_json(
            agent_card_data,
            labels=labels or {"category": "compute", "type": "trader"},
            onchain_agent_id=onchain_agent_id,
            chain_id=chain_id_for_reg,
            identity_registry=identity_registry_for_reg
        )
        logger.debug(f"[OFFCHAIN REGISTRATION] Built metadata JSON: {json.dumps(metadata_json, indent=2)}")
    
    # Quick health check first
    try:
        health_req = urllib.request.Request(f"{indexer_url.rstrip('/')}/health", method='GET')
        urllib.request.urlopen(health_req, timeout=3)
    except Exception as e:
        logger.warning(f"[REGISTRATION] Indexer health check failed: {e}")
        logger.warning(f"[REGISTRATION] Indexer may not be running at {indexer_url}")
        return None
    
    # Build payload - use snake_case to match indexer expectations
    # Use labels from metadata_json if available, otherwise fallback
    effective_labels = labels or {"category": "compute", "type": "trader"}
    if metadata_json:
        # Ensure labels include category and type from metadata
        effective_labels = {
            **effective_labels,
            "category": metadata_json.get("category", effective_labels.get("category", "compute")),
            "type": metadata_json.get("type", effective_labels.get("type", "trader")),
        }
    
    base_payload = {
        "owner": owner,
        "labels": effective_labels,
        "auth": {},  # Add empty auth to match indexer structure
        "domain": None,  # Add domain to match indexer structure
        "visibility": "public",  # Add visibility to match indexer structure
        "registration_file": None,  # Add to match indexer structure
        "registration_file_url": None,  # Add to match indexer structure
        # Important: include chain_id (even if None) so that the agent-side
        # signature hash matches the Indexer's AgentRegistration.model_dump(),
        # which always includes this field (defaulting to null).
        "chain_id": None,
    }

    # Include agent_id if provided
    if agent_id is not None:
        base_payload["agent_id"] = agent_id

    if agent_card_data:
        payload = {
            **base_payload,
            "agent_card": agent_card_data,  # Use snake_case to match indexer
        }
    else:
        payload = {
            **base_payload,
            "registration_file_url": agent_card_url,  # Use snake_case
        }

    # Add signature if private key is available
    if private_key:
        if not HAS_ETH_ACCOUNT:
            logger.warning(f"[OFFCHAIN REGISTRATION] eth_account not available, proceeding without signature")
        else:
            try:
                account = Account.from_key(private_key)

                # Generate timestamp
                timestamp = int(time.time())

                # Create deterministic hash of registration data (excluding signature fields)
                data_to_hash = {k: v for k, v in payload.items() if k not in ['signature', 'timestamp']}

                # Keep A2A agent card in camelCase (protocol compliant) - indexer handles camelCase
                data_str = json.dumps(data_to_hash, sort_keys=True, separators=(',', ':'))
                data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]

                # Debug logging
                logger.info(f"[OFFCHAIN REGISTRATION] Data being hashed: {data_str}")
                logger.info(f"[OFFCHAIN REGISTRATION] Generated hash: {data_hash}")

                # Create and sign message
                message = f"register:{owner}:{timestamp}:{data_hash}"
                logger.info(f"[OFFCHAIN REGISTRATION] Message to sign: {message}")
                message_hash = encode_defunct(text=message)
                signed_message = Account.sign_message(message_hash, private_key=private_key)

                # Add signature and timestamp to payload
                payload["signature"] = signed_message.signature.hex()
                payload["timestamp"] = timestamp

                logger.info(f"[OFFCHAIN REGISTRATION] ✓ Added cryptographic signature for owner {owner}")
                logger.info(f"[OFFCHAIN REGISTRATION] Message: {message}")
                logger.info(f"[OFFCHAIN REGISTRATION] Data hash: {data_hash}")
                logger.info(f"[OFFCHAIN REGISTRATION] Signature: {signed_message.signature.hex()}")
                logger.info(f"[OFFCHAIN REGISTRATION] Sending to indexer (A2A card in camelCase): {json.dumps(payload, sort_keys=True, separators=(',', ':'))}")
            except Exception as e:
                logger.warning(f"[OFFCHAIN REGISTRATION] Could not generate signature: {e}")
                logger.warning(f"[OFFCHAIN REGISTRATION] Proceeding without signature")
    else:
        logger.info(f"[OFFCHAIN REGISTRATION] No private key provided, proceeding without signature")

    try:
        req = urllib.request.Request(
            f"{indexer_url.rstrip('/')}/agents/register",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        # Shorter timeout since we're sending data directly
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            # Indexer returns "id" not "agent_id"
            agent_id = result.get('id') or result.get('agent_id')
            logger.info(f"[OFFCHAIN REGISTRATION] Indexer registration successful! Agent ID: {agent_id}")
            return agent_id
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.warning(f"[OFFCHAIN REGISTRATION] Indexer registration failed: {e.code} - {error_body}")
        return None
    except urllib.error.URLError as e:
        logger.warning(f"[OFFCHAIN REGISTRATION] Cannot connect to Indexer at {indexer_url}: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"[OFFCHAIN REGISTRATION] Unexpected error during Indexer registration: {e}")
        return None

