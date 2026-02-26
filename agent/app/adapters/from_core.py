"""Convert core schema models into legacy agent models."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.schema.pydantic_models import (
    Action,
    ActionType,
    Decision,
    DecisionContext,
    DomainEvent,
)

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


def core_decision_context_to_legacy(context: CoreDecisionContext) -> DecisionContext:
    """Convert core DecisionContext to legacy DecisionContext."""
    memory = context.memory or {}
    return DecisionContext(
        event=core_domain_event_to_legacy(context.event),
        agent_id=context.agent_id,
        available_resources=context.available_resources,
        market_state=context.market_state,
        past_experiences=memory.get("past_experiences", []),
        negotiation_history=memory.get("negotiation_history", []),
    )


def core_decision_to_legacy(
    core_decision: CoreDecision,
    *,
    decision_id: str,
    agent_id: str,
    context: DecisionContext,
    policy_used: str,
) -> Decision:
    """Convert core Decision to legacy Decision."""
    if core_decision.action is None:
        raise ValueError("core_decision.action is required for legacy Decision")
    return Decision(
        decision_id=decision_id,
        agent_id=agent_id,
        context=context,
        action=core_domain_action_to_legacy(core_decision.action),
        policy_used=policy_used,
    )
