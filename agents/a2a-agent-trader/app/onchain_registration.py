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

# Note: We don't cache agent IDs - each agent instance registers independently
# Multiple agents on different ports will each get their own on-chain agent ID

# Delay before attempting registration (seconds)
# This allows the server to fully start before registration
REGISTRATION_DELAY = 5

# Heartbeat interval (seconds) - should be less than Indexer's heartbeat_ttl_secs
HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds

# ERC-8004 Identity Registry ABI (complete - includes all ERC721 functions needed)
# Contains register, transferFrom, ownerOf, and all other essential functions
IDENTITY_REGISTRY_ABI = [
    # Agent registration functions
    {
        "inputs": [],
        "name": "register",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "string",
                "name": "tokenUri",
                "type": "string"
            }
        ],
        "name": "register",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "string",
                "name": "tokenUri",
                "type": "string"
            },
            {
                "internalType": "tuple[]",
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {
                        "internalType": "string",
                        "name": "key",
                        "type": "string"
                    },
                    {
                        "internalType": "bytes",
                        "name": "value",
                        "type": "bytes"
                    }
                ]
            }
        ],
        "name": "register",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },

    # ERC721 ownership functions
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "from",
                "type": "address"
            },
            {
                "internalType": "address",
                "name": "to",
                "type": "address"
            },
            {
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256"
            }
        ],
        "name": "transferFrom",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256"
            }
        ],
        "name": "ownerOf",
        "outputs": [
            {
                "internalType": "address",
                "name": "",
                "type": "address"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "owner",
                "type": "address"
            }
        ],
        "name": "balanceOf",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },

    # Metadata management functions
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            },
            {
                "internalType": "string",
                "name": "key",
                "type": "string"
            }
        ],
        "name": "getMetadata",
        "outputs": [
            {
                "internalType": "bytes",
                "name": "",
                "type": "bytes"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            },
            {
                "internalType": "string",
                "name": "key",
                "type": "string"
            },
            {
                "internalType": "bytes",
                "name": "value",
                "type": "bytes"
            }
        ],
        "name": "setMetadata",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            },
            {
                "internalType": "string",
                "name": "newUri",
                "type": "string"
            }
        ],
        "name": "setAgentUri",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },

    # Additional useful functions
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256"
            }
        ],
        "name": "tokenURI",
        "outputs": [
            {
                "internalType": "string",
                "name": "",
                "type": "string"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "owner",
                "type": "address"
            },
            {
                "internalType": "address",
                "name": "operator",
                "type": "address"
            }
        ],
        "name": "isApprovedForAll",
        "outputs": [
            {
                "internalType": "bool",
                "name": "",
                "type": "bool"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256"
            }
        ],
        "name": "getApproved",
        "outputs": [
            {
                "internalType": "address",
                "name": "",
                "type": "address"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },

    # Events
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "agentId",
                "type": "uint256"
            },
            {
                "indexed": False,
                "internalType": "string",
                "name": "tokenURI",
                "type": "string"
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "owner",
                "type": "address"
            }
        ],
        "name": "Registered",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "from",
                "type": "address"
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "to",
                "type": "address"
            },
            {
                "indexed": True,
                "internalType": "uint256",
                "name": "tokenId",
                "type": "uint256"
            }
        ],
        "name": "Transfer",
        "type": "event"
    }
]


