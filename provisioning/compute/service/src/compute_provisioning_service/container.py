from __future__ import annotations

from typing import Any

from dependency_injector import containers, providers
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.executor_leases import ExecutorLeaseService
from compute_provisioning.release import ReleaseJobDispatcher
from market_resource_pools import ResourcePoolService
from market_site.authority import LedgerSiteAuthority
from market_site.ledger import CapacityLedgerService

from bare_metal_provisioning_adapter.runtime import build_bare_metal_runtime
from vm_provisioning_adapter.runtime import build_vm_runtime

from compute_provisioning_service.config import settings
from compute_provisioning_service.db.database import create_db_engine, create_session_factory
from compute_provisioning_service.identity import resolve_identity_context
from compute_provisioning_service.middleware.auth import (
    SqlAlchemyProvisioningReplayStore,
)
from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
from compute_provisioning_service.composition import compose_adapter_bundles
from compute_provisioning_service.services.compute_contract_service import ComputeContractService
from compute_provisioning_service.services.deal_event_sink import (
    SqlAlchemyCapacityReleaseOutbox,
    StorefrontLifecycleEventSink,
    notify_storefront_capacity_released,
)
from compute_provisioning_service.services.capacity_reservation_watchdog import CapacityReservationWatchdog
from compute_provisioning_service.services.fulfillment_convergence import FulfillmentConvergenceWatchdog
from compute_provisioning_service.services.lease_watchdog import LeaseWatchdog
from compute_provisioning_service.services.principal_authority import (
    SqlAlchemyProvisioningPrincipalAuthority,
)
from market_fulfillment import (
    PhysicalSettlementScheduler,
    SettlementRepository,
    SqlAlchemySchedulingUnitOfWork,
    FulfillmentOrchestrator,
    SqlAlchemyFulfillmentUnitOfWork,
)



def _resolved_job_queue():
    if resolved_job_queue is None:
        raise RuntimeError("Job queue is not initialised")
    return resolved_job_queue


class DeferredFulfillmentTeardownPort:
    """Cycle-safe narrow port bound once the fulfillment service is composed."""

    def __init__(self) -> None:
        self._service = None

    def bind(self, service) -> None:
        if self._service is not None and self._service is not service:
            raise RuntimeError("fulfillment teardown port is already bound")
        self._service = service

    def _require_service(self):
        if self._service is None:
            raise RuntimeError("fulfillment teardown port is not bound")
        return self._service

    async def begin_teardown(self, fulfillment_id: str) -> str:
        accepted = await self._require_service().begin_fulfillment_teardown(fulfillment_id)
        return accepted.fulfillment_id

    def get_status(self, fulfillment_id: str):
        return self._require_service().get_fulfillment_status(fulfillment_id)


def _make_engine():
    return create_db_engine(settings.database_url, settings.is_sqlite)


def _make_session_factory(engine):
    return create_session_factory(engine)


def _runtime_value(runtime, name):
    return getattr(runtime, name)



def _vm_bundle(runtime, site_authority):
    return runtime.adapter_bundle(site_authority)


def _bare_metal_bundle(runtime, site_authority):
    return runtime.adapter_bundle(site_authority)


def _system_service(runtime, lease_lifecycle_service):
    return runtime.system_service(lease_lifecycle_service=lease_lifecycle_service)


def _compose_adapters(vm_bundle, bare_metal_bundle):
    return compose_adapter_bundles([vm_bundle, bare_metal_bundle])


def _provider_registry(composed_adapters):
    return composed_adapters.provider_registry


def _pool_config_handlers(composed_adapters):
    return dict(composed_adapters.pool_config_handlers)


def _release_dispatcher(composed_adapters):
    return composed_adapters.release_dispatcher


def _make_release_job_dispatcher(vm_runtime, job_service):
    """Route release-job status reads: VM through the fulfillment
    aggregate, bare-metal through the shared job queue, unchanged.

    ``vm_runtime.release_job_port()`` is used rather than reading it off
    ``composed_adapters`` because ``ReleaseJobPort`` has no place in the
    generic ``ExecutorAdapterBundle`` contract -- it is specific to
    ``LeaseLifecycleService``'s polling loop, not a fulfillment-provider or
    executor-adapter concern the bundle already models.
    """

    return ReleaseJobDispatcher(
        {
            "vm": vm_runtime.release_job_port(),
            "bare_metal": job_service,
        },
    )


def _make_compute_contract_service(site_authority, job_service, composed_adapters):
    return ComputeContractService(
        site_authority=site_authority,
        job_service=job_service,
        adapters=composed_adapters.executor_registry,
    )


