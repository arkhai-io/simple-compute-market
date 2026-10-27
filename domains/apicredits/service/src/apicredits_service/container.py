"""Composition root: build order and resolved singletons.

Plain module-level wiring. ``init()`` runs once in the FastAPI lifespan;
routers resolve services per request through ``lambda: resolved_X``.
"""

from __future__ import annotations

from arkhai_api_authority import (
    AuthorityRouteService,
    KeysService,
    SystemRouteService,
    create_db_engine,
    create_session_factory,
    initialize,
    run_migrations,
)
from market_site.ledger import CapacityLedgerService
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from apicredits_service.config import authority_config, settings

resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_keys_service: "KeysService | None" = None
resolved_route_service: "AuthorityRouteService | None" = None
resolved_system_service: "SystemRouteService | None" = None


def bootstrap(engine: Engine) -> None:
    """Migrate the schema, then seed and check the profile's pool."""
    run_migrations(engine)
    initialize(engine, authority_config.profile)


def init() -> None:
    """Build the engine, bootstrap the database, and wire the services."""
    global resolved_session_factory
    global resolved_capacity_ledger_service
    global resolved_keys_service
    global resolved_route_service
    global resolved_system_service

    engine = create_db_engine(authority_config.database_url, settings.is_sqlite)
    bootstrap(engine)
    resolved_session_factory = create_session_factory(engine)
    # No eligibility invariant: quota resources carry no host, and a quota is
    # counted in the ledger's neutral `units`.
    resolved_capacity_ledger_service = CapacityLedgerService(
        session_factory=resolved_session_factory,
    )
    resolved_keys_service = KeysService(
        session_factory=resolved_session_factory,
        capacity_ledger=resolved_capacity_ledger_service,
        config=authority_config,
    )
    resolved_route_service = AuthorityRouteService(resolved_keys_service)
    resolved_system_service = SystemRouteService(authority_config.distribution)
