from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from pydantic import BaseModel, Field

from app.schema.pydantic_models import Event, EventType, ComputeResource, MarketOrder


class ComparisonOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"


class Condition(BaseModel):
    field: str
    operator: ComparisonOperator
    value: Any


class ConditionGroupMode(str, Enum):
    ANY = "any"
    ALL = "all"


class ConditionGroup(BaseModel):
    mode: ConditionGroupMode = Field(default=ConditionGroupMode.ALL)
    conditions: list[Condition]


class ActionType(str, Enum):
    ACCEPT_OFFER = "accept_offer"
    REJECT_OFFER = "reject_offer"
    RESPOND_TO_ORDER = "respond_to_order"


class Action(BaseModel):
    action_type: str | ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None


class ActionSelection(BaseModel):
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class PolicyRule(BaseModel):
    name: str
    description: str
    trigger_type: str
    conditions: list[Condition] | ConditionGroup
    action: ActionSelection
    priority: int = 0


class DecisionContext(BaseModel):
    agent_id: str
    event: Event
    available_resources: dict[str, Any] = Field(default_factory=dict)
    market_state: dict[str, Any] = Field(default_factory=dict)
    negotiation_history: list[dict[str, Any]] = Field(default_factory=list)
    past_experiences: list[dict[str, Any]] = Field(default_factory=list)


def _get_field_from_context(context: DecisionContext, path: str) -> Any:
    # Supports dot paths like 'event.data.tag' or 'resources.total_gpus'
    root_map = {
        "event": context.event.model_dump(),
        "resources": context.available_resources,
        "market": context.market_state,
        "agent_id": context.agent_id,
    }
    parts = path.split(".")
    if not parts:
        return None
    head = parts[0]
    current: Any = root_map.get(head)
    if current is None and head == "agent_id":
        return context.agent_id
    for part in parts[1:]:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            break
    return current


def _compare(lhs: Any, op: ComparisonOperator, rhs: Any) -> bool:
    if op == ComparisonOperator.EQ:
        return lhs == rhs
    if op == ComparisonOperator.NE:
        return lhs != rhs
    if op == ComparisonOperator.GT:
        return lhs > rhs
    if op == ComparisonOperator.GTE:
        return lhs >= rhs
    if op == ComparisonOperator.LT:
        return lhs < rhs
    if op == ComparisonOperator.LTE:
        return lhs <= rhs
    if op == ComparisonOperator.IN:
        try:
            return lhs in rhs  # type: ignore[operator]
        except Exception:
            return False
    if op == ComparisonOperator.NOT_IN:
        try:
            return lhs not in rhs  # type: ignore[operator]
        except Exception:
            return False
    if op == ComparisonOperator.CONTAINS:
        try:
            return rhs in lhs  # type: ignore[operator]
        except Exception:
            return False
    return False


def conditions_match(context: DecisionContext, conds: list[Condition] | ConditionGroup) -> bool:
    if isinstance(conds, ConditionGroup):
        if conds.mode == ConditionGroupMode.ALL:
            return all(conditions_match(context, [c]) for c in conds.conditions)
        return any(conditions_match(context, [c]) for c in conds.conditions)
    # list of Condition
    for cond in conds:
        lhs = _get_field_from_context(context, cond.field)
        if not _compare(lhs, cond.operator, cond.value):
            return False
    return True


