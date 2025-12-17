"""Utility functions for API routes."""

import json
import time
import logging
import asyncio
import aiohttp
import hashlib
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.types import AgentCard, ERC8004RegistrationFile, Endpoint
from src.db.models import Agent, MarketOrder, OrderStatusEnum

# Import for signature verification
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

logger = logging.getLogger(__name__)


def build_erc8004_canonical_id_from_components(chain_id: int, identity_registry: str, agent_id: int) -> str:
    """
    Build ERC-8004 canonical ID from components.
    
    Format: eip155:{chainId}:{identityRegistry}:{agentId}
    
    Args:
        chain_id: Chain ID (e.g., 1337 for Anvil, 84532 for Base Sepolia)
        identity_registry: Registry contract address (will be normalized to lowercase)
        agent_id: Numeric ERC-721 tokenId
    
    Returns:
        Canonical ID string with lowercase address
    """
    normalized_registry = identity_registry.lower()
    return f"eip155:{chain_id}:{normalized_registry}:{agent_id}"


def parse_erc8004_canonical_id(canonical_id: str) -> tuple[int, str, int]:
    """
    Parse ERC-8004 canonical ID into components.
    
    Format: eip155:{chainId}:{identityRegistry}:{agentId}
    
    Args:
        canonical_id: Canonical ID string (e.g., "eip155:1337:0xRegistry:22")
    
    Returns:
        Tuple of (chain_id, identity_registry, onchain_agent_id)
    
    Raises:
        ValueError: If canonical ID format is invalid
    """
    if not canonical_id or not canonical_id.startswith("eip155:"):
        raise ValueError(f"Invalid canonical ID format: must start with 'eip155:'")
    
    parts = canonical_id.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid canonical ID format: expected 'eip155:chainId:registry:agentId', got {canonical_id}")
    
    namespace, chain_id_str, identity_registry, agent_id_str = parts
    
    if namespace != "eip155":
        raise ValueError(f"Invalid namespace: expected 'eip155', got '{namespace}'")
    
    try:
        chain_id = int(chain_id_str)
        onchain_agent_id = int(agent_id_str)
    except ValueError as e:
        raise ValueError(f"Invalid canonical ID: chainId and agentId must be integers: {e}")
    
    if not identity_registry.startswith("0x") or len(identity_registry) != 42:
        raise ValueError(f"Invalid registry address format: {identity_registry}")
    
    # Normalize registry address to lowercase for consistent comparison
    identity_registry = identity_registry.lower()
    
    return (chain_id, identity_registry, onchain_agent_id)


async def fetch_registration_file(url: str) -> dict:
    """Fetch registration file from URL"""
    timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to fetch registration file from {url}: {response.status}"
                    )
                return await response.json()
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=408,
                detail=f"Timeout fetching registration file from {url}"
            )


def convert_agent_card_to_registration_file(
    agent_card: AgentCard,
    owner: str,
    labels: dict
) -> ERC8004RegistrationFile:
    """Convert legacy agent_card format to ERC-8004 registration file format"""
    # Extract A2A endpoint from agent card
    endpoints = []
    if agent_card.url:
        a2a_endpoint = Endpoint(
            name="A2A",
            endpoint=str(agent_card.url),
            version=agent_card.version,
            a2a_skills=[skill.id for skill in agent_card.skills] if agent_card.skills else []
        )
        endpoints.append(a2a_endpoint)
    
    return ERC8004RegistrationFile(
        type="https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        name=agent_card.name,
        description=agent_card.description,
        image=None,
        endpoints=endpoints,
        registrations=[],
        supported_trust=[],
        active=True,
        x402support=False,
        updated_at=int(time.time())
    )


