"""Core plugin interface for domain capability packs."""

from __future__ import annotations

from typing import Protocol

from .action import ActionHandler
from .policy import Policy


class DomainPlugin(Protocol):
    """Contract structure implemented by optional domain modules."""

    @property
    def name(self) -> str:
        ...

    def event_types(self) -> set[str]:
        ...

    def action_handlers(self) -> dict[str, ActionHandler]:
        ...

    def policies(self) -> list[Policy]:
        ...
