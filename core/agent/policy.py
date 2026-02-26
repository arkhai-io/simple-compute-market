"""Core policy contracts and evaluation engine."""

from __future__ import annotations

from inspect import isawaitable
from typing import Awaitable, Callable, Protocol

from core.schemas import DecisionContext, DomainAction


class Policy(Protocol):
    """Callable policy returning an optional action (sync or async)."""

    def __call__(
        self, context: DecisionContext
    ) -> DomainAction | None | Awaitable[DomainAction | None]:
        ...


class PolicyEngine:
    """Evaluates registered policies in order until one returns an action."""

    def __init__(self) -> None:
        self._policies: list[Policy] = []

    def register(self, policy: Policy) -> None:
        self._policies.append(policy)

    def register_many(self, policies: list[Policy]) -> None:
        self._policies.extend(policies)

    async def evaluate(self, context: DecisionContext) -> DomainAction | None:
        for policy in self._policies:
            action = policy(context)
            if isawaitable(action):
                action = await action
            if action is not None:
                return action
        return None


def chain_callables(
    names: list[str],
    *,
    registry: dict[str, Callable[[DecisionContext], DomainAction | None]],
) -> Callable[[DecisionContext], DomainAction | None]:
    """Chain callables, returning the first non-None action."""

    def _impl(context: DecisionContext) -> DomainAction | None:
        for name in names:
            func = registry.get(name)
            if not func:
                continue
            act = func(context)
            if act is not None:
                return act
        return None

    return _impl

