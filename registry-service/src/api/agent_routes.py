"""Agent-related API routes."""

import logging
import time
import urllib.parse
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.db.database import get_db
from src.db.models import Agent, AgentMetadataEntry
from src.types import (
    AgentRegistration, AgentMetadata, HeartbeatRequest
)
from src.api.utils import (
    parse_erc8004_canonical_id,
    fetch_registration_file,
    convert_agent_card_to_registration_file,
    verify_registration_signature,
    verify_heartbeat_signature,
    find_agent_by_id,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/register", status_code=201)
async def register_agent(
    registration: AgentRegistration,
    db: Session = Depends(get_db),
):
    """Register a new agent - supports both ERC-8004 registration file and legacy agent_card format"""
    from src.types import ERC8004RegistrationFile
    
    owner = registration.owner
    
    if not owner or owner == "0x0000000000000000000000000000000000000000":
        raise HTTPException(status_code=400, detail="Owner address is required")

    # Verify signature if provided (secure registration)
    signature = registration.signature
    timestamp = registration.timestamp

    if signature and timestamp is not None:
        # Create registration data dictionary for verification
        reg_data = registration.model_dump(exclude={'signature', 'timestamp'})

        logger.info(f"[Registration] Verifying signature for owner: {owner}")
        if not verify_registration_signature(owner, timestamp, signature, reg_data):
            logger.error(f"[Registration] Invalid registration signature for owner: {owner}")
            raise HTTPException(
                status_code=401,
                detail="Invalid registration signature"
            )
        logger.info(f"[Registration] ✓ Valid signature verified for owner {owner}")
    else:
        logger.warning(f"[Registration] No signature provided for owner {owner} - allowing for backward compatibility")

    try:
        registration_file: Optional[ERC8004RegistrationFile] = None
        token_uri: Optional[str] = None
        
        # Determine format and get registration file
        if registration.registration_file:
            # Direct registration file provided
            registration_file = registration.registration_file
        elif registration.registration_file_url:
            # Registration file URL provided - fetch it
            file_data = await fetch_registration_file(registration.registration_file_url)
            registration_file = ERC8004RegistrationFile(**file_data)
            token_uri = registration.registration_file_url
        elif registration.agent_card:
            # Legacy agent_card format - convert to registration file
            registration_file = convert_agent_card_to_registration_file(
                registration.agent_card,
                owner,
                registration.labels or {}
            )
            # For legacy format, use agent URL as token URI
            token_uri = str(registration.agent_card.url)
        else:
            raise HTTPException(
                status_code=400,
                detail="Either registrationFile, registrationFileUrl, or agentCard must be provided"
            )
        
        # Ensure token_uri is the agent card path (endpoint + /.well-known/agent-card.json)
        if not token_uri:
            if registration_file.endpoints:
                # Use first endpoint URL and append agent card path
                base_url = registration_file.endpoints[0].endpoint.rstrip('/')
                token_uri = f"{base_url}/.well-known/agent-card.json"
            else:
                # Fallback: use a placeholder (in production, should upload to IPFS)
                token_uri = f"https://registry.example.com/agents/{registration_file.name.lower().replace(' ', '-')}.json"
        else:
            # If token_uri was provided, ensure it ends with agent-card.json if it's an endpoint URL
            if token_uri and not token_uri.endswith('.json') and not token_uri.endswith('/'):
                # If it looks like an endpoint URL, append agent card path
                if any(ep.endpoint in token_uri for ep in registration_file.endpoints):
                    token_uri = f"{token_uri.rstrip('/')}/.well-known/agent-card.json"
        
        # Extract metadata from registration file
        metadata_list = [
            AgentMetadata(key="name", value=registration_file.name),
            AgentMetadata(key="agentDescription", value=registration_file.description),
            AgentMetadata(key="registrationFileType", value=registration_file.type),
            AgentMetadata(key="supportedTrust", value=",".join(registration_file.supported_trust)),
        ]
        
        # Add endpoint information
        for idx, endpoint in enumerate(registration_file.endpoints):
            metadata_list.append(
                AgentMetadata(key=f"endpoint.{idx}.name", value=endpoint.name)
            )
            metadata_list.append(
                AgentMetadata(key=f"endpoint.{idx}.url", value=endpoint.endpoint)
            )
            if endpoint.version:
                metadata_list.append(
                    AgentMetadata(key=f"endpoint.{idx}.version", value=endpoint.version)
                )
        
        # Add labels
        if registration.labels:
            for k, v in registration.labels.items():
                metadata_list.append(AgentMetadata(key=f"label.{k}", value=v))
        
        # Require ERC-8004 canonical ID format: eip155:{chainId}:{identityRegistry}:{agentId}
        agent_canonical_id = registration.agent_id
        if not agent_canonical_id:
            raise HTTPException(
                status_code=400,
                detail="agentId (ERC-8004 canonical ID) is required. Format: eip155:{chainId}:{identityRegistry}:{agentId}"
            )
        
        # Validate canonical ID format and normalize
        try:
            chain_id_from_id, identity_registry_from_id, onchain_agent_id_from_id = parse_erc8004_canonical_id(agent_canonical_id)
            # Rebuild canonical ID with normalized address to ensure consistency
            from src.api.utils import build_erc8004_canonical_id_from_components
            agent_canonical_id = build_erc8004_canonical_id_from_components(
                chain_id_from_id, identity_registry_from_id, onchain_agent_id_from_id
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid canonical ID format: {e}. Expected format: eip155:{{chainId}}:{{identityRegistry}}:{{agentId}}"
            )
        
        # Build full ERC-8004-style metadata JSON (all keys camelCase for A2A/ERC-8004)
        # Extract category from labels if present, default to "compute"
        category = registration.labels.get("category", "compute") if registration.labels else "compute"
        
        metadata_json = {
            "category": category,
            "type": registration_file.type,
            "name": registration_file.name,
            "description": registration_file.description,
            "supportedTrust": registration_file.supported_trust,
            "active": registration_file.active,
            "endpoints": [
                {
                    "name": ep.name,
                    "endpoint": ep.endpoint,
                    "version": ep.version,
                    "a2aSkills": ep.a2a_skills or [],
                    "mcpTools": ep.mcp_tools or [],
                }
                for ep in registration_file.endpoints
            ],
        }
        
        # Normalize any legacy onchainAgentId to onChainAgentId (camelCase)
        if "onchainAgentId" in metadata_json:
            metadata_json["onChainAgentId"] = metadata_json.pop("onchainAgentId")
        
        # Add any additional labels (excluding category which is now in metadata)
        if registration.labels:
            for k, v in registration.labels.items():
                if k != "category":  # Already in metadata_json
                    metadata_json[k] = v

        # Use components from canonical ID (they are the source of truth)
        chain_id_to_use = chain_id_from_id
        # Normalize registry address to lowercase for consistent comparison (Ethereum addresses are case-insensitive)
        identity_registry_to_use = identity_registry_from_id.lower()
        onchain_agent_id_to_use = onchain_agent_id_from_id
        
        # Validate that chain_id matches if provided in registration
        if registration.chain_id is not None and registration.chain_id != chain_id_to_use:
            raise HTTPException(
                status_code=400,
                detail=f"chainId mismatch: canonical ID has chainId={chain_id_to_use}, but registration provides chainId={registration.chain_id}"
            )
        
        # Check if agent already exists by canonical ID or by (chain_id, identity_registry, onchain_agent_id) tuple
        existing_agent = db.query(Agent).filter(Agent.agent_id == agent_canonical_id).first()
        
        # Fallback: lookup by tuple (for event sync compatibility) - normalize registry address for comparison
        if not existing_agent:
            existing_agent = db.query(Agent).filter(
                Agent.chain_id == chain_id_to_use,
                Agent.identity_registry == identity_registry_to_use,  # Already normalized to lowercase
                Agent.onchain_agent_id == onchain_agent_id_to_use
            ).first()

        if existing_agent:
            # Update existing agent
            logger.info(f"[Registration] Agent {agent_canonical_id} already exists, updating...")
            existing_agent.agent_id = agent_canonical_id  # Ensure canonical ID is set
            existing_agent.chain_id = chain_id_to_use
            existing_agent.identity_registry = identity_registry_to_use
            existing_agent.onchain_agent_id = onchain_agent_id_to_use
            existing_agent.registry_address = identity_registry_to_use  # Keep for backward compatibility
            existing_agent.token_uri = token_uri
            existing_agent.metadata_json = metadata_json
            existing_agent.owner = owner  # Update owner if changed
            existing_agent.health_status = "healthy"
            existing_agent.updated_at = datetime.utcnow()

            # Delete existing metadata entries and recreate them
            db.query(AgentMetadataEntry).filter(AgentMetadataEntry.agent_id == agent_canonical_id).delete()

            agent = existing_agent
        else:
            # Create new agent
            logger.info(f"[Registration] Creating new agent {agent_canonical_id}")
            
            agent = Agent(
                agent_id=agent_canonical_id,  # Canonical ID is the primary identifier
                chain_id=chain_id_to_use,
                identity_registry=identity_registry_to_use,
                onchain_agent_id=onchain_agent_id_to_use,
                registry_address=identity_registry_to_use,  # Keep for backward compatibility
                owner=owner,
                token_uri=token_uri,
                metadata_json=metadata_json,
                health_status="healthy",
            )
            db.add(agent)

        # Flush to get auto-generated ID without committing yet
        db.flush()
        # Refresh to ensure we have the latest state (including auto-generated id)
        db.refresh(agent)

        # Store metadata entries (using canonical agent_id for FK)
        for meta in metadata_list:
            metadata_entry = AgentMetadataEntry(
                agent_id=agent_canonical_id,  # Use canonical ID for FK
                key=meta.key,
                value=meta.value,
            )
            db.add(metadata_entry)
        
        # Commit everything together
        db.commit()

        response_data = {
            "status": "updated" if existing_agent else "registered",
            "id": agent.id,  # Return integer PK
            "agentId": agent_canonical_id,  # Single agentId field (canonical format)
            "name": registration_file.name,
            "tokenURI": token_uri,
            "message": (
                f"Agent {'updated in' if existing_agent else 'registered with'} Indexer. "
                "To register on-chain, register directly from your agent code. "
                "See RECOMMENDED_REGISTRATION_WORKFLOW.md for instructions."
            ),
        }

        return response_data
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


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
    """Get agent by ID (expects canonical eip155:... format)"""
    agent = find_agent_by_id(db, agent_id)
    
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
    
    agent = find_agent_by_id(db, agent_id)
    
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
        
        # Verify signature (use canonical_id for message)
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

