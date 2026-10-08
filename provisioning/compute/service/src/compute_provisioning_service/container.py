from __future__ import annotations

import os
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from dependency_injector import containers, providers
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.executor_leases import ExecutorLeaseService
from compute_provisioning import JobExecutorTable
from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_ansible import (
    ANSIBLE_COMPONENT,
    SSH_CONNECTION_KIND,
    MockAnsibleRunner,
    SshConnectionCodec,
    ansible_readiness_component,
    probe_connectivity,
)
from compute_provisioning_ansible.runner import AnsibleRunner
from compute_provisioning.leases import LeaseRouteService
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
)
from market_resource_pools import ResourcePoolService
from market_site.authority import LedgerSiteAuthority
from market_site.ledger import CapacityLedgerService

from bare_metal_provisioning_adapter.runtime import (
    HOST_REQUIREMENT as BARE_METAL_HOST_REQUIREMENT,
    build_bare_metal_runtime,
)
from vm_provisioning_adapter.runtime import (
    HOST_POOL_CHANGE_HOOKS as VM_HOST_POOL_CHANGE_HOOKS,
    HOST_REQUIREMENT as VM_HOST_REQUIREMENT,
    build_vm_runtime,
)
from compute_provisioning_service.services.capacity_derivation import (
    LegacyHostCapacityDerivation,
)

from compute_provisioning_service.config import settings
from compute_provisioning_service.db.database import create_db_engine, create_session_factory
from compute_provisioning_service.identity import resolve_identity_context
from compute_provisioning_service.middleware.auth import (
    SqlAlchemyProvisioningReplayStore,
)
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning import ReleaseEffects, compose_adapter_bundles
from compute_provisioning_service.services.deal_event_sink import (
    SqlAlchemyCapacityReleaseOutbox,
    StorefrontLifecycleEventSink,
    notify_storefront_capacity_released,
)
from compute_provisioning_service.services.capacity_reservation_watchdog import CapacityReservationWatchdog
from compute_provisioning_service.services.fulfillment_convergence import FulfillmentConvergenceWatchdog
from compute_provisioning_service.services.job_retry import retry_policy_from
from compute_provisioning_service.services.system_status import (
    StatusComponentProvider,
    SystemStatusService,
)
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



def _adapter_bundle(runtime):
    return runtime.adapter_bundle()


def _make_status_components(job_executors, host_authority):
    """The readiness components status reports, each built by its implementation.

    The Ansible implementation reports on every executor it built, whichever
    domain contributed it, and on the keys the registered hosts reference.
    """

    def ansible():
        return ansible_readiness_component(
            executors_by_offering_mode=job_executors.executors_by_offering_mode(),
            list_hosts=lambda: host_authority.list_hosts(enabled_only=True),
        )

    return (StatusComponentProvider(name=ANSIBLE_COMPONENT, collect=ansible),)


def _inventory_views(composed_adapters):
    return composed_adapters.inventory_views


def _merge_host_requirements(*requirements: Mapping[str, bool]) -> Mapping[str, bool]:
    """One provider -> needs-host map for the ledger, scheduler, and composition.

    Built from each adapter package's static declaration, because the ledger
    exists before any provider instance does. Composition then refuses to start
    if the result disagrees with the providers it registers.
    """
    merged: dict[str, bool] = {}
    for requirement in requirements:
        for provider, needs_host in requirement.items():
            if provider in merged:
                raise ValueError(
                    f"provider {provider!r} declares its host requirement twice"
                )
            merged[provider] = needs_host
    return MappingProxyType(merged)


def _make_host_authority(session_factory, cfg, capacity_derivation, pool_change_hooks):
    """The one host authority: every connection kind's codec and every hook.

    The ``ssh`` codec is the Ansible implementation's, protecting a submitted
    key with the service's decryption key; pool-change hooks are the adapters'
    static declarations, merged here because the authority exists before any
    runtime does.
    """
    return HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([SshConnectionCodec(cfg.ssh_decryption_key)]),
        capacity_derivation=capacity_derivation,
        pool_change_hooks=tuple(pool_change_hooks),
    )


def _mock_profile_active() -> bool:
    profiles = os.environ.get("ACTIVE_PROFILES", "")
    return "mock" in {profile.strip() for profile in profiles.split(",")}


def _probe_only(playbook) -> str:
    raise RuntimeError("the connectivity probe runner runs no playbook")


def _make_probe_runner(cfg):
    """The runner connectivity probes use, belonging to no domain.

    The real Ansible runner, or under the mock profile the mock, whose every
    registered host is reachable. It probes; it never runs a playbook.
    """
    if _mock_profile_active():
        return MockAnsibleRunner(default_output=_probe_only)
    return AnsibleRunner(cfg)


