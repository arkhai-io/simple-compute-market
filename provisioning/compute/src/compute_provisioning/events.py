"""Narrow lifecycle-event sinks with duplicate-delivery protection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from .contracts import LifecycleEvent


class LifecycleEventSink(Protocol):
    async def deliver(self, event: LifecycleEvent) -> bool:
        """Deliver an event; return False when its identity was already handled."""


class IdempotentLifecycleEventSink:
    """Process each event identity once for the lifetime of this sink instance."""

    def __init__(self, deliver: Callable[[LifecycleEvent], Awaitable[None]]) -> None:
        self._deliver = deliver
        self._delivered: set[str] = set()

    async def deliver(self, event: LifecycleEvent) -> bool:
        if event.event_id in self._delivered:
            return False
        await self._deliver(event)
        self._delivered.add(event.event_id)
        return True
