"""Convert core schema models into legacy agent models."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.schema.pydantic_models import (
    Action,
    ActionType,
    DomainEvent
)

try:
    from core.schemas import (
        DomainAction as CoreDomainAction,
        DomainEvent as CoreDomainEvent,
    )
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from core.schemas import (  # type: ignore[no-redef]
        DomainAction as CoreDomainAction,
        DomainEvent as CoreDomainEvent,
    )


def core_domain_event_to_payload(event: CoreDomainEvent) -> dict[str, Any]:
    """Convert core DomainEvent to normalized event payload."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "source": event.source,
        "timestamp": event.timestamp.isoformat(),
        "data": event.data,
    }


def core_domain_event_to_legacy(event: CoreDomainEvent) -> DomainEvent:
    """Convert core DomainEvent to legacy DomainEvent."""
    return DomainEvent.model_validate(core_domain_event_to_payload(event))


def core_domain_action_to_legacy(action: CoreDomainAction) -> Action:
    """Convert core DomainAction to legacy Action."""
    return Action(
        action_type=ActionType(action.action_type),
        parameters=action.parameters,
        timestamp=action.timestamp,
    )
