"""Compatibility wiring for the core negotiation service."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from market_core.storefront.services.negotiation_service import (
    NegotiationService as _CoreNegotiationService,
    NegotiationServiceError,
)
from market_core.storefront.stage_log import stage_event
from market_storefront.utils.sync_negotiation import continue_sync_negotiation


class NegotiationService(_CoreNegotiationService):
    """Storefront-default negotiation service wiring."""

    def __init__(
        self,
        *,
        sqlite_client: Any,
        continue_negotiation: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        stage_event_fn: Callable[..., None] | None = None,
    ) -> None:
        async def _continue_proxy(**kwargs: Any) -> dict[str, Any]:
            return await continue_sync_negotiation(**kwargs)

        def _stage_event_proxy(*args: Any, **kwargs: Any) -> None:
            stage_event(*args, **kwargs)

        super().__init__(
            sqlite_client=sqlite_client,
            continue_negotiation=continue_negotiation or _continue_proxy,
            stage_event=stage_event_fn or _stage_event_proxy,
        )


__all__ = [
    "NegotiationService",
    "NegotiationServiceError",
    "continue_sync_negotiation",
    "stage_event",
]