def verify_heartbeat_signature(agent_id: str, timestamp: int, signature: str, owner_address: str) -> bool:
    """Verify heartbeat signature using EIP-191 personal sign format"""
    if not HAS_ETH_ACCOUNT:
        logger.warning("[Heartbeat] eth_account not available, signature verification disabled")
        return False

    try:
        # Construct the message that should have been signed
        message = f"heartbeat:{agent_id}:{timestamp}"
        logger.info(f"[Heartbeat] Verifying signature for agent: {agent_id}")
        logger.info(f"[Heartbeat] Expected message: {message}")
        logger.info(f"[Heartbeat] Expected owner: {owner_address}")
        logger.info(f"[Heartbeat] Received signature: {signature}")

        # Encode message in EIP-191 format
        message_hash = encode_defunct(text=message)

        # Recover the signer address from the signature
        recovered_address = Account.recover_message(message_hash, signature=signature)
        logger.info(f"[Heartbeat] Recovered address: {recovered_address}")

        # Verify it matches the agent's owner address
        is_valid = recovered_address.lower() == owner_address.lower()
        logger.info(f"[Heartbeat] Signature valid: {is_valid}")
        return is_valid
    except Exception as e:
        logger.error(f"[Heartbeat] Signature verification error: {e}")
        return False


