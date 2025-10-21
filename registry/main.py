from __future__ import annotations
import os, time, enum, secrets, asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

import aiohttp
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Body, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime, Text, JSON, Boolean, Enum, Index
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import IntegrityError
import jwt  # PyJWT

# ----------------------- Config -----------------------
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(16))  # dev default
HEARTBEAT_TTL_SECS = int(os.getenv("HEARTBEAT_TTL_SECS", "60"))  # mark stale if >60s since last beat
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./registry.db")

# Health Check Configuration
ENABLE_HEALTH_CHECKS = os.getenv("ENABLE_HEALTH_CHECKS", "true").lower() == "true"
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))  # check every minute
ENDPOINT_CHECK_TIMEOUT = int(os.getenv("ENDPOINT_CHECK_TIMEOUT", "10"))  # 10 second timeout

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()
app = FastAPI(title="Agent Registry (FastAPI MVP)", version="0.1.0")

@app.on_event("startup")
async def startup_event():
    """Initialize background tasks on startup."""
    print("[STARTUP] Agent Registry starting up...")

    if ENABLE_HEALTH_CHECKS:
        # Start the health check loop in the background
        asyncio.create_task(health_check_loop())
        print("[STARTUP] Health checking enabled")
    else:
        print("[STARTUP] Health checking disabled")

# ----------------------- RBAC -------------------------
class Role(str, enum.Enum):
    admin = "admin"
    validator = "validator"
    server = "server"
    client = "client"
    viewer = "viewer"

PERMS: Dict[str, List[str]] = {
    Role.admin: ["*"],
    Role.validator: ["validation:score", "agents:read"],
    Role.server: ["agents:register", "validation:request", "reputation:authorize", "agents:read"],
    Role.client: ["reputation:give", "agents:read"],
    Role.viewer: ["agents:read"],
}

bearer = HTTPBearer(auto_error=False)

