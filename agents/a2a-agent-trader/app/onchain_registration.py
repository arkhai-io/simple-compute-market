"""
Auto-registration module for a2a-agent-trader.

Supports both Indexer (via Indexer API) and on-chain (via smart contract) registration.
Registration happens automatically on agent startup when AUTO_REGISTER=true.
"""
import asyncio
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, TYPE_CHECKING

# Try to use aiohttp for async HTTP, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

if TYPE_CHECKING:
    from .utils.config import Config

logger = logging.getLogger(__name__)

# Path to store agent ID after registration
AGENT_ID_FILE = Path(__file__).parent.parent / ".agent_id"

# Delay before attempting registration (seconds)
# This allows the server to fully start before registration
REGISTRATION_DELAY = 5

# Heartbeat interval (seconds) - should be less than Indexer's heartbeat_ttl_secs
HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds

# ERC-8004 Identity Registry ABI (minimal - only register function)
IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "tokenURI", "type": "string"},
            {"name": "metadata", "type": "tuple[]", "components": [
                {"name": "key", "type": "string"},
                {"name": "value", "type": "string"}
            ]}
        ],
        "name": "register",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


async def register_offchain(
    agent_card_url: str,
    indexer_url: str,
    owner: str,
    labels: Optional[dict] = None
) -> Optional[str]:
    """
    Register agent with the ERC-8004 Indexer API.
    
    Args:
        agent_card_url: URL to the agent card (e.g., http://localhost:8000/.well-known/agent-card.json)
        indexer_url: URL of the Indexer API (e.g., http://localhost:8080)
        owner: Wallet address of the agent owner
        labels: Optional labels/metadata for the agent
        
    Returns:
        Agent ID if successful, None otherwise
    """
    logger.info(f"[REGISTRATION] Attempting Indexer registration...")
    logger.info(f"[REGISTRATION] Agent card URL: {agent_card_url}")
    logger.info(f"[REGISTRATION] Indexer: {indexer_url}")
    
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
    
    # Quick health check first
    try:
        health_req = urllib.request.Request(f"{indexer_url.rstrip('/')}/health", method='GET')
        urllib.request.urlopen(health_req, timeout=3)
    except Exception as e:
        logger.warning(f"[REGISTRATION] Indexer health check failed: {e}")
        logger.warning(f"[REGISTRATION] Indexer may not be running at {indexer_url}")
        return None
    
    # Build payload - prefer sending agent card directly to avoid registry fetch timeout
    if agent_card_data:
        payload = {
            "agentCard": agent_card_data,
            "owner": owner,
            "labels": labels or {"category": "compute", "type": "trader"}
        }
    else:
        payload = {
            "registrationFileUrl": agent_card_url,
            "owner": owner,
            "labels": labels or {"category": "compute", "type": "trader"}
        }
    
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
            logger.info(f"[REGISTRATION] Indexer registration successful! Agent ID: {agent_id}")
            return agent_id
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.warning(f"[REGISTRATION] Indexer registration failed: {e.code} - {error_body}")
        return None
    except urllib.error.URLError as e:
        logger.warning(f"[REGISTRATION] Cannot connect to Indexer at {indexer_url}: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"[REGISTRATION] Unexpected error during Indexer registration: {e}")
        return None


def _get_stored_agent_id() -> Optional[int]:
    """Get stored agent ID from file (cache only, not source of truth)"""
    try:
        if AGENT_ID_FILE.exists():
            agent_id_str = AGENT_ID_FILE.read_text().strip()
            return int(agent_id_str) if agent_id_str.isdigit() else None
    except Exception:
        pass
    return None


def _store_agent_id(agent_id: int) -> None:
    """Store agent ID to file (cache only)"""
    try:
        AGENT_ID_FILE.write_text(str(agent_id))
        logger.debug(f"[REGISTRATION] Cached agent ID: {agent_id}")
    except Exception as e:
        logger.warning(f"[REGISTRATION] Could not cache agent ID: {e}")


async def _query_indexer_for_agent(indexer_url: str, agent_id: str) -> Optional[dict]:
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


def _find_agent_id_by_owner(w3, contract, owner_address: str, max_blocks: int = 10000) -> Optional[int]:
    """Find agent ID by checking past registration events for this owner"""
    try:
        current_block = w3.eth.block_number
        from_block = max(0, current_block - max_blocks)
        
        # Get past AgentRegistered events
        events = contract.events.AgentRegistered.create_filter(
            from_block=from_block,
            to_block="latest"
        ).get_all_entries()
        
        # Find most recent registration by this owner
        for event in reversed(events):  # Check most recent first
            try:
                # Extract agent ID from event
                if hasattr(event, 'args'):
                    agent_id = None
                    if hasattr(event.args, 'agentId'):
                        agent_id = event.args.agentId
                    elif hasattr(event.args, 'agent_id'):
                        agent_id = event.args.agent_id
                    elif isinstance(event.args, (list, tuple)) and len(event.args) > 0:
                        agent_id = event.args[0]
                    
                    if agent_id:
                        # Check if this agent is owned by our address
                        try:
                            owner = contract.functions.ownerOf(agent_id).call()
                            if owner.lower() == owner_address.lower():
                                return int(agent_id)
                        except Exception:
                            continue
            except Exception:
                continue
        
        return None
    except Exception as e:
        logger.debug(f"[REGISTRATION] Could not search past events: {e}")
        return None


async def register_onchain(
    agent_card_url: str,
    private_key: str,
    rpc_url: str,
    contract_address: str,
    owner_address: Optional[str] = None,
    explicit_agent_id: Optional[str] = None,
    indexer_url: Optional[str] = None
) -> Optional[str]:
    """
    Register or update agent on-chain by calling the ERC-8004 Identity Registry contract.
    Checks if agent is already registered and updates metadata instead of re-registering.
    
    Priority order for finding existing agent:
    1. Explicit agent ID from environment variable (ONCHAIN_AGENT_ID)
    2. Query Indexer API (if indexer_url provided)
    3. Cached agent ID from file
    4. Search blockchain events (last resort)
    
    Args:
        agent_card_url: URL to the agent card (used as tokenURI)
        private_key: Private key for signing the transaction
        rpc_url: Blockchain RPC URL
        contract_address: ERC-8004 Identity Registry contract address
        owner_address: Optional owner address (defaults to signer address)
        explicit_agent_id: Explicit agent ID from env var (highest priority)
        indexer_url: Indexer API URL to query for existing agent
        
    Returns:
        Transaction hash if successful, None otherwise
    """
    try:
        from web3 import Web3
        from web3.providers import HTTPProvider
    except ImportError:
        logger.error("[REGISTRATION] web3 package not installed. Cannot perform on-chain registration.")
        return None
    
    logger.info(f"[REGISTRATION] Attempting on-chain registration...")
    logger.info(f"[REGISTRATION] Token URI: {agent_card_url}")
    logger.info(f"[REGISTRATION] Contract: {contract_address}")
    
    try:
        # Use HTTP provider for now (most RPC providers support HTTP even if URL is ws://)
        # Convert ws:// to http:// for compatibility
        http_url = rpc_url.replace("ws://", "http://").replace("wss://", "https://")
        logger.debug(f"[REGISTRATION] Connecting to RPC: {http_url} (converted from {rpc_url})")
        w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 10}))
        
        if not w3.is_connected():
            logger.error(f"[REGISTRATION] Cannot connect to RPC at {http_url} (original: {rpc_url})")
            return None
        
        account = w3.eth.account.from_key(private_key)
        to_address = owner_address or account.address
        
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=IDENTITY_REGISTRY_ABI
        )
        
        # Check if agent is already registered (priority order)
        agent_id = None
        
        # 1. Explicit agent ID from env var (highest priority - user override)
        if explicit_agent_id:
            try:
                agent_id = int(explicit_agent_id)
                logger.info(f"[REGISTRATION] Using explicit agent ID from env: {agent_id}")
                # Verify it's valid
                owner = contract.functions.ownerOf(agent_id).call()
                if owner.lower() != to_address.lower():
                    logger.warning(f"[REGISTRATION] Explicit agent ID {agent_id} owned by different address, ignoring")
                    agent_id = None
            except Exception as e:
                logger.warning(f"[REGISTRATION] Invalid explicit agent ID {explicit_agent_id}: {e}")
                agent_id = None
        
        # 2. Query Indexer API (fast, already indexed)
        if not agent_id and indexer_url:
            logger.debug(f"[REGISTRATION] Querying Indexer for existing agent...")
            cached_id = _get_stored_agent_id()
            if cached_id:
                indexer_data = await _query_indexer_for_agent(indexer_url, str(cached_id))
                if indexer_data:
                    try:
                        # Verify ownership on-chain
                        owner = contract.functions.ownerOf(cached_id).call()
                        if owner.lower() == to_address.lower():
                            agent_id = cached_id
                            logger.info(f"[REGISTRATION] Found agent in Indexer (ID: {agent_id})")
                    except Exception:
                        pass
        
        # 3. Use cached agent ID from file (verify it's still valid)
        if not agent_id:
            cached_id = _get_stored_agent_id()
            if cached_id:
                # Verify stored agent ID is still valid
                try:
                    owner = contract.functions.ownerOf(cached_id).call()
                    if owner.lower() == to_address.lower():
                        agent_id = cached_id
                        logger.info(f"[REGISTRATION] Using cached agent ID: {agent_id}")
                    else:
                        logger.warning(f"[REGISTRATION] Cached agent ID {cached_id} owned by different address")
                except Exception as e:
                    logger.debug(f"[REGISTRATION] Cached agent ID {cached_id} invalid: {e}")
        
        # If we found an existing agent ID, update metadata instead of registering
        if agent_id:
            logger.info(f"[REGISTRATION] Agent already registered (ID: {agent_id}), updating metadata...")
            try:
                # Update metadata instead of registering
                metadata = [
                    ("category", "compute"),
                    ("type", "a2a-trader"),
                    ("tokenURI", agent_card_url),
                ]
                
                tx = contract.functions.setMetadata(agent_id, metadata).build_transaction({
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "gas": 200000,
                    "gasPrice": w3.eth.gas_price,
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logger.info(f"[REGISTRATION] Metadata update submitted! TX: {tx_hash.hex()}")
                
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info(f"[REGISTRATION] Metadata updated! Block: {receipt.blockNumber}")
                    _store_agent_id(agent_id)  # Update cache
                    return tx_hash.hex()
                else:
                    logger.warning(f"[REGISTRATION] Metadata update failed")
            except Exception as e:
                logger.error(f"[REGISTRATION] Error updating metadata: {e}")
                # Fall through to register new
        
        # 4. Search blockchain events (last resort - slow/expensive)
        if not agent_id:
            logger.debug(f"[REGISTRATION] Searching blockchain for existing registration...")
            agent_id = _find_agent_id_by_owner(w3, contract, to_address)
            if agent_id:
                logger.info(f"[REGISTRATION] Found existing registration (ID: {agent_id}), updating metadata...")
                _store_agent_id(agent_id)
                
                metadata = [
                    ("category", "compute"),
                    ("type", "a2a-trader"),
                    ("tokenURI", agent_card_url),
                ]
                
                tx = contract.functions.setMetadata(agent_id, metadata).build_transaction({
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "gas": 200000,
                    "gasPrice": w3.eth.gas_price,
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logger.info(f"[REGISTRATION] Metadata update submitted! TX: {tx_hash.hex()}")
                
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info(f"[REGISTRATION] Metadata updated! Block: {receipt.blockNumber}")
                    return tx_hash.hex()
                else:
                    logger.warning(f"[REGISTRATION] Metadata update failed")
        
        # No existing registration found, register new
        logger.info(f"[REGISTRATION] Registering new agent on-chain...")
        metadata = [
            ("category", "compute"),
            ("type", "a2a-trader"),
        ]
        
        # Build transaction
        tx = contract.functions.register(
            Web3.to_checksum_address(to_address),
            agent_card_url,
            metadata
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 500000,  # Reasonable gas limit for registration
            "gasPrice": w3.eth.gas_price,
        })
        
        # Sign and send transaction
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logger.info(f"[REGISTRATION] On-chain registration submitted! TX: {tx_hash.hex()}")
        
        # Wait for confirmation
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            logger.info(f"[REGISTRATION] On-chain registration confirmed! Block: {receipt.blockNumber}")
            
            # Extract agent ID from event logs
            if receipt.logs:
                for log in receipt.logs:
                    try:
                        event = contract.events.AgentRegistered().process_log(log)
                        if event and hasattr(event, 'args'):
                            new_agent_id = None
                            if hasattr(event.args, 'agentId'):
                                new_agent_id = event.args.agentId
                            elif hasattr(event.args, 'agent_id'):
                                new_agent_id = event.args.agent_id
                            elif isinstance(event.args, (list, tuple)) and len(event.args) > 0:
                                new_agent_id = event.args[0]
                            
                            if new_agent_id:
                                _store_agent_id(int(new_agent_id))
                                logger.info(f"[REGISTRATION] Stored new agent ID: {new_agent_id}")
                                break
                    except Exception:
                        continue
            
            return tx_hash.hex()
        else:
            logger.error(f"[REGISTRATION] On-chain registration failed! TX reverted.")
            return None
            
    except Exception as e:
        logger.error(f"[REGISTRATION] On-chain registration error: {e}")
        return None


async def register_agent_on_startup(config: "Config") -> Optional[str]:
    """
    Main registration function called on agent startup.
    
    Attempts both Indexer and on-chain registration based on configuration.
    Waits for the server to be ready before attempting registration.
    
    Args:
        config: Agent configuration object
        
    Returns:
        Agent ID or transaction hash if any registration succeeded, None otherwise
    """
    if not config.auto_register:
        logger.debug("[REGISTRATION] Auto-registration disabled")
        return None
    
    # Wait for server to be ready before attempting registration
    logger.info(f"[REGISTRATION] Waiting {REGISTRATION_DELAY}s for server to start...")
    await asyncio.sleep(REGISTRATION_DELAY)
    
    logger.info("[REGISTRATION] Starting auto-registration...")
    
    # Build agent card URL
    base_url = config.base_url_override.rstrip('/')
    agent_card_url = f"{base_url}/.well-known/agent-card.json"
    owner = config.agent_wallet_address or "0x0000000000000000000000000000000000000000"
    
    result = None
    
    # Attempt Indexer registration first
    if config.indexer_url:
        result = await register_offchain(
            agent_card_url=agent_card_url,
            indexer_url=config.indexer_url,
            owner=owner
        )
        if result:
            logger.info(f"[REGISTRATION] Indexer registration complete. Agent ID: {result}")
    
    # Attempt on-chain registration if configured
    if (config.agent_priv_key and 
        config.chain_rpc_url and 
        config.identity_registry_address):
        
        tx_hash = await register_onchain(
            agent_card_url=agent_card_url,
            private_key=config.agent_priv_key,
            rpc_url=config.chain_rpc_url,
            contract_address=config.identity_registry_address,
            owner_address=config.agent_wallet_address,
            explicit_agent_id=config.onchain_agent_id,
            indexer_url=config.indexer_url
        )
        if tx_hash:
            logger.info(f"[REGISTRATION] On-chain registration complete. TX: {tx_hash}")
            result = result or tx_hash
    elif config.identity_registry_address:
        # Contract configured but missing credentials
        missing = []
        if not config.agent_priv_key:
            missing.append("AGENT_PRIV_KEY")
        if not config.chain_rpc_url:
            missing.append("CHAIN_RPC_URL")
        logger.warning(
            f"[REGISTRATION] On-chain registration skipped. Missing: {', '.join(missing)}"
        )
    
    if not result:
        logger.warning("[REGISTRATION] No registration completed. Agent will not be discoverable via Indexer.")
    
    # Start heartbeat loop if Indexer registration succeeded
    if result and config.indexer_url:
        # Extract agent ID from result (could be agent ID string or TX hash)
        # If it's a temp ID from Indexer, use it for heartbeats
        if isinstance(result, str) and result.startswith("temp_"):
            asyncio.create_task(heartbeat_loop(result, config.indexer_url, config.agent_priv_key, owner))
            logger.info(f"[REGISTRATION] Started heartbeat loop for agent {result}")
    
    return result


async def send_heartbeat(
    agent_id: str, 
    indexer_url: str, 
    private_key: Optional[str] = None,
    owner_address: Optional[str] = None
) -> bool:
    """
    Send heartbeat to Indexer to indicate agent is alive.
    
    Signs the heartbeat with the agent's private key to authenticate the request.
    
    Args:
        agent_id: Agent ID (from Indexer registration)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeat (optional if agent has no owner)
        owner_address: Owner wallet address (optional, used for logging)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import time
        timestamp = int(time.time())
        
        # Prepare request body with signature if private key is available
        body = {}
        if private_key:
            try:
                from eth_account import Account
                from eth_account.messages import encode_defunct
                
                # Construct message to sign
                message = f"heartbeat:{agent_id}:{timestamp}"
                
                # Sign message using EIP-191 personal sign format
                message_hash = encode_defunct(text=message)
                signed_message = Account.sign_message(message_hash, private_key)
                signature = signed_message.signature.hex()
                
                body = {
                    "signature": signature,
                    "timestamp": timestamp
                }
            except ImportError:
                logger.warning("[HEARTBEAT] eth_account not available, sending heartbeat without signature")
            except Exception as e:
                logger.warning(f"[HEARTBEAT] Failed to sign heartbeat: {e}")
        
        if HAS_AIOHTTP:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{indexer_url.rstrip('/')}/agents/{agent_id}/heartbeat",
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return True
                    elif response.status == 401:
                        logger.warning(f"[HEARTBEAT] Authentication failed - signature may be invalid")
                        return False
        else:
            import urllib.request
            import json as json_module
            req = urllib.request.Request(
                f"{indexer_url.rstrip('/')}/agents/{agent_id}/heartbeat",
                data=json_module.dumps(body).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    return True
    except Exception as e:
        logger.debug(f"[HEARTBEAT] Failed to send heartbeat: {e}")
    return False


async def heartbeat_loop(
    agent_id: Optional[str], 
    indexer_url: str,
    private_key: Optional[str] = None,
    owner_address: Optional[str] = None
):
    """
    Background task to periodically send heartbeats to Indexer.
    
    Args:
        agent_id: Agent ID from registration (None if not registered)
        indexer_url: Indexer API URL
        private_key: Private key for signing heartbeats (optional)
        owner_address: Owner wallet address (optional, for logging)
    """
    if not agent_id:
        logger.debug("[HEARTBEAT] No agent ID, skipping heartbeat loop")
        return
    
    logger.info(f"[HEARTBEAT] Starting heartbeat loop for agent {agent_id}")
    if private_key:
        logger.debug("[HEARTBEAT] Heartbeats will be signed for authentication")
    else:
        logger.warning("[HEARTBEAT] No private key provided - heartbeats will be unsigned (may fail if Indexer requires auth)")
    
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            success = await send_heartbeat(agent_id, indexer_url, private_key, owner_address)
            if success:
                logger.debug(f"[HEARTBEAT] Heartbeat sent successfully")
            else:
                logger.warning(f"[HEARTBEAT] Failed to send heartbeat")
        except asyncio.CancelledError:
            logger.info("[HEARTBEAT] Heartbeat loop cancelled")
            break
        except Exception as e:
            logger.error(f"[HEARTBEAT] Error in heartbeat loop: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)  # Wait before retrying

