from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
from typing import Optional
import json
import time
import logging
import asyncio
import aiohttp
from src.db.database import get_db
from src.db.models import Agent, AgentMetadataEntry
from src.types import (
    AgentRegistration, AgentCard, ERC8004RegistrationFile,
    Endpoint, RegistrationRecord, AgentMetadata
)
from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "erc-8004-registry",
        "version": "0.1.0",
        "health_checks_enabled": settings.enable_health_checks,
    }


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
            version=agent_card.protocol_version or agent_card.version,
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
        supported_trust=["reputation"],
        active=True,
        x402support=False,
        updated_at=int(time.time())
    )


@router.post("/agents/register", status_code=201)
async def register_agent(
    registration: AgentRegistration,
    db: Session = Depends(get_db),
):
    """Register a new agent - supports both ERC-8004 registration file and legacy agent_card format"""
    owner = registration.owner
    
    if not owner or owner == "0x0000000000000000000000000000000000000000":
        raise HTTPException(status_code=400, detail="Owner address is required")

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
        
        # If token URI not set yet, use first endpoint URL or generate one
        if not token_uri:
            if registration_file.endpoints:
                token_uri = registration_file.endpoints[0].endpoint
            else:
                # Fallback: use a placeholder (in production, should upload to IPFS)
                token_uri = f"https://registry.example.com/agents/{registration_file.name.lower().replace(' ', '-')}.json"
        
        # Extract metadata from registration file
        metadata_list = [
            AgentMetadata(key="agentName", value=registration_file.name),
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
        
        # Store in database (off-chain index)
        temp_agent_id = f"temp_{int(time.time() * 1000)}"
        
        # Build metadata JSON
        metadata_json = {
            **(registration.labels or {}),
            "name": registration_file.name,
            "description": registration_file.description,
            "type": registration_file.type,
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
        
        agent = Agent(
            agent_id=temp_agent_id,
            chain_id=settings.chain_id,
            registry_address=settings.identity_registry_address,
            token_uri=token_uri,
            metadata_json=metadata_json,
            health_status="healthy",
        )
        db.add(agent)
        db.commit()

        # Store metadata entries
        for meta in metadata_list:
            metadata_entry = AgentMetadataEntry(
                agent_id=temp_agent_id,
                key=meta.key,
                value=meta.value,
            )
            db.add(metadata_entry)
        db.commit()

        response_data = {
            "status": "registered",
            "id": temp_agent_id,
            "name": registration_file.name,
            "tokenURI": token_uri,
            "message": (
                "Agent registered off-chain. "
                "To register on-chain, register directly from your agent code. "
                "See RECOMMENDED_REGISTRATION_WORKFLOW.md for instructions."
            ),
        }

        return response_data
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str = Path(..., description="Agent ID"),
    db: Session = Depends(get_db),
):
    """Get agent by ID"""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get all metadata
    metadata = db.query(AgentMetadataEntry).filter(
        AgentMetadataEntry.agent_id == agent_id
    ).all()

    metadata_dict = agent.metadata_json or {}
    
    return {
        "id": agent.agent_id,
        "chainId": agent.chain_id,
        "registryAddress": agent.registry_address,
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
        # Simple text search on agent ID or metadata
        query = query.filter(
            or_(
                Agent.agent_id.contains(q),
            )
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
            "id": agent.agent_id,
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
            "id": agent.agent_id,
            "name": metadata.get("name", "Unknown"),
            "status": agent.health_status,
            "url": a2a_url or agent.token_uri,
            "tokenURI": agent.token_uri,
        })

    return {"items": items}


@router.post("/agents/{agent_id}/heartbeat")
async def heartbeat(
    agent_id: str = Path(..., description="Agent ID"),
    db: Session = Depends(get_db),
):
    """Update agent heartbeat"""
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from datetime import datetime
    agent.last_heartbeat = datetime.utcnow()
    agent.health_status = "healthy"
    agent.updated_at = datetime.utcnow()
    db.commit()

    return {"ok": True, "status": "healthy"}

