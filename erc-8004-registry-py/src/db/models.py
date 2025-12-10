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
    
    agent_id = Column(String, primary_key=True)
    chain_id = Column(Integer, nullable=False)
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