async def register_offchain(
    agent_card_url: str,
    indexer_url: str,
    owner: str,
    labels: Optional[dict] = None,
    agent_id: Optional[str] = None,
    private_key: Optional[str] = None
) -> Optional[str]:
    """
    Register agent with the ERC-8004 Indexer API.

    Args:
        agent_card_url: URL to the agent card (e.g., http://localhost:8000/.well-known/agent-card.json)
        indexer_url: URL of the Indexer API (e.g., http://localhost:8080)
        owner: Wallet address of the agent owner
        labels: Optional labels/metadata for the agent
        agent_id: Optional custom agent ID (e.g., wallet_address:agent_id)

    Returns:
        Agent ID if successful, None otherwise
    """
    logger.info(f"[OFFCHAIN REGISTRATION] Attempting Indexer registration...")
    logger.info(f"[OFFCHAIN REGISTRATION] Agent card URL: {agent_card_url}")
    logger.info(f"[OFFCHAIN REGISTRATION] Indexer: {indexer_url}")
    
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
    base_payload = {
        "owner": owner,
        "labels": labels or {"category": "compute", "type": "trader"}
    }

    # Include agent_id if provided
    if agent_id:
        base_payload["agentId"] = agent_id

    if agent_card_data:
        payload = {
            **base_payload,
            "agentCard": agent_card_data,
        }
    else:
        payload = {
            **base_payload,
            "registrationFileUrl": agent_card_url,
        }

    # Add signature if private key is available
    if private_key:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            import hashlib
            import time

            # Generate timestamp
            timestamp = int(time.time())

            # Create deterministic hash of registration data (excluding signature fields)
            data_to_hash = {k: v for k, v in payload.items() if k not in ['signature', 'timestamp']}
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