def _make_lease_lifecycle(
    cfg,
    site_authority,
    release_dispatcher,
    release_jobs,
    lifecycle_event_sink,
    capacity_release_outbox,
):
    return LeaseLifecycleService(
        cfg,
        site_authority,
        executor_release=release_dispatcher,
        release_jobs=release_jobs,
        capacity_released_notifier=(
            lambda reservation: notify_storefront_capacity_released(
                cfg, reservation, sink=lifecycle_event_sink
            )
        ),
        capacity_release_outbox=capacity_release_outbox,
    )


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

    identity_context = providers.Singleton(
        resolve_identity_context,
        settings=config,
    )

    provisioning_replay_store = providers.Singleton(
        SqlAlchemyProvisioningReplayStore,
        session_factory=session_factory,
    )

    # ------------------------------------------------------------------
    # Domain runtimes are loaded through adapter entry points. Generic
    # composition never imports concrete request/action/provider models.
    # ------------------------------------------------------------------

    # Declared here, ahead of vm_runtime, because VmReleaseExecutor and
    # VmFulfillmentReleaseJobPort (built inside vm_runtime) need it to
    # resolve a reservation's fulfillment_id. Also supplies the concrete
    # SettlementAbandonmentHook implementation the ledger calls when it
    # reclaims capacity that might belong to a not-yet-dispatched
    # settlement assignment (a lapsed hold, a terminal release, or a
    # negotiation-driven resize) -- market_site defines the hook protocol
    # but cannot import market_fulfillment to implement it.
    settlement_repository = providers.Singleton(SettlementRepository)

    fulfillment_teardown_port = providers.Singleton(DeferredFulfillmentTeardownPort)

    vm_runtime = providers.Singleton(
        build_vm_runtime,
        config=config,
        session_factory=session_factory,
        job_queue_provider=providers.Object(_resolved_job_queue),
        settlement_repository=settlement_repository,
        teardown_port=fulfillment_teardown_port,
    )

    ansible_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("ansible_service"),
    )
    host_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("host_service"),
    )
    ansible_pool_config_handler = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("pool_config_handler"),
    )
    job_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("job_service"),
    )
    vm_operations_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("vm_operations_service"),
    )
    host_operations_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("host_operations_service"),
    )

    capacity_ledger_service = providers.Singleton(
        CapacityLedgerService,
        session_factory=session_factory,
        # "gpu_count" is this domain's alias for the generic "units" claim
        # key — kept explicit here rather than hardcoded in kit/site so the
        # ledger stays domain-neutral.
        unit_claim_keys=("units", "gpu_count"),
        settlement_abandonment_hook=providers.Callable(
            lambda repository: repository.abandon_if_assigned,
            repository=settlement_repository,
        ),
    )

    site_authority = providers.Singleton(
        LedgerSiteAuthority,
        ledger=capacity_ledger_service,
    )

    bare_metal_runtime = providers.Singleton(
        build_bare_metal_runtime,
        site_authority=site_authority,
        job_service=job_service,
        job_queue_provider=providers.Object(_resolved_job_queue),
        config=config,
        host_service=host_service,
    )
    bare_metal_lease_service = providers.Callable(
        _runtime_value,
        runtime=bare_metal_runtime,
        name=providers.Object("lease_service"),
    )
    bare_metal_operations_service = providers.Callable(
        _runtime_value,
        runtime=bare_metal_runtime,
        name=providers.Object("operations_service"),
    )

    vm_adapter_bundle = providers.Singleton(
        _vm_bundle,
        runtime=vm_runtime,
        site_authority=site_authority,
    )

    bare_metal_adapter_bundle = providers.Singleton(
        _bare_metal_bundle,
        runtime=bare_metal_runtime,
        site_authority=site_authority,
    )

    composed_adapters = providers.Singleton(
        _compose_adapters,
        vm_bundle=vm_adapter_bundle,
        bare_metal_bundle=bare_metal_adapter_bundle,
    )

    composed_pool_config_handlers = providers.Singleton(
        _pool_config_handlers,
        composed_adapters=composed_adapters,
    )
    resource_pool_service = providers.Singleton(
        ResourcePoolService,
        session_factory=session_factory,
        handlers=composed_pool_config_handlers,
    )

    scheduling_unit_of_work = providers.Singleton(
        SqlAlchemySchedulingUnitOfWork,
        session_factory=session_factory,
        pool_service=resource_pool_service,
        capacity_ledger=capacity_ledger_service,
        repository=settlement_repository,
    )

    physical_settlement_scheduler = providers.Singleton(
        PhysicalSettlementScheduler,
        pool_service=resource_pool_service,
        capacity_ledger=capacity_ledger_service,
        session_factory=session_factory,
        # PhysicalSettlementScheduler does not silently default
        # resource_kind to "compute.gpu" -- the VM composition root
        # supplies it explicitly here to keep existing scheduling behavior
        # unchanged.
        default_resource_kind="compute.gpu",
        repository=settlement_repository,
        unit_of_work=scheduling_unit_of_work,
    )

    # ------------------------------------------------------------------
    # Fulfillment orchestration takes an already-selected SettlementResource as
    # input and never calls the scheduler itself.
    # ------------------------------------------------------------------
    capacity_reservation_watchdog = providers.Singleton(
        CapacityReservationWatchdog,
        capacity_ledger_service=capacity_ledger_service,
        settings=config,
    )

    executor_lease_service = providers.Singleton(
        ExecutorLeaseService,
        site_authority=site_authority,
    )

    provider_registry = providers.Singleton(
        _provider_registry,
        composed_adapters=composed_adapters,
    )

    release_dispatcher = providers.Singleton(
        _release_dispatcher,
        composed_adapters=composed_adapters,
    )

    release_job_dispatcher = providers.Singleton(
        _make_release_job_dispatcher,
        vm_runtime=vm_runtime,
        job_service=job_service,
    )

    compute_contract_service = providers.Factory(
        _make_compute_contract_service,
        site_authority=site_authority,
        job_service=job_service,
        composed_adapters=composed_adapters,
    )

    fulfillment_unit_of_work = providers.Singleton(
        SqlAlchemyFulfillmentUnitOfWork,
        session_factory=session_factory,
        pool_service=resource_pool_service,
        repository=settlement_repository,
    )

    fulfillment_service = providers.Singleton(
        FulfillmentOrchestrator,
        provider_registry=provider_registry,
        unit_of_work=fulfillment_unit_of_work,
    )

    principal_authority = providers.Singleton(
        SqlAlchemyProvisioningPrincipalAuthority,
        session_factory=session_factory,
        bootstrap=identity_context,
    )

    lifecycle_event_sink = providers.Singleton(
        StorefrontLifecycleEventSink,
        settings=config,
        identity=identity_context,
        principal_authority=principal_authority,
    )


    capacity_release_outbox = providers.Singleton(
        SqlAlchemyCapacityReleaseOutbox,
        session_factory=session_factory,
    )


    lease_lifecycle_service = providers.Singleton(
        _make_lease_lifecycle,
        cfg=config,
        site_authority=site_authority,
        release_dispatcher=release_dispatcher,
        release_jobs=release_job_dispatcher,
        lifecycle_event_sink=lifecycle_event_sink,
        capacity_release_outbox=capacity_release_outbox,
    )

    lease_watchdog = providers.Singleton(
        LeaseWatchdog,
        lease_lifecycle_service=lease_lifecycle_service,
        settings=config,
    )

    fulfillment_convergence_watchdog = providers.Singleton(
        FulfillmentConvergenceWatchdog,
        session_factory=session_factory,
        repository=settlement_repository,
        provider_registry=provider_registry,
        settings=config,
    )

    system_service = providers.Singleton(
        _system_service,
        runtime=vm_runtime,
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

resolved_job_service: Any | None = None
resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_ansible_service: Any | None = None
resolved_job_queue: "AsyncJobQueue | None" = None
resolved_system_service: Any | None = None
resolved_host_service: Any | None = None
resolved_vm_operations_service: Any | None = None
resolved_host_operations_service: Any | None = None
resolved_lease_lifecycle_service: "LeaseLifecycleService | None" = None
resolved_lease_watchdog: "LeaseWatchdog | None" = None
resolved_fulfillment_convergence_watchdog: "FulfillmentConvergenceWatchdog | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_bare_metal_lease_service: Any | None = None
resolved_bare_metal_operations_service: Any | None = None
resolved_executor_lease_service: "ExecutorLeaseService | None" = None
resolved_compute_contract_service = None
resolved_resource_pool_service: "ResourcePoolService | None" = None
resolved_relay_service: Any | None = None
resolved_physical_settlement_scheduler: "PhysicalSettlementScheduler | None" = None
resolved_fulfillment_service: "FulfillmentOrchestrator | None" = None
resolved_capacity_reservation_watchdog: "CapacityReservationWatchdog | None" = None