def _make_connectivity_probes(runner) -> Mapping[str, Any]:
    """Each connection kind's probe; the Ansible implementation probes ``ssh``."""

    async def probe_ssh(host):
        return await probe_connectivity(runner, host)

    return MappingProxyType({SSH_CONNECTION_KIND: probe_ssh})


def _make_job_engine(session_factory, job_executors, host_authority, cfg):
    """The one job authority every domain submits to and every route reads."""
    return JobEngine(
        session_factory,
        executors=job_executors,
        host_lookup=host_authority.lookup,
        retry_policy=retry_policy_from(cfg),
    )


def _make_release_effects():
    """The one registry of what domains return with a reservation's capacity.

    Created empty, filled and frozen by adapter composition, and run by the
    site ledger in every transaction that releases capacity.
    """
    return ReleaseEffects()


def _compose_adapters(
    vm_bundle, bare_metal_bundle, host_requirement, job_executors, release_effects
):
    return compose_adapter_bundles(
        [vm_bundle, bare_metal_bundle],
        host_requirement=host_requirement,
        job_executors=job_executors,
        release_effects=release_effects,
    )


def _provider_registry(composed_adapters):
    return composed_adapters.provider_registry


def _pool_config_handlers(composed_adapters):
    return dict(composed_adapters.pool_config_handlers)


