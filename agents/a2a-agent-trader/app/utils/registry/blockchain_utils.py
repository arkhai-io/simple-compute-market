"""
Blockchain utilities for agent registration.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_erc8004_canonical_id(chain_id: int, identity_registry: str, agent_id: int) -> str:
    """
    Build ERC-8004 canonical ID from components.
    
    Format: eip155:{chainId}:{identityRegistry}:{agentId}
    
    Args:
        chain_id: Chain ID (e.g., 1337 for Anvil)
        identity_registry: Registry contract address (will be normalized to lowercase)
        agent_id: Numeric ERC-721 tokenId
    
    Returns:
        Canonical ID string with lowercase address
    """
    normalized_registry = identity_registry.lower()
    return f"eip155:{chain_id}:{normalized_registry}:{agent_id}"


def find_agent_id_by_owner(w3, contract, owner_address: str) -> Optional[int]:
    """
    Find agent ID by checking balance.
    
    Args:
        w3: Web3 instance
        contract: Contract instance
        owner_address: Owner wallet address
    
    Returns:
        Agent ID if found, None otherwise
    """
    try:
        balance = contract.functions.balanceOf(owner_address).call()
        if balance == 0:
            return None
        
        # Find the first token owned by this address
        for token_id in range(balance + 10):
            try:
                if contract.functions.ownerOf(token_id).call().lower() == owner_address.lower():
                    return int(token_id)
            except Exception:
                continue
        return None
    except Exception as e:
        logger.warning(f"[BLOCKCHAIN] Could not find agent for owner: {e}")
        return None


def extract_agent_id_from_receipt(contract, receipt) -> Optional[int]:
    """
    Extract agent ID from transaction receipt.
    
    Args:
        contract: Contract instance
        receipt: Transaction receipt
    
    Returns:
        Agent ID if found, None otherwise
    """
    for log in receipt.logs:
        try:
            event = contract.events.Registered().process_log(log)
            if event:
                # Try different ways to access agentId (handles different web3.py versions)
                agent_id_value = None
                if hasattr(event.args, 'agentId'):
                    agent_id_value = event.args.agentId
                elif hasattr(event.args, 'agent_id'):
                    agent_id_value = event.args.agent_id
                elif isinstance(event.args, dict):
                    agent_id_value = event.args.get('agentId') or event.args.get('agent_id')
                elif isinstance(event.args, (list, tuple)) and len(event.args) > 0:
                    agent_id_value = event.args[0]
                
                if agent_id_value is not None:
                    return int(agent_id_value)
        except Exception as e:
            # Log the exception for debugging but continue trying other logs
            logger.debug(f"[BLOCKCHAIN] Error parsing event log: {e}")
            continue
    return None

