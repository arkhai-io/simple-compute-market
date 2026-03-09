"""Core plugin interface for domain capability packs."""

from __future__ import annotations

from typing import Any, Callable, Protocol

Policy = Callable[[Any], Any]


class DomainPlugin(Protocol):
    """Contract structure implemented by optional domain modules."""

    @property
    def name(self) -> str:
        ...

    def event_types(self) -> set[str]:
        ...

    def action_handlers(self) -> dict[str, Any]:
        ...

    def policies(self) -> list[Policy]:
        ...
