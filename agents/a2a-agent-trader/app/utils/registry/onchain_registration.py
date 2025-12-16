"""
On-chain registration logic for ERC-8004 Identity Registry.
"""
import json
import logging
import urllib.request
from typing import Optional, Tuple

try:
    from web3 import Web3
    from web3.providers import HTTPProvider
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

# Try to use aiohttp for async HTTP, fallback to urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from .blockchain_utils import find_agent_id_by_owner, extract_agent_id_from_receipt
from ...abi.identity_registry_abi import FULL_IDENTITY_REGISTRY_ABI

logger = logging.getLogger(__name__)


async def register_onchain(
    agent_card_url: str,
    private_key: str,
    rpc_url: str,
    contract_address: str,
    owner_address: Optional[str] = None,
    explicit_agent_id: Optional[str] = None,
    indexer_url: Optional[str] = None
) -> Optional[Tuple[str, int]]:
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
        Tuple of (tx_hash, agent_id) if successful, None otherwise
        If agent already exists, returns (None, existing_agent_id)
    """
    if not HAS_WEB3:
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
            abi=FULL_IDENTITY_REGISTRY_ABI
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
        if agent_id is None:
            logger.debug(f"[REGISTRATION] Searching blockchain for existing registration by owner...")
            # Use owner_address if provided, otherwise signer_address
            search_address = owner_address if owner_address else signer_address
            agent_id = find_agent_id_by_owner(w3, contract, search_address)
            if agent_id is not None:
                logger.info(f"[REGISTRATION] Found existing registration (ID: {agent_id}) for owner {search_address}")
                # Continue to idempotent check below
        
        # If we found an existing agent ID, skip registration entirely (idempotent)
        # CRITICAL: Use 'is not None' instead of truthy check because agent_id 0 is valid!
        if agent_id is not None:
            logger.info(f"[REGISTRATION] ✓ Agent already registered with ID: {agent_id}")
            logger.info(f"[REGISTRATION] ✓ Skipping on-chain registration (idempotent)")

            # Successfully found existing registration - no need for additional verification
            logger.info(f"[REGISTRATION] ✓ Using existing agent ID {agent_id} for wallet {owner_address if owner_address else signer_address}")

            return (None, agent_id)  # Return (None, agent_id) to indicate existing registration
        
        # No existing registration found, register new
        logger.info(f"[ONCHAIN REGISTRATION] Registering new agent on-chain...")
        
        # Fetch agent card to build full metadata
        agent_card_data = None
        try:
            if HAS_AIOHTTP:
                async with aiohttp.ClientSession() as session:
                    async with session.get(agent_card_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 200:
                            agent_card_data = await response.json()
            else:
                card_req = urllib.request.Request(agent_card_url, method='GET')
                with urllib.request.urlopen(card_req, timeout=5) as response:
                    agent_card_data = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            logger.warning(f"[ONCHAIN REGISTRATION] Could not fetch agent card: {e}, using minimal metadata")
        
        # Build minimal metadata JSON for on-chain registration
        # Full metadata is stored in tokenURI, on-chain metadata is minimal
        labels = {"category": "compute", "type": "trader"}  # Default labels
        agent_card = agent_card_data or {"name": "A2A Agent", "description": "", "url": agent_card_url}
        metadata_json = {
            "name": agent_card.get("name", "A2A Agent"),
            "category": labels.get("category", "compute"),
            "type": labels.get("type", "trader"),
        }
        
        # Official contract: register(string tokenUri, MetadataEntry[] metadata)
        # MetadataEntry is {string key, bytes value} - format matches viem's toHex output
        # According to ERC-8004 spec, on-chain metadata examples are "agentWallet" or "agentName"
        # We store essential metadata on-chain for composability, but keep detailed data in tokenURI
        metadata = [
            # Store agent name on-chain (as per ERC-8004 spec example)
            {"key": "agentName", "value": Web3.to_hex(text=metadata_json.get("name", "A2A Agent"))},
            # Store category and type for filtering/discovery (custom keys, but useful for composability)
            {"key": "category", "value": Web3.to_hex(text=metadata_json.get("category", "compute"))},
            {"key": "type", "value": Web3.to_hex(text=metadata_json.get("type", "trader"))},
        ]
        # Note: agentId is already the ERC-721 tokenId, so we don't store it as metadata
        # Description and other details are in the tokenURI registration file, not on-chain
        
        # Store full metadata JSON for later use (e.g., in event sync)
        logger.debug(f"[ONCHAIN REGISTRATION] Full metadata JSON: {json.dumps(metadata_json, indent=2)}")

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
        
        # Handle both bytes and HexBytes types for tx_hash
        tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
        logger.info(f"[ONCHAIN REGISTRATION] On-chain registration submitted! TX: {tx_hash_str}")
        
        # Wait for confirmation
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            logger.info(f"[ONCHAIN REGISTRATION] On-chain registration confirmed! Block: {receipt.blockNumber}")
            
            # Extract agent ID from Registered event
            onchain_id = extract_agent_id_from_receipt(contract, receipt)
            
            # Fallback: query contract if event parsing failed
            if onchain_id is None:
                logger.warning(f"[REGISTRATION] Could not extract agent ID from events, querying contract...")
                onchain_id = find_agent_id_by_owner(w3, contract, signer_address)

            # Handle NFT transfer if needed
            if onchain_id is not None:
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

            # Return (tx_hash, agent_id) tuple
            if onchain_id is not None:
                tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
                return (tx_hash_str, onchain_id)
            else:
                logger.error(f"[REGISTRATION] Registration succeeded but could not extract agent ID")
                return None
        else:
            logger.error(f"[REGISTRATION] On-chain registration failed! TX reverted.")
            return None
            
    except Exception as e:
        logger.error(f"[REGISTRATION] On-chain registration error: {e}")
        return None

