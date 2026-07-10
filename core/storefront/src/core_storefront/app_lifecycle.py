"""Reusable storefront application lifecycle assembly.

Concrete storefront executables own their domain services and startup tasks, but
share the same lifespan shape: create singleton clients/services, publish them to
an executable container, then run domain startup hooks before accepting traffic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol


class LoggerLike(Protocol):
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True)
class StorefrontLifecycleCallbacks:
    """Callbacks required to assemble a storefront lifespan."""

    get_sqlite_client: Callable[[], Any]
    set_stage_event_db_path: Callable[[str], None]
    build_alkahest_clients: Callable[[], dict[str, Any]]
    build_listing_service: Callable[..., Any]
    build_negotiation_service: Callable[..., Any]
    build_system_service: Callable[..., Any]
    populate_container: Callable[..., None]
    startup_tasks: Callable[[], Awaitable[None]]
    logger: LoggerLike | None = None


def build_storefront_lifespan(callbacks: StorefrontLifecycleCallbacks) -> Callable[[Any], Any]:
    """Build a FastAPI-compatible lifespan function.

    The returned callable is intentionally typed against ``Any`` so this core
    module does not import FastAPI. Domain packages pass it directly to
    ``FastAPI(lifespan=...)`` via ``build_storefront_app``.
    """

    @asynccontextmanager
    async def lifespan(_: Any):
        sqlite_client = callbacks.get_sqlite_client()
        callbacks.set_stage_event_db_path(sqlite_client.db_path)
        alkahest_clients = callbacks.build_alkahest_clients()

        listing_service = callbacks.build_listing_service(
            sqlite_client=sqlite_client,
            alkahest_clients=alkahest_clients,
        )
        negotiation_service = callbacks.build_negotiation_service(
            sqlite_client=sqlite_client,
        )
        system_service = callbacks.build_system_service(
            sqlite_client=sqlite_client,
        )

        callbacks.populate_container(
            sqlite_client=sqlite_client,
            alkahest_clients=alkahest_clients,
            listing_service=listing_service,
            negotiation_service=negotiation_service,
            system_service=system_service,
        )

        if callbacks.logger is not None:
            callbacks.logger.info("[STARTUP] Singletons initialized")
        await callbacks.startup_tasks()
        if callbacks.logger is not None:
            callbacks.logger.info("[STARTUP] Background tasks started")

        yield

        if callbacks.logger is not None:
            callbacks.logger.info("[SHUTDOWN] Storefront shutting down")

    return lifespan