def verify_registration_signature(
    owner: str,
    timestamp: int,
    signature: str,
    registration_data: dict
) -> bool:
    """
    Verify registration signature using EIP-191 personal sign format.

    Message format: "register:{owner}:{timestamp}:{hash_of_registration_data}"

    Args:
        owner: Owner wallet address
        timestamp: Unix timestamp
        signature: EIP-191 signature
        registration_data: Registration data dictionary (sorted for consistent hashing)

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        import hashlib
        import json

        # Check timestamp is within 5 minutes
        current_time = int(time.time())
        if abs(current_time - timestamp) > 300:  # 5 minutes
            logger.warning(f"[Registration] Timestamp too old or in future: {timestamp}, current: {current_time}")
            return False

        # Create deterministic hash of registration data
        # Remove signature and timestamp from data to create hash
        data_to_hash = {k: v for k, v in registration_data.items()
                       if k not in ['signature', 'timestamp']}

        # Convert Pydantic models to dictionaries for serialization
        def serialize_registration_data(obj):
            if hasattr(obj, 'model_dump'):
                return obj.model_dump()
            elif isinstance(obj, dict):
                return {k: serialize_registration_data(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [serialize_registration_data(item) for item in obj]
            elif hasattr(obj, '__class__') and 'HttpUrl' in str(type(obj)):
                return str(obj)
            else:
                return obj

        serializable_data = serialize_registration_data(data_to_hash)

        # Sort keys for consistent ordering - keep A2A agent card in camelCase (protocol compliant)
        data_str = json.dumps(serializable_data, sort_keys=True, separators=(',', ':'))
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]

        # Verify signature
        message = f"register:{owner}:{timestamp}:{data_hash}"
        message_hash = encode_defunct(text=message)

        # Ensure signature has 0x prefix and is proper format
        if not signature.startswith('0x'):
            signature = '0x' + signature

        recovered_address = Account.recover_message(message_hash, signature=signature)
        logger.info(f"[Registration] Signature format check: original={len(signature)} chars, with prefix={signature[:10]}...")

        logger.info(f"[Registration] Verifying signature for owner {owner}")
        logger.info(f"[Registration] Expected message: {message}")
        logger.info(f"[Registration] Data to hash: {data_str}")
        logger.info(f"[Registration] Data hash: {data_hash}")
        logger.info(f"[Registration] Received signature: {signature}")
        logger.info(f"[Registration] Recovered address: {recovered_address}")
        logger.info(f"[Registration] Expected owner: {owner}")
        logger.info(f"[Registration] Address match: {recovered_address.lower() == owner.lower()}")

        return recovered_address.lower() == owner.lower()
    except Exception as e:
        logger.error(f"[Registration] Signature verification error: {e}")
        return False


def get_resource_type(resource: dict) -> str:
    """Determine if resource is compute or token"""
    if "token" in resource:
        return "token"
    elif "gpu_model" in resource:
        return "compute"
    return "unknown"


def resources_match(resource1: dict, resource2: dict) -> bool:
    """Check if two resources match (deep comparison of JSON fields)"""
    import json
    # Normalize JSON for comparison
    return json.dumps(resource1, sort_keys=True) == json.dumps(resource2, sort_keys=True)


def find_agent_by_id(db: Session, agent_id: str) -> Optional[Agent]:
    """Find agent by ID (supports canonical ID format)"""
    
    # Try canonical ID (exact match)
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent:
        return agent
    
    # Fallback: parse canonical ID and lookup by components
    # This handles case where canonical ID format differs (e.g., address case)
    try:
        chain_id, identity_registry, onchain_agent_id = parse_erc8004_canonical_id(agent_id)
        # Normalize identity_registry to lowercase for comparison
        identity_registry_lower = identity_registry.lower()
        agent = db.query(Agent).filter(
            and_(
                Agent.chain_id == chain_id,
                Agent.identity_registry == identity_registry_lower,
                Agent.onchain_agent_id == onchain_agent_id
            )
        ).first()
        return agent
    except ValueError:
        return None


def order_to_dict(order: MarketOrder) -> dict:
    """Convert MarketOrder model to API response dict"""
    return {
        "order_id": order.order_id,
        "agent_id": order.agent_id,
        "order_maker": order.order_maker,
        "order_taker": order.order_taker,
        "offer_resource": order.offer_resource or {},
        "demand_resource": order.demand_resource or {},
        "duration": order.duration,
        "maker_attestation": order.maker_attestation,
        "taker_attestation": order.taker_attestation,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def validate_order_status(status: str) -> OrderStatusEnum:
    """Validate and convert string status to OrderStatusEnum"""
    try:
        return OrderStatusEnum(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")


def matches_resource_filters(
    order: MarketOrder,
    offer_resource_type: Optional[str] = None,
    demand_resource_type: Optional[str] = None,
    region: Optional[str] = None,
    gpu_model: Optional[str] = None,
    sla: Optional[float] = None,
    bidirectional: bool = False,
) -> bool:
    """Check if order matches resource filters"""
    offer_res = order.offer_resource or {}
    demand_res = order.demand_resource or {}
    
    # Resource type filtering (skip if bidirectional)
    if not bidirectional:
        if offer_resource_type:
            if get_resource_type(offer_res) != offer_resource_type.lower():
                return False
        if demand_resource_type:
            if get_resource_type(demand_res) != demand_resource_type.lower():
                return False
    
    # Region filtering - applies to both directions
    if region:
        if offer_res.get("region") != region and demand_res.get("region") != region:
            return False
    
    # GPU model filtering - applies to both directions
    if gpu_model:
        if offer_res.get("gpu_model") != gpu_model and demand_res.get("gpu_model") != gpu_model:
            return False
    
    # SLA filtering - applies to both directions
    if sla is not None:
        if offer_res.get("sla") != sla and demand_res.get("sla") != sla:
            return False
    
    return True


def find_symmetric_order(db: Session, order: MarketOrder, original_offer_resource: dict, original_demand_resource: dict) -> Optional[MarketOrder]:
    """Find the symmetric order for a given order.
    
    A symmetric order is one where:
    - offer_resource == original_order.demand_resource
    - demand_resource == original_order.offer_resource
    - order_maker == original_order.order_taker (the agent accepting)
    """
    if not order.order_taker:  # Only look for symmetric order if we have a taker
        return None
    
    symmetric_orders = db.query(MarketOrder).filter(
        and_(
            MarketOrder.order_id != order.order_id,  # Not the same order
            MarketOrder.order_maker == order.order_taker,  # Maker is the taker of original order
        )
    ).all()
    
    # Find the one where resources are swapped
    for candidate in symmetric_orders:
        if (resources_match(candidate.offer_resource, original_demand_resource) and
            resources_match(candidate.demand_resource, original_offer_resource)):
            return candidate
    
    return None
