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


def build_agent_card_url(base_url: str) -> str:
    """
    Build the agent card URL (token_uri) consistently.
    
    Args:
        base_url: Base URL of the agent (e.g., http://localhost:8000)
    
    Returns:
        Agent card URL (e.g., http://localhost:8000/.well-known/agent-card.json)
    """
    return f"{base_url.rstrip('/')}/.well-known/agent-card.json"




async def update_existing_agent(
    contract,
    account,
    agent_id: int,
    desired_token_uri: str,
    desired_metadata: list,
    w3,
    private_key: str
) -> Tuple[Optional[str], dict]:
    """
    Update existing agent if changes detected.
    
    Args:
        contract: Web3 contract instance
        account: Web3 account instance
        agent_id: Existing agent ID
        desired_token_uri: Desired token URI (agent card URL)
        desired_metadata: List of desired metadata dicts with 'key' and 'value' (hex-encoded)
        w3: Web3 instance
        private_key: Private key for signing transactions
        
    Returns:
        Tuple of (last_tx_hash_if_updated, updates_dict) where updates_dict indicates what was updated:
        {
            'token_uri_updated': bool,
            'metadata_updated': list of updated keys,
            'no_changes': bool
        }
    """
    updates = {
        'token_uri_updated': False,
        'metadata_updated': [],
        'no_changes': True
    }
    last_tx_hash = None
    
    try:
        # Fetch current token URI from contract
        current_token_uri = contract.functions.tokenURI(agent_id).call()
        
        # Normalize URIs for comparison (strip trailing slashes, handle http/https)
        def normalize_uri(uri: str) -> str:
            uri = uri.rstrip('/')
            # Normalize http/https (optional - uncomment if needed)
            # uri = uri.replace('https://', 'http://')
            return uri
        
        normalized_current = normalize_uri(current_token_uri)
        normalized_desired = normalize_uri(desired_token_uri)
        
        logger.debug(f"[UPDATE] Current token URI: {current_token_uri}")
        logger.debug(f"[UPDATE] Desired token URI: {desired_token_uri}")
        
        # Compare normalized token URIs
        if normalized_current != normalized_desired:
            logger.info(f"[UPDATE] Token URI changed: {current_token_uri} -> {desired_token_uri}")
            try:
                # Call setAgentUri
                tx = contract.functions.setAgentUri(agent_id, desired_token_uri).build_transaction({
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "gas": 200000,
                    "gasPrice": w3.eth.gas_price,
                })
                
                signed_tx = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
                
                # Wait for confirmation
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info(f"[UPDATE] ✓ Token URI updated! TX: {tx_hash_str}")
                    updates['token_uri_updated'] = True
                    updates['no_changes'] = False
                    last_tx_hash = tx_hash_str
                else:
                    logger.error(f"[UPDATE] ✗ Token URI update failed! TX reverted.")
            except Exception as e:
                logger.error(f"[UPDATE] Error updating token URI: {e}")
        else:
            logger.debug(f"[UPDATE] Token URI unchanged")
        
        # Fetch current metadata and compare
        for desired_meta in desired_metadata:
            key = desired_meta['key']
            desired_value_hex = desired_meta['value']
            
            try:
                # Fetch current metadata value (returns bytes)
                current_value_bytes = contract.functions.getMetadata(agent_id, key).call()
                
                # Convert desired hex string to bytes for comparison
                # Web3.to_hex returns hex string with '0x' prefix, so we need to handle that
                if isinstance(desired_value_hex, str):
                    if desired_value_hex.startswith('0x'):
                        desired_value_bytes = bytes.fromhex(desired_value_hex[2:])
                    else:
                        desired_value_bytes = bytes.fromhex(desired_value_hex)
                else:
                    desired_value_bytes = desired_value_hex
                
                # Compare bytes
                if current_value_bytes != desired_value_bytes:
                    logger.info(f"[UPDATE] Metadata key '{key}' changed")
                    try:
                        # Call setMetadata - contract expects bytes value
                        tx = contract.functions.setMetadata(agent_id, key, desired_value_bytes).build_transaction({
                            "from": account.address,
                            "nonce": w3.eth.get_transaction_count(account.address),
                            "gas": 200000,
                            "gasPrice": w3.eth.gas_price,
                        })
                        
                        signed_tx = account.sign_transaction(tx)
                        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                        tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
                        
                        # Wait for confirmation
                        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                        if receipt.status == 1:
                            logger.info(f"[UPDATE] ✓ Metadata key '{key}' updated! TX: {tx_hash_str}")
                            updates['metadata_updated'].append(key)
                            updates['no_changes'] = False
                            last_tx_hash = tx_hash_str
                        else:
                            logger.error(f"[UPDATE] ✗ Metadata key '{key}' update failed! TX reverted.")
                    except Exception as e:
                        logger.error(f"[UPDATE] Error updating metadata key '{key}': {e}")
                else:
                    logger.debug(f"[UPDATE] Metadata key '{key}' unchanged")
            except Exception as e:
                # Metadata key might not exist yet, treat as changed
                logger.debug(f"[UPDATE] Metadata key '{key}' not found on-chain (or error): {e}, will update")
                try:
                    # Convert desired hex to bytes
                    if isinstance(desired_value_hex, str):
                        if desired_value_hex.startswith('0x'):
                            desired_value_bytes = bytes.fromhex(desired_value_hex[2:])
                        else:
                            desired_value_bytes = bytes.fromhex(desired_value_hex)
                    else:
                        desired_value_bytes = desired_value_hex
                    
                    # Call setMetadata
                    tx = contract.functions.setMetadata(agent_id, key, desired_value_bytes).build_transaction({
                        "from": account.address,
                        "nonce": w3.eth.get_transaction_count(account.address),
                        "gas": 200000,
                        "gasPrice": w3.eth.gas_price,
                    })
                    
                    signed_tx = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
                    
                    # Wait for confirmation
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    if receipt.status == 1:
                        logger.info(f"[UPDATE] ✓ Metadata key '{key}' set! TX: {tx_hash_str}")
                        updates['metadata_updated'].append(key)
                        updates['no_changes'] = False
                        last_tx_hash = tx_hash_str
                    else:
                        logger.error(f"[UPDATE] ✗ Metadata key '{key}' set failed! TX reverted.")
                except Exception as e2:
                    logger.error(f"[UPDATE] Error setting metadata key '{key}': {e2}")
        
        if updates['no_changes']:
            logger.info(f"[UPDATE] ✓ No changes detected for agent {agent_id}")
        
        return (last_tx_hash, updates)
        
    except Exception as e:
        logger.error(f"[UPDATE] Error in update_existing_agent: {e}")
        return (None, updates)


