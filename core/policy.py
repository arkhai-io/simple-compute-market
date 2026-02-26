"""Core policy contracts and evaluation engine."""

from __future__ import annotations

from typing import Protocol

from .schemas import DecisionContext, DomainAction


class Policy(Protocol):
    """Callable policy returning an optional action."""

    def __call__(self, context: DecisionContext) -> DomainAction | None:
        ...


class PolicyEngine:
    """Evaluates registered policies in order until one returns an action."""

    def __init__(self) -> None:
        self._policies: list[Policy] = []

    def register(self, policy: Policy) -> None:
        self._policies.append(policy)

    def register_many(self, policies: list[Policy]) -> None:
        self._policies.extend(policies)

    def evaluate(self, context: DecisionContext) -> DomainAction | None:
        for policy in self._policies:
            action = policy(context)
            if action is not None:
                return action
        return None
