"""Domain-agnostic core schemas.

These models are intentionally minimal and stable so current agent code can
map in/out without immediate domain extraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Generic domain event transported through core orchestration."""

    event_id: str = Field(description="Unique event identifier")
    event_type: str = Field(description="Event type identifier")
    source: str = Field(description="Source identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class DomainAction(BaseModel):
    """Generic domain action selected by policy and executed by action handlers."""

    action_type: str = Field(description="Action type identifier")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Decision(BaseModel):
    """Policy decision."""

    action: DomainAction | None = Field(default=None)


class DecisionContext(BaseModel):
    """Domain-neutral policy evaluation context."""

    event: DomainEvent
    agent_id: str
    available_resources: dict[str, Any] = Field(default_factory=dict)
    market_state: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
