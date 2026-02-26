"""Core action execution contracts and dispatcher."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.schemas import DomainAction


class ActionHandler(ABC):
    """Explicit base class for async action handlers."""

    @abstractmethod
    async def execute(self, action: DomainAction, **kwargs: Any) -> dict[str, Any]:
        """Execute an action and return a structured result."""


class ActionDispatcher:
    """Maps action types to concrete async handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    @staticmethod
    def _normalize_action_type(action_type: Any) -> str:
        if hasattr(action_type, "value"):
            return str(action_type.value)
        return str(action_type)

    def register(self, action_type: str, handler: ActionHandler) -> None:
        self._handlers[self._normalize_action_type(action_type)] = handler

    def register_many(self, handlers: dict[str, ActionHandler]) -> None:
        for action_type, handler in handlers.items():
            self.register(action_type, handler)

    def has_handler(self, action_type: str) -> bool:
        return self._normalize_action_type(action_type) in self._handlers

    async def dispatch(self, action: DomainAction, **kwargs: Any) -> dict[str, Any]:
        handler = self._handlers.get(self._normalize_action_type(action.action_type))
        if handler is None:
            raise ValueError(
                f"No action handler registered for '{self._normalize_action_type(action.action_type)}'"
            )
        return await handler.execute(action, **kwargs)

