"""Utility functions for API routes."""

import json
import time
import logging
import asyncio
import hashlib
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from src.db.models import Agent, Listing, OrderStatusEnum

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


def _verify_eip191_signature(message: str, signature: str, expected_owner: str) -> bool:
    """Low-level EIP-191 signature verification. Recovers signer and checks against expected_owner."""
    if not HAS_ETH_ACCOUNT:
        return False
    try:
        message_hash = encode_defunct(text=message)
        recovered = Account.recover_message(message_hash, signature=signature)
        return recovered.lower() == expected_owner.lower()
    except Exception as e:
        logger.error(f"[VERIFY] EIP-191 verification error: {e}")
        return False


def verify_heartbeat_signature(agent_id: str, timestamp: int, signature: str, owner_address: str) -> bool:
    """Verify heartbeat signature. Message format: 'heartbeat:{agent_id}:{timestamp}'"""
    if not HAS_ETH_ACCOUNT:
        logger.warning("[Heartbeat] eth_account not available, signature verification disabled")
        return False
    message = f"heartbeat:{agent_id}:{timestamp}"
    logger.info(f"[Heartbeat] Verifying for agent={agent_id} owner={owner_address}")
    is_valid = _verify_eip191_signature(message, signature, owner_address)
    logger.info(f"[Heartbeat] Signature valid: {is_valid}")
    return is_valid


def verify_order_signature(operation: str, resource_id: str, timestamp: int, signature: str, owner_address: str) -> bool:
    """Verify a listing mutation signature.

    Message format: '{operation}:{resource_id}:{timestamp}'
    operation: 'create_listing', 'update_listing', or 'delete_listing'
    resource_id: agent_id for create_listing, listing_id for update/delete
    """
    if not HAS_ETH_ACCOUNT:
        logger.warning("[Order] eth_account not available, signature verification disabled")
        return False
    message = f"{operation}:{resource_id}:{timestamp}"
    logger.info(f"[Order] Verifying {operation} for resource={resource_id} owner={owner_address}")
    is_valid = _verify_eip191_signature(message, signature, owner_address)
    logger.info(f"[Order] Signature valid: {is_valid}")
    return is_valid


_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


async def ensure_agent_indexed(db: Session, agent_id: str) -> Optional[Agent]:
    """Return the Agent row for ``agent_id``, JIT-indexing from chain if missing.

    The indexer never pre-walks the chain. The first publish/heartbeat/lookup
    for a given canonical_id triggers this helper:

      1. Try the local DB (``find_agent_by_id``).
      2. Parse the canonical ID. Reject if its (chain_id, registry_addr)
         components don't match this indexer's configured scope — that
         agent lives on a chain or registry this indexer can't verify.
      3. Call ``ownerOf(onchain_id)`` on chain. If it raises or returns the
         zero address, the agent isn't registered → return None (404).
      4. Call ``tokenURI(onchain_id)`` opportunistically (best-effort; no
         consumer reads it today, but storing it costs nothing).
      5. INSERT the new row. Race-safe: a unique constraint on
         (chain_id, identity_registry, onchain_agent_id) handles
         concurrent inserts via IntegrityError → re-query.
    """
    agent = find_agent_by_id(db, agent_id)
    if agent is not None:
        return agent

    try:
        chain_id, identity_registry_lower, onchain_agent_id = parse_erc8004_canonical_id(agent_id)
    except ValueError:
        return None

    from src.config import settings  # local import — avoids cycle at module load
    if chain_id != settings.chain_id:
        return None
    if identity_registry_lower != settings.identity_registry_address.lower():
        return None

    from src.services.chain_client import get_identity_registry
    client = get_identity_registry()

    try:
        owner = await asyncio.to_thread(client.get_owner, onchain_agent_id)
    except Exception as e:
        logger.info(
            f"[JIT] ownerOf({onchain_agent_id}) failed — likely not registered on-chain yet: {e}"
        )
        return None

    if not owner or owner == _ZERO_ADDRESS:
        return None

    token_uri: Optional[str] = None
    try:
        token_uri = await asyncio.to_thread(client.get_token_uri, onchain_agent_id)
    except Exception as e:
        logger.warning(f"[JIT] tokenURI({onchain_agent_id}) failed: {e}")

    canonical_id = build_erc8004_canonical_id_from_components(
        chain_id, identity_registry_lower, onchain_agent_id
    )

    agent = Agent(
        agent_id=canonical_id,
        chain_id=chain_id,
        identity_registry=identity_registry_lower,
        onchain_agent_id=onchain_agent_id,
        registry_address=identity_registry_lower,
        owner=owner,
        token_uri=token_uri or None,
        metadata_json={"onChainAgentId": onchain_agent_id},
    )
    db.add(agent)
    try:
        db.commit()
        db.refresh(agent)
    except IntegrityError:
        # Concurrent request inserted the same agent first. Re-query
        # under the now-committed row.
        db.rollback()
        return find_agent_by_id(db, canonical_id)

    logger.info(f"[JIT] Indexed agent {canonical_id} owner={owner}")
    return agent


