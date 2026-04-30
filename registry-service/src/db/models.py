from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
import enum


class AgentStatusEnum(str, enum.Enum):
    healthy = "healthy"
    stale = "stale"
    unreachable = "unreachable"
    deprecated = "deprecated"

Base = declarative_base()


class Agent(Base):
    __tablename__ = "agents"
    
    # Integer primary key for internal DB use
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ERC-8004 canonical identifier: eip155:{chainId}:{identityRegistry}:{agentId}
    # This is the single source of truth for agent identity
    agent_id = Column(String, nullable=True, unique=True)
    
    # Components of canonical ID for querying
    chain_id = Column(Integer, nullable=False)
    identity_registry = Column(String, nullable=True)  # Registry contract address
    onchain_agent_id = Column(Integer, nullable=True)  # Numeric ERC-721 tokenId
    
    # Legacy field name for backward compatibility (maps to identity_registry)
    registry_address = Column(String, nullable=False)
    
    owner = Column(String, nullable=True)  # Wallet address of agent owner (for signature verification)
    token_uri = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON, default=dict)  # Database column is "metadata", Python attr is "metadata_json" to avoid SQLAlchemy conflict
    health_status = Column(SQLEnum(AgentStatusEnum), nullable=False, default=AgentStatusEnum.healthy)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    metadata_entries = relationship("AgentMetadataEntry", back_populates="agent", cascade="all, delete-orphan")
    health_checks = relationship("HealthCheck", back_populates="agent", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_agents_chain_id", "chain_id"),
        Index("idx_agents_health_status", "health_status"),
        Index("idx_agents_owner", "owner"),
        Index("idx_agents_token_uri", "token_uri"),
        Index("idx_agents_identity_registry", "identity_registry"),
        Index("idx_agents_onchain_agent_id", "onchain_agent_id"),
        Index("ux_agents_chain_registry_onchain", "chain_id", "identity_registry", "onchain_agent_id", unique=True),
    )


class AgentMetadataEntry(Base):
    __tablename__ = "agent_metadata"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id", ondelete="CASCADE"), nullable=False)
    key = Column(String, nullable=False)
    value = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    
    # Relationships
    agent = relationship("Agent", back_populates="metadata_entries")
    
    __table_args__ = (
        Index("idx_agent_metadata_agent_id", "agent_id"),
    )


class HealthCheck(Base):
    __tablename__ = "health_checks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, ForeignKey("agents.agent_id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    response_time = Column(Integer, nullable=True)  # milliseconds
    error = Column(Text, nullable=True)
    
    # Relationships
    agent = relationship("Agent", back_populates="health_checks")
    
    __table_args__ = (
        Index("idx_health_checks_agent_id", "agent_id"),
        Index("idx_health_checks_checked_at", "checked_at"),
    )


class OrderStatusEnum(str, enum.Enum):
    open = "open"
    closed = "closed"
    accepted = "accepted"
    expired = "expired"


class Listing(Base):
    __tablename__ = "listings"

    listing_id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.agent_id", ondelete="CASCADE"), nullable=False)
    seller = Column(Text, nullable=False)  # Agent card URL of the listing seller
    buyer = Column(Text, nullable=True)    # Agent card URL of the buyer (when accepted)
    offer_resource = Column(JSON, nullable=False)  # JSON representation of ComputeResource or TokenResource
    demand_resource = Column(JSON, nullable=False)  # JSON representation of ComputeResource or TokenResource
    duration_hours = Column(Integer, nullable=False)
    seller_attestation = Column(Text, nullable=True)  # fulfillment attestation UID posted by seller
    buyer_attestation = Column(Text, nullable=True)   # escrow attestation UID locked by buyer
    oracle_address = Column(Text, nullable=True)
    status = Column(SQLEnum(OrderStatusEnum, name="liststatusenum"), nullable=False, default=OrderStatusEnum.open)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    agent = relationship("Agent")

    __table_args__ = (
        Index("idx_listings_agent_id", "agent_id"),
        Index("idx_listings_status", "status"),
        Index("idx_listings_created_at", "created_at"),
    )

