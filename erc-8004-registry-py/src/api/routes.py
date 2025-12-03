from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
from typing import Optional
from src.db.database import get_db
from src.db.models import Agent, AgentMetadataEntry
from src.types import AgentRegistration, AgentCard
from src.config import settings
from src.contracts.identity_registry import IdentityRegistryClient
from src.types import NetworkConfig, AgentMetadata

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


@router.post("/agents/register", status_code=201)
async def register_agent(
    registration: AgentRegistration,
    db: Session = Depends(get_db),
):
    """Register a new agent"""
    agent_card = registration.agent_card
    owner = registration.owner
    
    if not owner or owner == "0x0000000000000000000000000000000000000000":
        raise HTTPException(status_code=400, detail="Owner address is required")

    try:
        # Create token URI (in production, upload agent card to IPFS or similar)
        token_uri = str(agent_card.url)  # For MVP, use the agent URL as token URI
        
        # Prepare metadata
        metadata_list = [
            AgentMetadata(key="agentName", value=agent_card.name),
            AgentMetadata(key="agentDescription", value=agent_card.description),
            AgentMetadata(key="agentUrl", value=str(agent_card.url)),
            AgentMetadata(key="agentVersion", value=agent_card.version),
        ]
        
        if registration.labels:
            for k, v in registration.labels.items():
                metadata_list.append(AgentMetadata(key=f"label.{k}", value=v))

        # Store in database (off-chain index)
        # Generate a temporary agent ID (will be replaced with on-chain ID after registration)
        temp_agent_id = f"temp_{int(__import__('time').time() * 1000)}"
        
        agent = Agent(
            agent_id=temp_agent_id,
            chain_id=settings.chain_id,
            registry_address=settings.identity_registry_address,
            token_uri=token_uri,
            metadata_json={
                **(registration.labels or {}),
                "name": agent_card.name,
                "description": agent_card.description,
                "url": str(agent_card.url),
                "version": agent_card.version,
            },
            health_status="healthy",
        )
        db.add(agent)
        db.commit()

        # Store metadata
        for meta in metadata_list:
            metadata_entry = AgentMetadataEntry(
                agent_id=temp_agent_id,
                key=meta.key,
                value=meta.value,
            )
            db.add(metadata_entry)
        db.commit()

        return {
            "status": "registered",
            "id": temp_agent_id,
            "name": agent_card.name,
            "message": "Agent registered off-chain. On-chain registration requires wallet integration.",
        }
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

    return {
        "id": agent.agent_id,
        "chainId": agent.chain_id,
        "registryAddress": agent.registry_address,
        "tokenURI": agent.token_uri,
        "metadata": agent.metadata_json,
        "healthStatus": agent.health_status,
        "lastHeartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        "createdAt": agent.created_at.isoformat(),
        "updatedAt": agent.updated_at.isoformat(),
        "metadataEntries": [{"key": m.key, "value": m.value} for m in metadata],
    }


@router.get("/agents")
async def list_agents(
    q: Optional[str] = Query(None, description="Search query"),
    limit: int = Query(25, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List agents with optional search"""
    query = db.query(Agent)

    if q:
        # Simple text search on agent ID or metadata
        query = query.filter(
            or_(
                Agent.agent_id.contains(q),
            )
        )

    agents = query.order_by(desc(Agent.updated_at)).offset(offset).limit(limit).all()

    return {
        "items": [
            {
                "id": agent.agent_id,
                "name": agent.metadata_json.get("name") if agent.metadata_json else "Unknown",
                "status": agent.health_status,
                "url": agent.metadata_json.get("url") if agent.metadata_json else agent.token_uri,
                "version": agent.metadata_json.get("version") if agent.metadata_json else "0.1.0",
                "labels": agent.metadata_json or {},
                "createdAt": agent.created_at.isoformat(),
                "updatedAt": agent.updated_at.isoformat(),
            }
            for agent in agents
        ],
        "count": len(agents),
    }


@router.get("/agents/search")
async def search_agents(
    q: str = Query(..., description="Search query"),
    db: Session = Depends(get_db),
):
    """Search agents"""
    if not q:
        return {"items": []}

    # Simple search - in production, implement full-text search
    agents = db.query(Agent).filter(
        Agent.agent_id.contains(q)
    ).limit(50).all()

    return {
        "items": [
            {
                "id": agent.agent_id,
                "name": agent.metadata_json.get("name") if agent.metadata_json else "Unknown",
                "status": agent.health_status,
                "url": agent.metadata_json.get("url") if agent.metadata_json else agent.token_uri,
            }
            for agent in agents
        ],
    }


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

