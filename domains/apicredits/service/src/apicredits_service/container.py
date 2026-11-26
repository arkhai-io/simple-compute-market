"""Composition root: build order and resolved singletons.

Plain module-level wiring — no provider framework. ``init()`` runs once
in the FastAPI lifespan; routers resolve services per request through
``lambda: resolved_X`` (the same access pattern the provisioning
service converged on, without the machinery it converged away from).
"""

from __future__ import annotations

from market_resource_pools import ResourcePoolFacts
from sqlalchemy.orm import Session, sessionmaker

from apicredits_service.config import settings
from market_site.ledger import CapacityLedgerService
from apicredits_service.db.database import (
    create_db_engine,
    create_session_factory,
    initialise_database,
)
from apicredits_service.services.keys_service import KeysService

resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_keys_service: "KeysService | None" = None


def build_capacity_ledger(
    session_factory: "sessionmaker[Session]",
) -> CapacityLedgerService:
    """The site ledger over the service's database.

    Its pool reader is the pool authority's, over the ``resource_pools`` table
    the service seeds, with no host requirement: a quota is delivered through
    no host, so no pool needs one and admission is host-agnostic. No
    eligibility invariant either, since quota resources carry no host. It
    uses the domain-neutral unit claim keys (``("units",)``) and mirror
    dimension (``"units"``): a quota is counted in units and has no other
    alias.
    """
    return CapacityLedgerService(
        session_factory=session_factory,
        pool_facts=ResourcePoolFacts(),
    )


def init() -> None:
    """Build the engine, check and initialise the database, and wire the services.

    The database must already be migrated by ``apicredits-service-migrate``;
    one that is not is refused here, before any service is built.
    """
    global resolved_session_factory
    global resolved_capacity_ledger_service
    global resolved_keys_service

    engine = create_db_engine(settings.database_url, settings.is_sqlite)
    initialise_database(engine)
    resolved_session_factory = create_session_factory(engine)
    resolved_capacity_ledger_service = build_capacity_ledger(resolved_session_factory)
    resolved_keys_service = KeysService(
        session_factory=resolved_session_factory,
        capacity_ledger=resolved_capacity_ledger_service,
    )
