from __future__ import annotations

from dependency_injector import containers, providers

from config import settings
from db.database import create_db_engine, create_session_factory
from services.ansible_service import AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.host_service import HostService
from services.job_service import AnsibleJobService
from services.lease_check_service import LeaseCheckService
from services.lease_service import LeaseService
from services.lease_watchdog import LeaseWatchdog
from services.system_service import SystemService


def _make_ansible_service(cfg):
    """Return ProgrammableMockAnsibleService when ACTIVE_PROFILES includes 'mock'."""
    import os
    active = [p.strip() for p in os.environ.get("ACTIVE_PROFILES", "").split(",") if p.strip()]
    if "mock" in active:
        from services.mock_ansible_service import ProgrammableMockAnsibleService
        return ProgrammableMockAnsibleService(cfg)
    return AnsibleService(cfg)


def _make_engine():
    return create_db_engine(settings.database_url, settings.is_sqlite)


def _make_session_factory(engine):
    return create_session_factory(engine)


class Container(containers.DeclarativeContainer):
    """Application-level DI container.

    The ``job_queue`` Resource provider is intentionally absent: ``AsyncJobQueue``
    is a plain synchronous object (no async initialiser needed) and is
    instantiated directly in the FastAPI lifespan after ``init_resources()``.
    This avoids the ``asyncio.get_event_loop()`` issue that affects async
    Resource providers inside AnyIO worker threads.
    """

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    config = providers.Object(settings)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    db_engine = providers.Singleton(_make_engine)

    session_factory = providers.Singleton(
        _make_session_factory,
        engine=db_engine,
    )

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------
    ansible_service = providers.Singleton(
        _make_ansible_service,
        cfg=config,
    )

    host_service = providers.Singleton(
        HostService,
        session_factory=session_factory,
        settings=config,
    )

    job_service = providers.Singleton(
        AnsibleJobService,
        settings=config,
        session_factory=session_factory,
        ansible_service=ansible_service,
        host_service=host_service,
    )

    system_service = providers.Singleton(
        SystemService,
        ansible_service=ansible_service,
        settings=config,
        host_service=host_service,
    )

    lease_service = providers.Singleton(
        LeaseService,
        session_factory=session_factory,
    )

    lease_check_service = providers.Singleton(
        LeaseCheckService,
        lease_service=lease_service,
        settings=config,
        job_service=job_service,
    )

    lease_watchdog = providers.Singleton(
        LeaseWatchdog,
        lease_check_service=lease_check_service,
        settings=config,
    )


# Shared container instance — imported by main.py and all controllers.
container = Container()

# ---------------------------------------------------------------------------
# Resolved service instances.
# Populated once during FastAPI lifespan startup.
# Controllers reference these via Depends(lambda: resolved_X) so that
# dependency-injector's provider machinery is never invoked on the request
# path — avoiding asyncio.get_event_loop() calls inside AnyIO worker threads.
# ---------------------------------------------------------------------------
from sqlalchemy.orm import sessionmaker, Session  # noqa: E402

resolved_job_service: "AnsibleJobService | None" = None
resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_ansible_service: "AnsibleService | None" = None
resolved_job_queue: "AsyncJobQueue | None" = None
resolved_system_service: "SystemService | None" = None
resolved_host_service: "HostService | None" = None
resolved_lease_service: "LeaseService | None" = None
resolved_lease_check_service: "LeaseCheckService | None" = None
resolved_lease_watchdog: "LeaseWatchdog | None" = None
