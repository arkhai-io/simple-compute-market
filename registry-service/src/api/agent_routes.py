"""Agent-related API routes."""

import logging
import time
import urllib.parse
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db.database import get_db
from src.db.models import Agent, AgentMetadataEntry
from src.types import HeartbeatRequest
from src.api.utils import (
    ensure_agent_indexed,
    refresh_agent_owner,
    verify_heartbeat_signature,
    find_agent_by_id,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agents/search")
async def search_agents(
    q: str = Query(..., description="Search query"),
    endpoint_type: Optional[str] = Query(None, description="Filter by endpoint type"),
    db: Session = Depends(get_db),
):
    """Search agents with optional endpoint type filter"""
    if not q:
        return {"items": []}

    # Simple search - in production, implement full-text search
    agents = db.query(Agent).filter(
        Agent.agent_id.contains(q)
    ).limit(50).all()

    items = []
    for agent in agents:
        metadata = agent.metadata_json or {}
        
        # Filter by endpoint type if specified
        if endpoint_type:
            endpoints = metadata.get("endpoints", [])
            has_endpoint = any(
                ep.get("name", "").upper() == endpoint_type.upper()
                for ep in endpoints
            )
            if not has_endpoint:
                continue
        
        # Extract endpoint URLs
        endpoints = metadata.get("endpoints", [])
        a2a_url = None
        for ep in endpoints:
            ep_name = ep.get("name", "") if isinstance(ep, dict) else getattr(ep, "name", "")
            if ep_name.upper() == "A2A":
                a2a_url = ep.get("endpoint") if isinstance(ep, dict) else getattr(ep, "endpoint", None)
        
        items.append({
            "id": agent.id,  # Integer PK
            "agentId": agent.agent_id,  # Single agentId field (canonical format)
            "name": metadata.get("name", "Unknown"),
            "status": agent.health_status,
            "url": a2a_url or agent.token_uri,
            "tokenURI": agent.token_uri,
        })

    return {"items": items}


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format or integer PK)"),
    db: Session = Depends(get_db),
):
    """Get agent by ID (expects canonical eip155:... format).

    First call for a canonical_id triggers JIT indexing from chain
    (ownerOf + tokenURI). Returns 404 only if the agent isn't registered
    on-chain at all or is outside this indexer's (chain, registry) scope.
    """
    agent = await ensure_agent_indexed(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get all metadata (using canonical agent_id for FK lookup)
    metadata = db.query(AgentMetadataEntry).filter(
        AgentMetadataEntry.agent_id == agent.agent_id
    ).all()

    metadata_dict = agent.metadata_json or {}
    
    return {
        "id": agent.id,  # Integer PK
        "agentId": agent.agent_id,  # Single agentId field (canonical format)
        "chainId": agent.chain_id,
        "registryAddress": agent.registry_address,
        "owner": agent.owner,
        "tokenURI": agent.token_uri,
        "metadata": metadata_dict,
        "endpoints": metadata_dict.get("endpoints", []),
        "supportedTrust": metadata_dict.get("supportedTrust", []),
        "healthStatus": agent.health_status,
        "lastHeartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        "createdAt": agent.created_at.isoformat(),
        "updatedAt": agent.updated_at.isoformat(),
        "metadataEntries": [{"key": m.key, "value": m.value} for m in metadata],
    }


@router.get("/agents")
async def list_agents(
    q: Optional[str] = Query(None, description="Search query"),
    endpoint_type: Optional[str] = Query(None, description="Filter by endpoint type (MCP, A2A, etc.)"),
    trust_model: Optional[str] = Query(None, description="Filter by trust model (reputation, validation, etc.)"),
    limit: int = Query(25, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List agents with optional search and filters"""
    query = db.query(Agent)

    if q:
        # Simple text search on canonical agent ID
        query = query.filter(
            Agent.agent_id.contains(q)
        )

    agents = query.order_by(desc(Agent.updated_at)).offset(offset).limit(limit).all()

    # Filter by endpoint type and trust model in Python (for now)
    # In production, use database full-text search or JSON queries
    filtered_items = []
    for agent in agents:
        metadata = agent.metadata_json or {}
        
        # Filter by endpoint type
        if endpoint_type:
            endpoints = metadata.get("endpoints", [])
            has_endpoint = any(
                ep.get("name", "").upper() == endpoint_type.upper()
                for ep in endpoints
            )
            if not has_endpoint:
                continue
        
        # Filter by trust model
        if trust_model:
            supported_trust = metadata.get("supportedTrust", [])
            if isinstance(supported_trust, str):
                supported_trust = [supported_trust]
            if trust_model.lower() not in [t.lower() for t in supported_trust]:
                continue
        
        # Extract endpoint URLs
        endpoints = metadata.get("endpoints", [])
        a2a_url = None
        mcp_url = None
        for ep in endpoints:
            ep_name = ep.get("name", "") if isinstance(ep, dict) else getattr(ep, "name", "")
            if ep_name.upper() == "A2A":
                a2a_url = ep.get("endpoint") if isinstance(ep, dict) else getattr(ep, "endpoint", None)
            elif ep_name.upper() == "MCP":
                mcp_url = ep.get("endpoint") if isinstance(ep, dict) else getattr(ep, "endpoint", None)
        
        # Build labels (exclude internal fields)
        labels = {k: v for k, v in metadata.items() 
                 if k not in ["name", "description", "endpoints", "supportedTrust", "type", "active", "x402support", "updatedAt"]}
        
        filtered_items.append({
            "id": agent.id,  # Integer PK
            "agentId": agent.agent_id,  # Single agentId field (canonical format)
            "name": metadata.get("name", "Unknown"),
            "status": agent.health_status,
            "url": a2a_url or mcp_url or agent.token_uri,
            "tokenURI": agent.token_uri,
            "endpoints": endpoints,
            "supportedTrust": metadata.get("supportedTrust", []),
            "labels": labels,
            "createdAt": agent.created_at.isoformat(),
            "updatedAt": agent.updated_at.isoformat(),
        })

    return {
        "items": filtered_items,
        "count": len(filtered_items),
    }


@router.post("/agents/{agent_id}/heartbeat")
async def heartbeat(
    agent_id: str = Path(..., description="Agent ID (canonical ID or integer PK)"),
    request: HeartbeatRequest = Body(default=HeartbeatRequest()),
    db: Session = Depends(get_db),
):
    """
    Update agent heartbeat.
    
    Requires cryptographic signature from the agent's owner address to verify authenticity.
    Signature format: EIP-191 personal sign of message "heartbeat:{agentId}:{timestamp}"
    """
    # FastAPI should automatically URL-decode path parameters, but ensure it's decoded
    agent_id = urllib.parse.unquote(agent_id)

    agent = await ensure_agent_indexed(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    # Use canonical agent_id for signature verification
    canonical_id_for_sig = agent.agent_id
    
    # Verify signature if agent has an owner address
    signature = request.signature
    timestamp = request.timestamp
    
    if agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(
                status_code=401,
                detail="Signature and timestamp required for authenticated heartbeats"
            )
        
        # Check timestamp is within 5-minute window
        now = int(time.time())
        if abs(now - timestamp) > 300:  # 5 minutes
            raise HTTPException(
                status_code=401,
                detail="Timestamp too old or too far in future (max 5 minutes)"
            )

        if not verify_heartbeat_signature(canonical_id_for_sig, timestamp, signature, agent.owner):
            # Owner may have changed on-chain since we cached it. Refresh once and retry.
            agent = await refresh_agent_owner(db, agent)
            if not verify_heartbeat_signature(canonical_id_for_sig, timestamp, signature, agent.owner):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid signature"
                )
    elif signature or timestamp:
        # Signature provided but agent has no owner - warn but allow
        logger.warning(f"[Heartbeat] Agent {agent_id} has no owner but signature provided")

    agent.last_heartbeat = datetime.utcnow()
    agent.health_status = "healthy"
    agent.updated_at = datetime.utcnow()
    db.commit()

    return {"ok": True, "status": "healthy"}

