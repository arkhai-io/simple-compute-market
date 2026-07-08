from __future__ import annotations

from dependency_injector import containers, providers

from config import settings
from db.database import create_db_engine, create_session_factory
from services.ansible_service import AnsibleService
from services.async_job_queue import AsyncJobQueue
from services.bare_metal_lease_service import BareMetalLeaseService
from services.bare_metal_operations_service import BareMetalOperationsService
from core_site.ledger import CapacityLedgerService
from services.host_operations_service import HostOperationsService
from services.host_service import HostService
from services.job_service import AnsibleJobService
from services.lease_lifecycle_service import LeaseLifecycleService
from services.lease_watchdog import LeaseWatchdog
from services.release_executors import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalReleaseExecutor,
    ExecutorReleaseDispatcher,
    VM_EXECUTOR_KIND,
    VmReleaseExecutor,
)
from services.site_resources_service import SiteResourcesService
from services.system_service import SystemService
from services.vm_operations_service import VmOperationsService


def _resolved_job_queue():
    if resolved_job_queue is None:
        raise RuntimeError("Job queue is not initialised")
    return resolved_job_queue


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


def _make_release_dispatcher(bare_metal_operations_service, job_service):
    return ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(
            release_delegate=bare_metal_operations_service.reclaim_access_for_allocation,
        ),
        VM_EXECUTOR_KIND: VmReleaseExecutor(
            job_service=job_service,
            job_queue_provider=_resolved_job_queue,
        ),
    })


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

    vm_operations_service = providers.Factory(
        VmOperationsService,
        job_service=job_service,
        job_queue_provider=_resolved_job_queue,
    )

    host_operations_service = providers.Factory(
        HostOperationsService,
        ansible_service=ansible_service,
        host_service=host_service,
        job_service=job_service,
        job_queue_provider=_resolved_job_queue,
    )

    capacity_ledger_service = providers.Singleton(
        CapacityLedgerService,
        session_factory=session_factory,
    )

    site_resources_service = providers.Singleton(
        SiteResourcesService,
        capacity_service=capacity_ledger_service,
    )

    bare_metal_lease_service = providers.Singleton(
        BareMetalLeaseService,
        site_resources_service=site_resources_service,
    )

    bare_metal_operations_service = providers.Factory(
        BareMetalOperationsService,
        job_service=job_service,
        job_queue_provider=_resolved_job_queue,
        settings=config,
    )

    release_dispatcher = providers.Factory(
        _make_release_dispatcher,
        bare_metal_operations_service=bare_metal_operations_service,
        job_service=job_service,
    )

    lease_lifecycle_service = providers.Singleton(
        LeaseLifecycleService,
        settings=config,
        site_resources_service=site_resources_service,
        job_service=job_service,
        job_queue_provider=_resolved_job_queue,
        release_dispatcher=release_dispatcher,
    )

    lease_watchdog = providers.Singleton(
        LeaseWatchdog,
        lease_lifecycle_service=lease_lifecycle_service,
        settings=config,
    )

    system_service = providers.Singleton(
        SystemService,
        ansible_service=ansible_service,
        settings=config,
        host_service=host_service,
        session_factory=session_factory,
        job_queue_provider=_resolved_job_queue,
        lease_lifecycle_service=lease_lifecycle_service,
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
resolved_vm_operations_service: "VmOperationsService | None" = None
resolved_host_operations_service: "HostOperationsService | None" = None
resolved_lease_lifecycle_service: "LeaseLifecycleService | None" = None
resolved_lease_watchdog: "LeaseWatchdog | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_bare_metal_lease_service: "BareMetalLeaseService | None" = None
resolved_bare_metal_operations_service: "BareMetalOperationsService | None" = None
