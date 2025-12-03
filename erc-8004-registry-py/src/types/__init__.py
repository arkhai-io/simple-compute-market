from enum import Enum
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, HttpUrl


class AgentStatus(str, Enum):
    healthy = "healthy"
    stale = "stale"
    unreachable = "unreachable"
    deprecated = "deprecated"


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
    default_input_modes: List[str] = ["text/plain"]
    default_output_modes: List[str] = ["text/plain"]
    skills: List[Capability] = []
    capabilities: Dict[str, Any] = {}


class AgentRegistration(BaseModel):
    agent_card: AgentCard
    domain: Optional[str] = None
    owner: Optional[str] = None
    visibility: Optional[str] = "public"  # public|internal|private
    labels: Dict[str, str] = {}
    auth: Dict[str, Any] = {}


class AgentMetadata(BaseModel):
    key: str
    value: str


class NetworkConfig(BaseModel):
    chain_id: int
    rpc_url: str
    identity_registry: str
    reputation_registry: str
    validation_registry: str