async def register_onchain(
    agent_card_url: str,
    private_key: str,
    rpc_url: str,
    contract_address: str,
    owner_address: Optional[str] = None,
    explicit_agent_id: Optional[str] = None,
    indexer_url: Optional[str] = None,
    agent_name: Optional[str] = None
) -> Optional[Tuple[str, int, Optional[dict]]]:
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
        agent_name: Optional agent name (from AGENT_ID env var). If not provided, uses agent card name or "A2A Agent"
        
    Returns:
        Tuple of (tx_hash, agent_id, updates_dict) if successful, None otherwise
        - For new registrations: (tx_hash, agent_id, None)
        - For existing agents with updates: (tx_hash, agent_id, updates_dict) where tx_hash is the last update transaction hash
        - For existing agents with no changes: (None, agent_id, updates_dict) where updates_dict['no_changes'] is True
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
        
        try:
            w3 = Web3(HTTPProvider(http_url, request_kwargs={'timeout': 10}))
            if not w3.is_connected():
                logger.error(f"[REGISTRATION] Cannot connect to RPC at {http_url} (original: {rpc_url})")
                logger.error(f"[REGISTRATION] Please ensure your blockchain node is running and accessible")
                return None
        except Exception as conn_error:
            logger.error(f"[REGISTRATION] RPC connection error: {conn_error}")
            logger.error(f"[REGISTRATION] Failed to connect to {http_url} (original: {rpc_url})")
            logger.error(f"[REGISTRATION] Please check:")
            logger.error(f"[REGISTRATION]   1. Is your blockchain node running?")
            logger.error(f"[REGISTRATION]   2. Is the RPC URL correct?")
            logger.error(f"[REGISTRATION]   3. Is the port accessible?")
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
                # Handle both numeric ID and canonical ID formats
                if explicit_agent_id.startswith("eip155:"):
                    # Extract numeric agent ID from canonical ID format: eip155:{chainId}:{registry}:{agentId}
                    parts = explicit_agent_id.split(":")
                    if len(parts) == 4:
                        agent_id = int(parts[3])
                        logger.info(f"[REGISTRATION] Extracted numeric agent ID {agent_id} from canonical ID {explicit_agent_id}")
                    else:
                        raise ValueError(f"Invalid canonical ID format: {explicit_agent_id}")
                else:
                    # Assume it's a numeric ID
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
        
        # Build agent card from config (server may not be running yet)
        # Try to fetch from URL first, fallback to building from config
        agent_card_data = None
        try:
            if HAS_AIOHTTP:
                async with aiohttp.ClientSession() as session:
                    async with session.get(agent_card_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 200:
                            agent_card_data = await response.json()
                            logger.debug(f"[REGISTRATION] Fetched agent card from {agent_card_url}")
            else:
                card_req = urllib.request.Request(agent_card_url, method='GET')
                with urllib.request.urlopen(card_req, timeout=5) as response:
                    agent_card_data = json.loads(response.read().decode('utf-8'))
                    logger.debug(f"[REGISTRATION] Fetched agent card from {agent_card_url}")
        except Exception as e:
            logger.info(f"[REGISTRATION] Could not fetch agent card from URL (server may not be running): {e}")
            logger.info(f"[REGISTRATION] Building agent card from configuration...")
        
        # Build agent card from config if fetch failed
        if agent_card_data is None:
            # Import shared function to build agent card from config
            from ...utils.agent_card import build_agent_card_data
            from ...utils.config import get_agent_id, DEFAULT_AGENT_ID
            base_url = agent_card_url.replace("/.well-known/agent-card.json", "")
            # Prioritize agent_name parameter, then AGENT_ID env var (with validation), then default
            if agent_name:
                final_agent_id = agent_name
            else:
                try:
                    final_agent_id = get_agent_id()
                except ValueError:
                    # If validation fails, use default
                    final_agent_id = DEFAULT_AGENT_ID
            agent_card_data = build_agent_card_data(
                agent_id=final_agent_id,
                base_url=base_url
            )
        
        # Build metadata for on-chain storage
        # Use agent_name parameter if provided, otherwise from agent card, otherwise default
        from ...utils.config import DEFAULT_AGENT_ID
        final_agent_name = agent_name or agent_card_data.get("name", DEFAULT_AGENT_ID)
        labels = {"category": "compute", "type": "trader"}  # Default labels
        
        # Official contract: register(string tokenUri, MetadataEntry[] metadata)
        # MetadataEntry is {string key, bytes value} - format matches viem's toHex output
        # Store essential metadata on-chain for composability (minimal to save gas)
        metadata = [
            # Store agent name on-chain (as per ERC-8004 spec example)
            # Uses AGENT_ID env var if provided, otherwise from agent card, otherwise "A2A Agent"
            {"key": "agentName", "value": Web3.to_hex(text=final_agent_name)},
            # Store category and type for filtering/discovery
            {"key": "category", "value": Web3.to_hex(text=labels.get("category", "compute"))},
            {"key": "type", "value": Web3.to_hex(text=labels.get("type", "trader"))},
        ]
        
        # If we found an existing agent ID, check for changes and update if needed (idempotent)
        # CRITICAL: Use 'is not None' instead of truthy check because agent_id 0 is valid!
        if agent_id is not None:
            logger.info(f"[REGISTRATION] ✓ Agent already registered with ID: {agent_id}")
            logger.info(f"[REGISTRATION] Checking for changes and updating if needed...")

            # Update existing agent if changes detected
            update_tx_hash, updates = await update_existing_agent(
                contract=contract,
                account=account,
                agent_id=agent_id,
                desired_token_uri=agent_card_url,
                desired_metadata=metadata,
                w3=w3,
                private_key=private_key
            )
            
            if updates['no_changes']:
                logger.info(f"[REGISTRATION] ✓ No changes detected, using existing agent ID {agent_id}")
            else:
                if updates['token_uri_updated']:
                    logger.info(f"[REGISTRATION] ✓ Token URI updated")
                if updates['metadata_updated']:
                    logger.info(f"[REGISTRATION] ✓ Metadata keys updated: {', '.join(updates['metadata_updated'])}")
            
            # Return (tx_hash_if_updated, agent_id, updates_dict) - tx_hash is None if no updates were made
            return (update_tx_hash, agent_id, updates)
        
        # No existing registration found, register new
        logger.info(f"[ONCHAIN REGISTRATION] Registering new agent on-chain...")
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

            # Return (tx_hash, agent_id, None) tuple - None indicates new registration
            if onchain_id is not None:
                tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
                return (tx_hash_str, onchain_id, None)
            else:
                logger.error(f"[REGISTRATION] Registration succeeded but could not extract agent ID")
                return None
        else:
            logger.error(f"[REGISTRATION] On-chain registration failed! TX reverted.")
            return None
            
    except Exception as e:
        logger.error(f"[REGISTRATION] On-chain registration error: {e}")
        return None

