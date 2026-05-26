from typing import Optional

from pydantic import BaseModel


class AgentMetadata(BaseModel):
    key: str
    value: str


class HeartbeatRequest(BaseModel):
    """Heartbeat request with optional signature."""
    signature: Optional[str] = None
    timestamp: Optional[int] = None


class NetworkConfig(BaseModel):
    chain_id: int
    rpc_url: str
    identity_registry: str
    reputation_registry: str
    validation_registry: str