async def refresh_agent_owner(db: Session, agent: Agent) -> Agent:
    """Re-fetch ``ownerOf`` from chain and update the row if it changed.

    Called when a signed publish/heartbeat fails verification — handles
    on-chain ownership transfers naturally. The agent NFT may have been
    transferred since we last cached its owner; refresh once and let the
    caller retry verification against the updated value.

    Best-effort: an RPC failure leaves the cached owner unchanged. The
    caller then returns 401 to the requester as normal.
    """
    from src.services.chain_client import get_identity_registry
    client = get_identity_registry()
    try:
        owner = await asyncio.to_thread(client.get_owner, agent.onchain_agent_id)
    except Exception as e:
        logger.warning(f"[JIT] refresh ownerOf({agent.onchain_agent_id}) failed: {e}")
        return agent

    if owner and owner.lower() != (agent.owner or "").lower():
        old = agent.owner
        agent.owner = owner
        db.commit()
        db.refresh(agent)
        logger.info(f"[JIT] Refreshed owner for {agent.agent_id}: {old} → {owner}")
    return agent


def find_agent_by_id(db: Session, agent_id: str) -> Optional[Agent]:
    """Find agent by ID.

    Accepts three input shapes:
      1. Full ERC-8004 canonical ID (``eip155:<chain>:<registry>:<n>``) —
         exact match.
      2. Same canonical shape with a different-cased registry address —
         re-parsed and looked up by components.
      3. Bare numeric ``onchain_agent_id`` — composed with the registry's
         configured ``chain_id`` and ``identity_registry_address`` and
         looked up by components. This makes URL-encoded canonical IDs
         optional in the common single-chain-per-registry deployment.
    """

    # 1. Try canonical ID (exact match)
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    if agent:
        return agent

    # 2. Parse canonical and look up by components — handles address-case
    # differences between the URL and what's stored.
    try:
        chain_id, identity_registry, onchain_agent_id = parse_erc8004_canonical_id(agent_id)
        identity_registry_lower = identity_registry.lower()
        agent = db.query(Agent).filter(
            and_(
                Agent.chain_id == chain_id,
                Agent.identity_registry == identity_registry_lower,
                Agent.onchain_agent_id == onchain_agent_id
            )
        ).first()
        if agent:
            return agent
    except ValueError:
        pass

    # 3. Bare numeric fallback. A registry indexes one (chain, registry)
    # tuple, so onchain_agent_id alone is effectively unique. Construct
    # the canonical form from the registry's config and retry.
    if agent_id.isdigit():
        try:
            from src.config import settings  # local import to avoid cycles
            onchain_agent_id_int = int(agent_id)
            agent = db.query(Agent).filter(
                and_(
                    Agent.chain_id == settings.chain_id,
                    Agent.identity_registry == settings.identity_registry_address.lower(),
                    Agent.onchain_agent_id == onchain_agent_id_int,
                )
            ).first()
            if agent:
                return agent
        except (ValueError, ImportError):
            pass

    return None


def order_to_dict(listing: Listing) -> dict:
    """Convert a Listing ORM row to its wire-shape dict."""
    return {
        "listing_id": listing.listing_id,
        "agent_id": listing.agent_id,
        "seller": listing.seller,
        "buyer": listing.buyer,
        "offer_resource": listing.offer_resource or {},
        "accepted_escrows": listing.accepted_escrows or [],
        "max_duration_seconds": listing.max_duration_seconds,
        "oracle_address": listing.oracle_address,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


def validate_order_status(status: str) -> OrderStatusEnum:
    """Validate and convert string status to OrderStatusEnum"""
    try:
        return OrderStatusEnum(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")