def require_roles(*allowed: Role):
    def dep(auth: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> Dict[str, Any]:
        if not auth or not auth.scheme.lower() == "bearer":
            raise HTTPException(401, "missing bearer token")
        try:
            payload = jwt.decode(auth.credentials, JWT_SECRET, algorithms=[JWT_ALG])
        except Exception as e:
            raise HTTPException(401, f"invalid token: {e}")
        roles = payload.get("roles", [])
        if not any(r in [a.value if isinstance(a, Role) else a for a in allowed] or r == "admin" for r in roles):
            raise HTTPException(403, "forbidden")
        return {"sub": payload.get("sub"), "roles": roles, "claims": payload}
    return dep

# ----------------------- Models -----------------------
class Capability(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = []
    input_modes: List[str] = ["text/plain"]
    output_modes: List[str] = ["text/plain"]
    examples: List[str] = []

class AgentCard(BaseModel):
    name: str
    description: str
    url: HttpUrl
    version: str = "0.1.0"
    default_input_modes: List[str] = ["text"]
    default_output_modes: List[str] = ["text"]
    skills: List[Capability] = []
    capabilities: Dict[str, Any] = {"streaming": True}

class AgentRegistration(BaseModel):
    # “Agent Card” plus identity/labels your platform needs
    agent_card: AgentCard
    domain: Optional[str] = None               # aligns with A2A/Agent Card host
    owner: Optional[str] = None                # user/org/tenant id
    visibility: str = Field("internal", pattern="^(public|internal|private)$")
    labels: Dict[str, str] = {}
    auth: Dict[str, Any] = {}                  # optional (token hints, etc.)

class AgentRowStatus(str, enum.Enum):
    healthy = "healthy"
    stale = "stale"
    unreachable = "unreachable"
    deprecated = "deprecated"

class AgentORM(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), index=True, nullable=False)
    description = Column(Text, nullable=False)
    url = Column(String(1024), nullable=False, unique=False)
    version = Column(String(50), nullable=False, default="0.1.0")
    domain = Column(String(512), nullable=True, index=True)
    owner = Column(String(256), nullable=True, index=True)
    visibility = Column(String(32), nullable=False, default="internal")  # public|internal|private
    labels = Column(JSON, default=dict)
    agent_card = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_heartbeat = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(Enum(AgentRowStatus), default=AgentRowStatus.healthy)
    deprecated = Column(Boolean, default=False)

Index("ix_agents_text", AgentORM.name, AgentORM.description)

def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

Base.metadata.create_all(bind=engine)

# ----------------------- Policy helpers ----------------
def can_view(agent: AgentORM, caller: Dict[str, Any]) -> bool:
    if agent.visibility == "public":
        return True
    roles = caller.get("roles", [])
    if "admin" in roles:
        return True
    if agent.visibility == "internal" and any(r in ["viewer","server","client","validator"] for r in roles):
        return True
    # private → require explicit owner match (simple MVP rule)
    sub = caller.get("sub")
    return bool(agent.owner and sub and agent.owner == sub)

def heartbeat_status(now: datetime, last: datetime) -> AgentRowStatus:
    # Handle timezone differences - ensure both datetimes are comparable
    if last.tzinfo is None:
        # If last_heartbeat is timezone-naive (from SQLite), assume UTC
        last = last.replace(tzinfo=timezone.utc)
    elif now.tzinfo is None:
        # If now is timezone-naive, assume UTC
        now = now.replace(tzinfo=timezone.utc)

    return AgentRowStatus.healthy if (now - last).total_seconds() <= HEARTBEAT_TTL_SECS else AgentRowStatus.stale

# ----------------------- Health Checking -----------------
async def check_agent_endpoint(url: str) -> bool:
    """Check if an agent's endpoint is responsive."""
    try:
        timeout = aiohttp.ClientTimeout(total=ENDPOINT_CHECK_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                return response.status < 500  # Consider 4xx and 5xx as unhealthy
    except Exception as e:
        print(f"[HEALTH CHECK] Failed to connect to {url}: {e}")
        return False

async def health_check_loop():
    """Background task that periodically checks agent health."""
    if not ENABLE_HEALTH_CHECKS:
        print("[HEALTH CHECK] Health checks disabled")
        return

    print(f"[HEALTH CHECK] Starting health check loop (interval: {HEALTH_CHECK_INTERVAL}s)")

    while True:
        try:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            await perform_health_checks()
        except Exception as e:
            print(f"[HEALTH CHECK] Error in health check loop: {e}")

async def perform_health_checks():
    """Perform health checks on all agents."""
    print(f"[HEALTH CHECK] Running health checks at {datetime.now(timezone.utc)}")

    with SessionLocal() as session:
        now = datetime.now(timezone.utc)

        # Get all non-deprecated agents
        agents = session.query(AgentORM).filter(
            AgentORM.deprecated == False
        ).all()

        print(f"[HEALTH CHECK] Checking {len(agents)} agents")

        for agent in agents:
            try:
                # First, check if heartbeat is stale
                current_status = heartbeat_status(now, agent.last_heartbeat)

                if current_status == AgentRowStatus.stale:
                    # If heartbeat is stale, check if endpoint is reachable
                    print(f"[HEALTH CHECK] Agent {agent.id} ({agent.name}) heartbeat stale, checking endpoint...")
                    endpoint_reachable = await check_agent_endpoint(agent.url)

                    if endpoint_reachable:
                        # Endpoint reachable but no heartbeat - mark as stale
                        new_status = AgentRowStatus.stale
                        print(f"[HEALTH CHECK] Agent {agent.id} endpoint reachable but no heartbeat")
                    else:
                        # Endpoint not reachable - mark as unreachable
                        new_status = AgentRowStatus.unreachable
                        print(f"[HEALTH CHECK] Agent {agent.id} unreachable - endpoint not responding")

                    # Update status if changed
                    if agent.status != new_status:
                        old_status = agent.status
                        agent.status = new_status
                        agent.updated_at = now
                        session.commit()
                        print(f"[HEALTH CHECK] Agent {agent.id} status: {old_status} → {new_status}")
                else:
                    # Heartbeat is recent, ensure status is healthy
                    if agent.status != AgentRowStatus.healthy:
                        old_status = agent.status
                        agent.status = AgentRowStatus.healthy
                        agent.updated_at = now
                        session.commit()
                        print(f"[HEALTH CHECK] Agent {agent.id} recovered: {old_status} → healthy")

            except Exception as e:
                print(f"[HEALTH CHECK] Error checking agent {agent.id}: {e}")

# ----------------------- Endpoints ---------------------
@app.post("/agents/register", status_code=201)
def register_agent(
    reg: AgentRegistration,
    caller=Depends(require_roles(Role.server, Role.admin)),
    s: Session = Depends(db),
):
    # store/overwrite by (name, owner, version) or new row—MVP: upsert by (url)
    now = datetime.now(timezone.utc)
    orm = AgentORM(
        name=reg.agent_card.name,
        description=reg.agent_card.description,
        url=str(reg.agent_card.url),
        version=reg.agent_card.version,
        domain=reg.domain or str(reg.agent_card.url),
        owner=reg.owner or caller["sub"],
        visibility=reg.visibility,
        labels=reg.labels or {},
        agent_card=reg.agent_card.model_dump(mode='json'),
        created_at=now,
        updated_at=now,
        last_heartbeat=now,
        status=AgentRowStatus.healthy,
    )
    s.add(orm)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        # If same URL exists, update it
        existing = s.query(AgentORM).filter(AgentORM.url == str(reg.agent_card.url)).first()
        if not existing:
            raise
        existing.name = reg.agent_card.name
        existing.description = reg.agent_card.description
        existing.version = reg.agent_card.version
        existing.domain = reg.domain or existing.domain
        existing.owner = reg.owner or existing.owner
        existing.visibility = reg.visibility or existing.visibility
        existing.labels = reg.labels or existing.labels
        existing.agent_card = reg.agent_card.model_dump(mode='json')
        existing.updated_at = now
        s.commit()
        orm = existing
    return {"status": "registered", "id": orm.id, "name": orm.name}

@app.post("/agents/{agent_id}/heartbeat", status_code=200)
def heartbeat(
    agent_id: int = Path(..., ge=1),
    caller=Depends(require_roles(Role.server, Role.admin, Role.validator, Role.client)),
    s: Session = Depends(db),
):
    orm = s.query(AgentORM).get(agent_id)
    if not orm:
        raise HTTPException(404, "agent not found")
    orm.last_heartbeat = datetime.now(timezone.utc)
    orm.status = AgentRowStatus.healthy
    orm.updated_at = datetime.now(timezone.utc)
    s.commit()
    return {"ok": True, "status": orm.status}

@app.get("/agents/search")
def search_agents(
    q: str = Query(..., description="free text search query"),
    caller=Depends(require_roles(Role.viewer, Role.server, Role.client, Role.validator, Role.admin)),
    s: Session = Depends(db),
):
    print(f"[DEBUG] search_agents called: q={q}, caller={caller}")
    like = f"%{q}%"
    try:
        rows = s.query(AgentORM).filter(
            (AgentORM.name.ilike(like)) |
            (AgentORM.description.ilike(like)) |
            (AgentORM.agent_card.cast(String).ilike(like))
        ).limit(50).all()
    except Exception as e:
        print(f"[DEBUG] JSON search failed: {e}, falling back to name/description only")
        rows = s.query(AgentORM).filter(
            (AgentORM.name.ilike(like)) |
            (AgentORM.description.ilike(like))
        ).limit(50).all()
    print(f"[DEBUG] Search found {len(rows)} agents before filtering")
    now = datetime.now(timezone.utc)
    results = []
    for r in rows:
        r.status = heartbeat_status(now, r.last_heartbeat)
        can_view_result = can_view(r, caller)
        print(f"[DEBUG] Search agent {r.id} ({r.name}): visibility={r.visibility}, owner={r.owner}, can_view={can_view_result}")
        if can_view_result:
            results.append({"id": r.id, "name": r.name, "status": r.status, "url": r.url})
    print(f"[DEBUG] Search returning {len(results)} agents after permission filtering")
    return {"items": results}

@app.get("/agents/{agent_id}")
def get_agent(
    agent_id: int = Path(..., ge=1),
    caller=Depends(require_roles(Role.viewer, Role.server, Role.client, Role.validator, Role.admin)),
    s: Session = Depends(db),
):
    orm = s.query(AgentORM).get(agent_id)
    if not orm:
        raise HTTPException(404, "not found")
    # live status
    orm.status = heartbeat_status(datetime.now(timezone.utc), orm.last_heartbeat)
    if not can_view(orm, caller):
        raise HTTPException(403, "forbidden")
    return {
        "id": orm.id,
        "status": orm.status,
        "visibility": orm.visibility,
        "labels": orm.labels,
        "owner": orm.owner,
        "agent_card": orm.agent_card,
        "last_heartbeat": orm.last_heartbeat,
        "updated_at": orm.updated_at,
    }

@app.get("/agents")
def list_agents(
    q: Optional[str] = Query(None, description="keyword search in name/description"),
    skill: Optional[str] = Query(None, description="filter by skill id or tag"),
    visibility: Optional[str] = Query(None, pattern="^(public|internal|private)$"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    caller=Depends(require_roles(Role.viewer, Role.server, Role.client, Role.validator, Role.admin)),
    s: Session = Depends(db),
):
    print(f"[DEBUG] list_agents called: q={q}, skill={skill}, visibility={visibility}, caller={caller}")
    qry = s.query(AgentORM)
    if visibility:
        qry = qry.filter(AgentORM.visibility == visibility)
    if q:
        like = f"%{q}%"
        qry = qry.filter((AgentORM.name.ilike(like)) | (AgentORM.description.ilike(like)))
    if skill:
        # naive JSON LIKE; swap to Postgres JSONB @> for prod
        like = f"%\"id\": \"{skill}\"%"
        try:
            qry = qry.filter(AgentORM.agent_card.cast(String).ilike(like))
        except Exception as e:
            print(f"[DEBUG] Skill filtering failed: {e}, skipping skill filter")
            # Continue without skill filtering if JSON search fails
    rows = qry.order_by(AgentORM.updated_at.desc()).offset(offset).limit(limit).all()
    print(f"[DEBUG] Found {len(rows)} agents before filtering")
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        r.status = heartbeat_status(now, r.last_heartbeat)
        can_view_result = can_view(r, caller)
        print(f"[DEBUG] Agent {r.id} ({r.name}): visibility={r.visibility}, owner={r.owner}, can_view={can_view_result}")
        if can_view_result:
            out.append({
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "version": r.version,
                "labels": r.labels,
                "visibility": r.visibility,
                "url": r.url,
            })
    print(f"[DEBUG] Returning {len(out)} agents after permission filtering")
    return {"items": out, "count": len(out)}

@app.post("/agents/{agent_id}/deprecate", status_code=200)
def deprecate_agent(
    agent_id: int,
    deprecated: bool = Body(True),
    caller=Depends(require_roles(Role.admin)),
    s: Session = Depends(db),
):
    orm = s.query(AgentORM).get(agent_id)
    if not orm:
        raise HTTPException(404, "not found")
    orm.deprecated = bool(deprecated)
    orm.status = AgentRowStatus.deprecated if deprecated else orm.status
    orm.updated_at = datetime.now(timezone.utc)
    s.commit()
    return {"ok": True, "deprecated": orm.deprecated}

# ----------------------- Health Check Endpoints ---------
@app.get("/health")
def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "agent-registry",
        "version": "0.1.0",
        "health_checks_enabled": ENABLE_HEALTH_CHECKS,
        "health_check_interval": HEALTH_CHECK_INTERVAL if ENABLE_HEALTH_CHECKS else None
    }

@app.post("/agents/{agent_id}/verify")
async def verify_agent(
    agent_id: int = Path(..., ge=1),
    caller=Depends(require_roles(Role.server, Role.admin)),
    s: Session = Depends(db),
):
    """Manually verify a specific agent's endpoint."""
    orm = s.query(AgentORM).get(agent_id)
    if not orm:
        raise HTTPException(404, "agent not found")

    print(f"[VERIFY] Manually checking agent {agent_id} ({orm.name})")
    endpoint_reachable = await check_agent_endpoint(orm.url)

    result = {
        "agent_id": agent_id,
        "name": orm.name,
        "url": orm.url,
        "endpoint_reachable": endpoint_reachable,
        "last_heartbeat": orm.last_heartbeat,
        "current_status": orm.status
    }

    if endpoint_reachable:
        # If endpoint is reachable, update status to healthy
        if orm.status != AgentRowStatus.healthy:
            old_status = orm.status
            orm.status = AgentRowStatus.healthy
            orm.updated_at = datetime.now(timezone.utc)
            s.commit()
            result["status_updated"] = f"{old_status} → healthy"
    else:
        # If endpoint is not reachable, mark as unreachable
        if orm.status != AgentRowStatus.unreachable:
            old_status = orm.status
            orm.status = AgentRowStatus.unreachable
            orm.updated_at = datetime.now(timezone.utc)
            s.commit()
            result["status_updated"] = f"{old_status} → unreachable"

    return result

@app.post("/agents/health-checks")
async def trigger_health_checks(
    caller=Depends(require_roles(Role.admin)),
):
    """Manually trigger health checks on all agents."""
    print(f"[MANUAL] Triggering manual health checks by {caller.get('sub')}")
    await perform_health_checks()
    return {"message": "Health checks triggered", "timestamp": datetime.now(timezone.utc)}

# ----------------------- Simple token mint (dev only) ---
class TokenReq(BaseModel):
    sub: str
    roles: List[Role]

@app.post("/dev/mint-token")
def mint_token(req: TokenReq):
    # DEV ONLY. In prod, issue tokens via Auth0/Clerk/IAP and verify via JWKS.
    payload = {
        "sub": req.sub,
        "roles": [r.value for r in req.roles],
        "iat": int(time.time()),
        "exp": int(time.time() + 3600),
    }
    return {"token": jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)}
