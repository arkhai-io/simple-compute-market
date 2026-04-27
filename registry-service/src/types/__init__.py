from enum import Enum
from typing import Optional, Dict, List, Any, Union
from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator, ConfigDict


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
    input_modes: Optional[List[str]] = Field(default=["text/plain"], alias="inputModes")
    output_modes: Optional[List[str]] = Field(default=["text/plain"], alias="outputModes")
    examples: List[str] = []
    
    model_config = ConfigDict(populate_by_name=True)


class AgentCard(BaseModel):
    """A2A Protocol agent card format (camelCase compliant)"""
    name: str
    description: str
    url: HttpUrl
    version: str = "0.1.0"
    defaultInputModes: Optional[List[str]] = Field(default=["text/plain"])
    defaultOutputModes: Optional[List[str]] = Field(default=["text/plain"])
    skills: List[Capability] = []
    capabilities: Dict[str, Any] = {}
    preferredTransport: Optional[str] = Field(default=None)
    protocolVersion: Optional[str] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)
    
    

# ERC-8004 Registration File Format Models

class Endpoint(BaseModel):
    """Endpoint definition for ERC-8004 registration file"""
    name: str  # "MCP", "A2A", etc.
    endpoint: str
    version: Optional[str] = None
    
    # MCP-specific fields
    mcp_tools: Optional[List[str]] = Field(default=None, alias="mcpTools")
    mcp_prompts: Optional[List[str]] = Field(default=None, alias="mcpPrompts")
    mcp_resources: Optional[List[str]] = Field(default=None, alias="mcpResources")
    
    # A2A-specific fields
    a2a_skills: Optional[List[str]] = Field(default=None, alias="a2aSkills")
    
    model_config = ConfigDict(populate_by_name=True)


class RegistrationRecord(BaseModel):
    """On-chain registration record"""
    agent_id: int = Field(alias="agentId")
    agent_registry: str = Field(alias="agentRegistry")  # Format: "eip155:chainId:address"
    
    model_config = ConfigDict(populate_by_name=True)


class ERC8004RegistrationFile(BaseModel):
    """ERC-8004 compliant registration file format"""
    type: str = Field(default="https://eips.ethereum.org/EIPS/eip-8004#registration-v1")
    name: str
    description: str
    image: Optional[str] = None
    endpoints: List[Endpoint] = []
    registrations: List[RegistrationRecord] = []
    supported_trust: List[str] = Field(default=["reputation"], alias="supportedTrust")
    active: bool = True
    x402support: bool = Field(default=False, alias="x402support")
    updated_at: int = Field(alias="updatedAt")
    
    model_config = ConfigDict(populate_by_name=True)
    
    @model_validator(mode='before')
    @classmethod
    def normalize_fields(cls, data):
        """Normalize camelCase to snake_case"""
        if isinstance(data, dict):
            normalized = {}
            for key, value in data.items():
                if key == "supportedTrust":
                    normalized["supported_trust"] = value
                elif key == "x402support":
                    normalized["x402support"] = value
                elif key == "updatedAt":
                    normalized["updated_at"] = value
                else:
                    normalized[key] = value
            return normalized
        return data


class AgentRegistration(BaseModel):
    """Agent registration request - supports both formats"""
    # ERC-8004 registration file (new format)
    registration_file: Optional[ERC8004RegistrationFile] = Field(default=None, alias="registrationFile")
    registration_file_url: Optional[str] = Field(default=None, alias="registrationFileUrl")

    # Legacy agent card format (backward compatibility)
    agent_card: Optional[AgentCard] = Field(default=None, alias="agentCard")

    # Common fields
    agent_id: Optional[str] = Field(default=None, alias="agentId")  # Custom agent ID (optional)
    chain_id: Optional[int] = Field(default=None, alias="chainId")  # Chain ID from agent
    domain: Optional[str] = None
    owner: Optional[str] = None
    visibility: Optional[str] = "public"  # public|internal|private
    labels: Dict[str, str] = {}
    auth: Dict[str, Any] = {}

    # Signature-based authentication fields
    signature: Optional[str] = None  # EIP-191 signature of registration message
    timestamp: Optional[int] = None  # Unix timestamp for replay protection

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode='after')
    def validate_format(self):
        """Ensure at least one format is provided"""
        if not self.registration_file and not self.registration_file_url and not self.agent_card:
            raise ValueError("Either registrationFile, registrationFileUrl, or agentCard must be provided")
        return self


class AgentMetadata(BaseModel):
    key: str
    value: str


class HeartbeatRequest(BaseModel):
    """Heartbeat request with optional signature"""
    signature: Optional[str] = None
    timestamp: Optional[int] = None


class NetworkConfig(BaseModel):
    chain_id: int
    rpc_url: str
    identity_registry: str
    reputation_registry: str
    validation_registry: str

