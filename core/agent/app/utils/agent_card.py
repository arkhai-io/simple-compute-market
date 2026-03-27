"""
Agent card utilities for building agent card data from configuration.
Shared by server (agent.py) and registration script (onchain_registration.py).
"""
import time
from typing import Optional


def build_agent_card_data(
    agent_name: str,
    base_url: str,
    description: Optional[str] = None
) -> dict:
    """
    Build agent card JSON data from configuration.
    Shared function used by both server (agent.py) and registration script.
    
    Args:
        agent_name: Agent display name (from AGENT_NAME env var, or AGENT_ID as fallback)
        base_url: Base URL of the agent (e.g., http://localhost:8000)
        description: Optional description (defaults to standard description)
    
    Returns:
        Agent card JSON dict matching A2A AgentCard format
    """
    return {
        "name": agent_name,
        "description": description or "A helpful AI assistant designed to trade compute resources with others.",
        "url": base_url,
        "version": "0.1.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [],
        "capabilities": {
            "streaming": True
        }
    }


def build_erc8004_registration_file(
    agent_card_data: dict,
    agent_id: Optional[int] = None,
    chain_id: Optional[int] = None,
    identity_registry: Optional[str] = None,
    supported_trust: Optional[list] = None
) -> dict:
    """
    Build ERC-8004 registration file JSON as per ERC-8004 spec.
    
    The registration file MUST have:
    - type: "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    - name, description, image (for ERC-721 compatibility)
    - endpoints: array with A2A endpoint pointing to agent card
    - registrations: array with agentId and agentRegistry (if registered on-chain)
    - supportedTrust: array (optional)
    
    Args:
        agent_card_data: Agent card JSON data (from build_agent_card_data)
        agent_id: Optional on-chain numeric agent ID
        chain_id: Optional chain ID for registrations array
        identity_registry: Optional registry address for registrations array
        supported_trust: Optional list of supported trust models (e.g., ["reputation"])
    
    Returns:
        ERC-8004 registration file JSON dict
    """
    base_url = agent_card_data.get("url", "")
    agent_card_url = f"{base_url.rstrip('/')}/.well-known/agent-card.json"
    
    # Build endpoints array - A2A endpoint points to agent card
    endpoints = [
        {
            "name": "A2A",
            "endpoint": agent_card_url,
            "version": agent_card_data.get("version", "0.1.0")
        }
    ]
    
    # Add capabilities if available (for MCP endpoints)
    if agent_card_data.get("capabilities"):
        endpoints[0]["capabilities"] = agent_card_data["capabilities"]
    
    # Build registrations array if we have on-chain registration info
    registrations = []
    if agent_id is not None and chain_id is not None and identity_registry:
        registrations.append({
            "agentId": agent_id,
            "agentRegistry": f"eip155:{chain_id}:{identity_registry.lower()}"
        })
    
    # Build registration file
    registration_file = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": agent_card_data.get("name", "A2A Agent"),
        "description": agent_card_data.get("description", ""),
        "endpoints": endpoints,
        "updatedAt": int(time.time()),
    }
    
    # Add image if available (for ERC-721 compatibility)
    if agent_card_data.get("image"):
        registration_file["image"] = agent_card_data["image"]
    
    # Add registrations array if we have on-chain info (SHOULD have at least one per spec)
    if registrations:
        registration_file["registrations"] = registrations
    
    # Add supportedTrust if provided (OPTIONAL per spec)
    if supported_trust:
        registration_file["supportedTrust"] = supported_trust
    
    return registration_file

