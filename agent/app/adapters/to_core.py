"""Convert legacy agent models into core schema models."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.schema.pydantic_models import Action, Decision, DecisionContext, DomainEvent

try:
    from core.schemas import (
        Decision as CoreDecision,
        DecisionContext as CoreDecisionContext,
        DomainAction as CoreDomainAction,
        DomainEvent as CoreDomainEvent,
    )
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from core.schemas import (  # type: ignore[no-redef]
        Decision as CoreDecision,
        DecisionContext as CoreDecisionContext,
        DomainAction as CoreDomainAction,
        DomainEvent as CoreDomainEvent,
    )


def event_payload_to_core_domain_event(payload: dict[str, Any]) -> CoreDomainEvent:
    """Normalize arbitrary event payload into a core DomainEvent."""
    event = DomainEvent.model_validate(payload)
    return legacy_domain_event_to_core(event)


def legacy_domain_event_to_core(event: DomainEvent) -> CoreDomainEvent:
    """Convert legacy DomainEvent to core DomainEvent."""
    event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    return CoreDomainEvent(
        event_id=event.event_id,
        event_type=event_type,
        source=event.source,
        timestamp=event.timestamp,
        data=event.data,
    )


def legacy_action_to_core(action: Action) -> CoreDomainAction:
    """Convert legacy Action to core DomainAction."""
    action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
    return CoreDomainAction(
        action_type=action_type,
        parameters=action.parameters,
        timestamp=action.timestamp,
    )


def legacy_decision_context_to_core(context: DecisionContext) -> CoreDecisionContext:
    """Convert legacy DecisionContext to core DecisionContext."""
    return CoreDecisionContext(
        event=legacy_domain_event_to_core(context.event),
        agent_id=context.agent_id,
        available_resources=context.available_resources,
        market_state=context.market_state,
        memory={
            "past_experiences": context.past_experiences,
            "negotiation_history": context.negotiation_history,
        },
    )


def legacy_decision_to_core(decision: Decision) -> CoreDecision:
    """Convert legacy Decision to core Decision."""
    return CoreDecision(
        action=legacy_action_to_core(decision.action),
    )

