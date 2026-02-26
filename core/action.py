"""Core action execution contracts and dispatcher."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import DomainAction


class ActionHandler(ABC):
    """Explicit base class for async action handlers."""

    @abstractmethod
    async def execute(self, action: DomainAction, **kwargs: Any) -> dict[str, Any]:
        """Execute an action and return a structured result."""


class ActionDispatcher:
    """Maps action types to concrete async handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, action_type: str, handler: ActionHandler) -> None:
        self._handlers[action_type] = handler

    def register_many(self, handlers: dict[str, ActionHandler]) -> None:
        for action_type, handler in handlers.items():
            self.register(action_type, handler)

    def has_handler(self, action_type: str) -> bool:
        return action_type in self._handlers

    async def dispatch(self, action: DomainAction, **kwargs: Any) -> dict[str, Any]:
        handler = self._handlers.get(action.action_type)
        if handler is None:
            raise ValueError(f"No action handler registered for '{action.action_type}'")
        return await handler.execute(action, **kwargs)