def _make_lease_lifecycle(
    cfg,
    site_authority,
    release_executor,
    release_status,
    lifecycle_event_sink,
    capacity_release_outbox,
):
    return LeaseLifecycleService(
        cfg,
        site_authority,
        release_executor=release_executor,
        release_status=release_status,
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

    # Declared ahead of the ledger: the release guard the ledger consults on
    # every capacity reclaim reads the fulfillment aggregate through it.
    # market_site defines the guard protocol but cannot import
    # market_fulfillment to implement it.
    settlement_repository = providers.Singleton(SettlementRepository)

    fulfillment_teardown_port = providers.Singleton(DeferredFulfillmentTeardownPort)

    # Declared ahead of the ledger, which runs it whenever it releases capacity.
    release_effects = providers.Singleton(_make_release_effects)

    host_requirement = providers.Object(
        _merge_host_requirements(VM_HOST_REQUIREMENT, BARE_METAL_HOST_REQUIREMENT)
    )

    capacity_ledger_service = providers.Singleton(
        CapacityLedgerService,
        session_factory=session_factory,
        host_requirement=host_requirement,
        # "gpu_count" is this domain's alias for the generic "units" claim
        # key and the dimension its legacy scalar mirrors — kept explicit here
        # rather than hardcoded in kit/site so the ledger stays domain-neutral.
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        # Capacity returns only on fulfillment's proof that nothing remains
        # delivered, whoever asks the site to free it.
        release_guard=providers.Singleton(
            FulfillmentReleaseGuard,
            settlement_repository=settlement_repository,
        ),
        release_effect=release_effects,
    )

    # Declared ahead of vm_runtime: host inventory derives capacity
    # declarations from INI hosts through this port, inside its own upsert
    # transaction.
    capacity_derivation = providers.Singleton(
        LegacyHostCapacityDerivation,
        ledger=capacity_ledger_service,
    )

    # Filled and frozen by adapter composition; the job engine resolves each
    # job's executor through it.
    job_executor_table = providers.Singleton(JobExecutorTable)

    host_pool_change_hooks = providers.Object(VM_HOST_POOL_CHANGE_HOOKS)

    host_authority = providers.Singleton(
        _make_host_authority,
        session_factory=session_factory,
        cfg=config,
        capacity_derivation=capacity_derivation,
        pool_change_hooks=host_pool_change_hooks,
    )

    probe_runner = providers.Singleton(_make_probe_runner, cfg=config)

    connectivity_probes = providers.Singleton(
        _make_connectivity_probes, runner=probe_runner
    )

    job_engine = providers.Singleton(
        _make_job_engine,
        session_factory=session_factory,
        job_executors=job_executor_table,
        host_authority=host_authority,
        cfg=config,
    )

    # Every job, a fulfillment's or an operator's, is submitted through this.
    job_submission = providers.Singleton(
        JobSubmissionService,
        engine=job_engine,
        hosts=host_authority,
        job_queue_provider=providers.Object(_resolved_job_queue),
    )

    vm_runtime = providers.Singleton(
        build_vm_runtime,
        config=config,
        session_factory=session_factory,
        job_queue_provider=providers.Object(_resolved_job_queue),
        host_authority=host_authority,
        job_engine=job_engine,
        job_submission=job_submission,
    )

    ansible_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("ansible_service"),
    )
    ansible_pool_config_handler = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("pool_config_handler"),
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
    relay_service = providers.Callable(
        _runtime_value,
        runtime=vm_runtime,
        name=providers.Object("relay_service"),
    )

    site_authority = providers.Singleton(
        LedgerSiteAuthority,
        ledger=capacity_ledger_service,
    )

    bare_metal_runtime = providers.Singleton(
        build_bare_metal_runtime,
        job_engine=job_engine,
        job_submission=job_submission,
        config=config,
    )
    bare_metal_mock_executor = providers.Callable(
        _runtime_value,
        runtime=bare_metal_runtime,
        name=providers.Object("mock_executor"),
    )

    vm_adapter_bundle = providers.Singleton(_adapter_bundle, runtime=vm_runtime)

    bare_metal_adapter_bundle = providers.Singleton(
        _adapter_bundle, runtime=bare_metal_runtime
    )

    composed_adapters = providers.Singleton(
        _compose_adapters,
        vm_bundle=vm_adapter_bundle,
        bare_metal_bundle=bare_metal_adapter_bundle,
        host_requirement=host_requirement,
        job_executors=job_executor_table,
        release_effects=release_effects,
    )

    inventory_views = providers.Singleton(
        _inventory_views,
        composed_adapters=composed_adapters,
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
        host_requirement=host_requirement,
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

    release_executor = providers.Singleton(
        FulfillmentReleaseExecutor,
        settlement_repository=settlement_repository,
        session_factory=session_factory,
        teardown_port=fulfillment_teardown_port,
    )

    release_status = providers.Singleton(
        FulfillmentReleaseStatusPort,
        teardown_port=fulfillment_teardown_port,
    )

    fulfillment_unit_of_work = providers.Singleton(
        SqlAlchemyFulfillmentUnitOfWork,
        session_factory=session_factory,
        pool_service=resource_pool_service,
        repository=settlement_repository,
        # So dispatch acknowledgement can record the provider's create-job
        # handle on the reservation, the same ledger the scheduling unit of
        # work above already holds.
        capacity_ledger=capacity_ledger_service,
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
        release_executor=release_executor,
        release_status=release_status,
        lifecycle_event_sink=lifecycle_event_sink,
        capacity_release_outbox=capacity_release_outbox,
    )

    lease_route_service = providers.Singleton(
        LeaseRouteService,
        leases=executor_lease_service,
        lifecycle=lease_lifecycle_service,
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
        capacity_ledger=capacity_ledger_service,
    )

    status_components = providers.Singleton(
        _make_status_components,
        job_executors=job_executor_table,
        host_authority=host_authority,
    )

    system_status_service = providers.Singleton(
        SystemStatusService,
        settings=config,
        session_factory=session_factory,
        job_queue_provider=providers.Object(_resolved_job_queue),
        lease_lifecycle=lease_lifecycle_service,
        job_executors=job_executor_table,
        components=status_components,
        identity_resolver=providers.Object(lambda: resolve_identity_context(settings)),
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

resolved_job_engine: "JobEngine | None" = None
resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_ansible_service: Any | None = None
resolved_job_queue: "AsyncJobQueue | None" = None
resolved_system_status_service: "SystemStatusService | None" = None
resolved_inventory_views: Any | None = None
resolved_definition_documents: "tuple[Any, ...] | None" = None
resolved_background_tasks: "tuple[Any, ...] | None" = None
resolved_host_authority: "HostAuthority | None" = None
resolved_connectivity_probes: Mapping[str, Any] | None = None
resolved_vm_operations_service: Any | None = None
resolved_host_operations_service: Any | None = None
resolved_lease_lifecycle_service: "LeaseLifecycleService | None" = None
resolved_lease_watchdog: "LeaseWatchdog | None" = None
resolved_fulfillment_convergence_watchdog: "FulfillmentConvergenceWatchdog | None" = None
resolved_capacity_ledger_service: "CapacityLedgerService | None" = None
resolved_bare_metal_mock_executor: Any | None = None
resolved_executor_lease_service: "ExecutorLeaseService | None" = None
resolved_lease_route_service: "LeaseRouteService | None" = None
resolved_resource_pool_service: "ResourcePoolService | None" = None
resolved_relay_service: Any | None = None
resolved_physical_settlement_scheduler: "PhysicalSettlementScheduler | None" = None
resolved_fulfillment_service: "FulfillmentOrchestrator | None" = None
resolved_capacity_reservation_watchdog: "CapacityReservationWatchdog | None" = None