# Removed agent ID caching - each agent instance registers independently


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
    """Find agent ID by checking token ownership (primary) and events (fallback)"""
    try:
        logger.debug(f"[REGISTRATION] Searching for owner {owner_address}")

        # PRIMARY: Try to find events (reliable with new contract that emits events)
        current_block = w3.eth.block_number
        from_block = max(0, current_block - max_blocks)

        # List all available events for debugging
        try:
            event_names = [attr for attr in dir(contract.events) if not attr.startswith('_')]
            logger.debug(f"[REGISTRATION] Available events: {event_names}")
        except Exception as e:
            logger.debug(f"[REGISTRATION] Could not list events: {e}")

        # Try multiple possible event names
        events = []
        event_names_to_try = ['Registered', 'AgentRegistered', 'Registration', 'CreateAgent', 'AgentCreated']

        for event_name in event_names_to_try:
            try:
                if hasattr(contract.events, event_name):
                    logger.debug(f"[REGISTRATION] Trying event {event_name}...")
                    event_filter = getattr(contract.events, event_name).create_filter(
                        from_block=from_block,
                        to_block="latest"
                    )
                    events = event_filter.get_all_entries()
                    logger.info(f"[REGISTRATION] Found {len(events)} {event_name} events")
                    if events:
                        break
            except Exception as e:
                logger.debug(f"[REGISTRATION] Event {event_name} not available: {e}")
                continue

        # Find most recent registration by this owner
        logger.info(f"[REGISTRATION] Processing {len(events)} events for owner {owner_address}")
        for i, event in enumerate(reversed(events)):  # Check most recent first
            try:
                logger.info(f"[REGISTRATION] Processing event {i+1}/{len(events)}")
                # Extract agent ID and owner from event
                if hasattr(event, 'args'):
                    agent_id = None
                    event_owner = None

                    if hasattr(event.args, 'agentId'):
                        agent_id = event.args.agentId
                        # Registered event has owner as indexed parameter
                        if hasattr(event.args, 'owner'):
                            event_owner = event.args.owner
                        logger.info(f"[REGISTRATION] Event has agentId: {agent_id}, owner: {event_owner}")
                    elif hasattr(event.args, 'agent_id'):
                        agent_id = event.args.agent_id
                        if hasattr(event.args, 'owner'):
                            event_owner = event.args.owner
                        logger.info(f"[REGISTRATION] Event has agent_id: {agent_id}, owner: {event_owner}")
                    elif isinstance(event.args, (list, tuple)) and len(event.args) >= 2:
                        agent_id = event.args[0]
                        event_owner = event.args[2] if len(event.args) > 2 else None
                        logger.info(f"[REGISTRATION] Event tuple: agent_id: {agent_id}, owner: {event_owner}")
                    else:
                        logger.warning(f"[REGISTRATION] Event args structure unknown: {event.args}")

                    if agent_id:
                        # Check if this agent is owned by our address
                        # First check event owner, then verify on-chain
                        if event_owner and event_owner.lower() == owner_address.lower():
                            logger.info(f"[REGISTRATION] Event owner matches: {event_owner} == {owner_address}")
                            try:
                                # Double-check on-chain
                                owner = contract.functions.ownerOf(agent_id).call()
                                logger.info(f"[REGISTRATION] On-chain owner of agent {agent_id}: {owner}")
                                if owner.lower() == owner_address.lower():
                                    logger.info(f"[REGISTRATION] ✓ Found matching agent ID: {agent_id}")
                                    return int(agent_id)
                                else:
                                    logger.warning(f"[REGISTRATION] On-chain owner mismatch: {owner} != {owner_address}")
                            except Exception as e:
                                logger.warning(f"[REGISTRATION] Error checking on-chain owner for {agent_id}: {e}")
                                continue
                        else:
                            logger.info(f"[REGISTRATION] Event owner mismatch or missing: {event_owner} != {owner_address}, checking on-chain...")
                            # Fallback: check on-chain
                            try:
                                owner = contract.functions.ownerOf(agent_id).call()
                                logger.info(f"[REGISTRATION] On-chain owner check for agent {agent_id}: {owner}")
                                if owner.lower() == owner_address.lower():
                                    logger.info(f"[REGISTRATION] ✓ Found matching agent ID via on-chain check: {agent_id}")
                                    return int(agent_id)
                                else:
                                    logger.info(f"[REGISTRATION] On-chain owner does not match: {owner} != {owner_address}")
                            except Exception as e:
                                logger.warning(f"[REGISTRATION] Error checking on-chain owner for {agent_id}: {e}")
                                continue
            except Exception:
                continue

        logger.debug(f"[REGISTRATION] No agent found for owner {owner_address} in {len(events)} events")

        return None
    except Exception as e:
        logger.warning(f"[REGISTRATION] Could not search past events: {e}")
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
    2. Search blockchain events (finds most recent registration by owner)
    
    Note: Each agent instance registers independently. Multiple agents on different ports
    will each get their own on-chain agent ID (auto-incremented by contract).
    No local caching is used - agents always check the blockchain for existing registrations.
    
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
        logger.error("[ONCHAIN REGISTRATION] web3 package not installed. Cannot perform on-chain registration.")
        return None
    
    logger.info(f"[ONCHAIN REGISTRATION] Attempting on-chain registration...")
    logger.info(f"[ONCHAIN REGISTRATION] Token URI: {agent_card_url}")
    logger.info(f"[ONCHAIN REGISTRATION] Contract: {contract_address}")
    
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
        # Official contract always mints to msg.sender (the account signing)
        # If owner_address differs, we'd need to transfer after registration
        signer_address = account.address
        
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
                logger.info(f"[REGISTRATION] Using explicit agent ID {agent_id} (searching for owner {owner_address or signer_address})")
                # Verify it's valid
                owner = contract.functions.ownerOf(agent_id).call()
                logger.info(f"[REGISTRATION] Agent {agent_id} owned by {owner}")

                # Check if owner matches what we expect
                expected_owner = owner_address if owner_address else signer_address
                if owner.lower() != expected_owner.lower():
                    logger.warning(f"[REGISTRATION] Explicit agent ID {agent_id} owned by {owner}, expected {expected_owner}, ignoring")
                    agent_id = None
                else:
                    logger.info(f"[REGISTRATION] ✓ Explicit agent ID {agent_id} ownership confirmed")
            except Exception as e:
                logger.warning(f"[REGISTRATION] Invalid explicit agent ID {explicit_agent_id}: {e}")
                agent_id = None
        
        # 2. Search blockchain events (finds most recent registration by owner)
        if not agent_id:
            logger.debug(f"[REGISTRATION] Searching blockchain for existing registration by owner...")
            # Use owner_address if provided, otherwise signer_address
            search_address = owner_address if owner_address else signer_address
            agent_id = _find_agent_id_by_owner(w3, contract, search_address)
            if agent_id:
                logger.info(f"[REGISTRATION] Found existing registration (ID: {agent_id}) for owner {search_address}")
                # Continue to idempotent check below
        
        # If we found an existing agent ID, skip registration entirely (idempotent)
        if agent_id:
            logger.info(f"[REGISTRATION] ✓ Agent already registered with ID: {agent_id}")
            logger.info(f"[REGISTRATION] ✓ Skipping on-chain registration (idempotent)")

            # Successfully found existing registration - no need for additional verification
            logger.info(f"[REGISTRATION] ✓ Using existing agent ID {agent_id} for wallet {owner_address if owner_address else signer_address}")

            return None  # Return None to indicate no transaction was needed
        
        # No existing registration found, register new
        logger.info(f"[ONCHAIN REGISTRATION] Registering new agent on-chain...")
        # Official contract: register(string tokenUri, MetadataEntry[] metadata)
        # MetadataEntry is {string key, bytes value}
        metadata = [
            ("category", "compute".encode('utf-8')),  # Convert to bytes
            ("type", "a2a-trader".encode('utf-8')),
        ]
        
        # Build transaction - no 'to' parameter, always mints to msg.sender
        tx = contract.functions.register(
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
        
        logger.info(f"[ONCHAIN REGISTRATION] On-chain registration submitted! TX: {tx_hash.hex()}")
        
        # Wait for confirmation
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            logger.info(f"[ONCHAIN REGISTRATION] On-chain registration confirmed! Block: {receipt.blockNumber}")
            
            # Extract agent ID from event logs (Registered event)
            if receipt.logs:
                logger.info(f"[REGISTRATION] Processing {len(receipt.logs)} log(s) from transaction")
                for i, log in enumerate(receipt.logs):
                    try:
                        event = contract.events.Registered().process_log(log)
                        if event and hasattr(event, 'args'):
                            new_agent_id = None
                            if hasattr(event.args, 'agentId'):
                                new_agent_id = event.args.agentId
                            elif hasattr(event.args, 'agent_id'):
                                new_agent_id = event.args.agent_id
                            elif isinstance(event.args, (list, tuple)) and len(event.args) > 0:
                                new_agent_id = event.args[0]

                            if new_agent_id:
                                onchain_id = int(new_agent_id)
                                logger.info(f"[REGISTRATION] ✓ Registered new agent ID: {onchain_id}")
                                break
                            else:
                                logger.warning(f"[REGISTRATION] Event found but no agent ID in log {i}")
                    except Exception as e:
                        logger.debug(f"[REGISTRATION] Could not parse log {i} as Registered event: {e}")
                        continue

                if 'onchain_id' not in locals():
                    logger.warning(f"[REGISTRATION] No agent ID found in transaction logs")
            else:
                logger.warning(f"[REGISTRATION] No logs found in transaction receipt")

            # Handle NFT transfer if needed
            if 'onchain_id' in locals():
                # If owner_address was specified and differs from signer, transfer NFT
                if owner_address and owner_address.lower() != signer_address.lower():
                    logger.info(f"[REGISTRATION] Transferring agent NFT to {owner_address}...")
                    # Execute ERC721 transfer
                    transfer_tx = contract.functions.transferFrom(
                        signer_address,
                        owner_address,
                        onchain_id
                    ).build_transaction({
                        'from': signer_address,
                        'nonce': w3.eth.get_transaction_count(signer_address),
                        'gas': 200000,
                        'gasPrice': w3.eth.gas_price,
                        'chainId': w3.eth.chain_id
                    })

                    # Sign and send transfer transaction
                    signed_transfer_tx = w3.eth.account.sign_transaction(transfer_tx, private_key)
                    transfer_tx_hash = w3.eth.send_raw_transaction(signed_transfer_tx.rawTransaction)

                    # Wait for transfer confirmation
                    transfer_receipt = w3.eth.wait_for_transaction_receipt(transfer_tx_hash, timeout=60)

                    if transfer_receipt.status == 1:
                        logger.info(f"[REGISTRATION] ✓ Agent NFT transferred to {owner_address}")
                    else:
                        logger.error(f"[REGISTRATION] ✗ NFT transfer failed for agent {onchain_id}")

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

    # Build agent card URL
    base_url = config.base_url_override.rstrip('/')
    agent_card_url = f"{base_url}/.well-known/agent-card.json"
    
    # Initialize indexer_agent_id to None
    indexer_agent_id = None
    
    # Attempt on-chain registration if configured
    if (config.agent_priv_key and
        config.chain_rpc_url and
        config.identity_registry_address):

        # Early check: see if agent is already registered on-chain
        try:
            from web3 import Web3
            from web3.providers import HTTPProvider
            # Use HTTP provider for compatibility (same as register_onchain function)
            http_url = config.chain_rpc_url.replace("ws://", "http://").replace("wss://", "https://")
            w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 10}))
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(config.identity_registry_address),
                abi=IDENTITY_REGISTRY_ABI
            )

            # Check if agent already exists by searching for owner's tokens
            existing_agent_id = _find_agent_id_by_owner(w3, contract, wallet_address)
            if existing_agent_id:
                logger.info(f"[ONCHAIN REGISTRATION] ✓ Wallet already registered on-chain with agent ID: {existing_agent_id}")

                # Successfully verified existing registration
                logger.info(f"[ONCHAIN REGISTRATION] ✓ Using existing agent ID {existing_agent_id}")
                logger.info(f"[ONCHAIN REGISTRATION] ✓ Agent registration is idempotent")

                logger.info(f"[ONCHAIN REGISTRATION] ✓ Skipping on-chain registration (idempotent)")
            else:
                # Register new agent on-chain
                logger.info(f"[ONCHAIN REGISTRATION] No existing registration found, creating new agent NFT...")
                tx_hash = await register_onchain(
                    agent_card_url=agent_card_url,
                    private_key=config.agent_priv_key,
                    rpc_url=config.chain_rpc_url,
                    contract_address=config.identity_registry_address,
                    owner_address=wallet_address,
                    explicit_agent_id=config.onchain_agent_id,
                    indexer_url=config.indexer_url
                )
                if tx_hash:
                    logger.info(f"[ONCHAIN REGISTRATION] ✓ On-chain registration complete. TX: {tx_hash}")
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
    # This adds the agent to the indexer.db for discovery
    indexer_agent_id = None
    if config.indexer_url:
        try:
            # Create a deterministic agent ID from wallet address and agent_id
            # Format: {wallet_address}:{agent_id}
            custom_agent_id = f"{wallet_address}:{config.agent_id}"

            indexer_agent_id = await register_offchain(
                agent_card_url=agent_card_url,
                indexer_url=config.indexer_url,
                owner=wallet_address,
                agent_id=custom_agent_id,
                private_key=config.agent_priv_key
            )
            if indexer_agent_id:
                logger.info(f"[OFFCHAIN REGISTRATION] Indexer registration complete. Agent ID: {indexer_agent_id}")
            else:
                logger.warning("[OFFCHAIN REGISTRATION] Indexer registration returned no agent ID")
        except Exception as e:
            logger.warning(f"[OFFCHAIN REGISTRATION] Indexer registration failed: {e}")

    # Start heartbeat loop if Indexer registration succeeded
    if indexer_agent_id and config.indexer_url:
        asyncio.create_task(heartbeat_loop(indexer_agent_id, config.indexer_url, config.agent_priv_key, wallet_address))
        logger.info(f"[REGISTRATION] Started heartbeat loop for agent {indexer_agent_id}")

    logger.info(f"[REGISTRATION] Registration complete using wallet address as identifier: {wallet_address}")
    return wallet_address


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
            import urllib.parse
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

