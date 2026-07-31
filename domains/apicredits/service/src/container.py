"""Composition root: build order and resolved singletons.

Plain module-level wiring — no provider framework. ``init()`` runs once
in the FastAPI lifespan; routers resolve services per request through
``lambda: resolved_X`` (the same access pattern the provisioning
service converged on, without the machinery it converged away from).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from config import settings
from market_site.ledger import CapacityLedgerService
from db.database import create_db_engine, create_session_factory, run_migrations
from services.keys_service import KeysService

resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_keys_service: "KeysService | None" = None


def init() -> None:
    """Build the engine, create tables, and wire the services."""
    global resolved_session_factory
    global resolved_capacity_ledger_service
    global resolved_keys_service

    engine = create_db_engine(settings.database_url, settings.is_sqlite)
    run_migrations(engine)
    resolved_session_factory = create_session_factory(engine)
    # No eligibility invariant: token quota resources carry no host
    # (unlike the VM site's required vm_host). Uses the domain-neutral
    # unit_claim_keys default (("units",)) — this domain has no VM-style
    # "gpu_count" alias to opt into.
    resolved_capacity_ledger_service = CapacityLedgerService(
        session_factory=resolved_session_factory,
    )
    resolved_keys_service = KeysService(
        session_factory=resolved_session_factory,
        capacity_ledger=resolved_capacity_ledger_service,
    )
