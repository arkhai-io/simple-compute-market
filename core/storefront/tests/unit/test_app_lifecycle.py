from types import SimpleNamespace

import pytest

from core_storefront.app_lifecycle import (
    StorefrontLifecycleCallbacks,
    build_storefront_lifespan,
)


class CapturingLogger:
    def __init__(self):
        self.messages: list[str] = []

    def info(self, msg: str, *args, **kwargs) -> None:
        self.messages.append(msg)


@pytest.mark.asyncio
async def test_storefront_lifespan_builds_services_populates_container_and_runs_startup():
    events: list[str] = []
    db = SimpleNamespace(db_path="/tmp/storefront.db")
    container: dict[str, object] = {}
    logger = CapturingLogger()

    async def startup_tasks() -> None:
        events.append("startup")

    lifespan = build_storefront_lifespan(
        StorefrontLifecycleCallbacks(
            get_sqlite_client=lambda: events.append("db") or db,
            set_stage_event_db_path=lambda path: events.append(f"stage:{path}"),
            build_alkahest_clients=lambda: events.append("alkahest") or {"chain": object()},
            build_listing_service=lambda **kwargs: events.append("listing") or {"listing": kwargs},
            build_negotiation_service=lambda **kwargs: events.append("negotiation") or {"negotiation": kwargs},
            build_system_service=lambda **kwargs: events.append("system") or {"system": kwargs},
            populate_container=lambda **kwargs: events.append("container") or container.update(kwargs),
            startup_tasks=startup_tasks,
            logger=logger,
        )
    )

    async with lifespan(None):
        events.append("serving")

    assert events == [
        "db",
        "stage:/tmp/storefront.db",
        "alkahest",
        "listing",
        "negotiation",
        "system",
        "container",
        "startup",
        "serving",
    ]
    assert container["sqlite_client"] is db
    assert container["alkahest_clients"]
    assert logger.messages == [
        "[STARTUP] Singletons initialized",
        "[STARTUP] Background tasks started",
        "[SHUTDOWN] Storefront shutting down",
    ]
