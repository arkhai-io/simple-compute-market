from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from typing import Any

from compute_provisioning.startup import (
    ComputeProvisioningBackgroundTask,
    ComputeProvisioningShutdownStep,
    ComputeProvisioningStartupStep,
)

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.config import settings
from compute_provisioning_service.container import container
from compute_provisioning_service.db.migrations import check_schema_version
from compute_provisioning.jobs.queue import AsyncJobQueue
from compute_provisioning_service.services.definition_documents import (
    DefinitionDocumentImporter,
)

from compute_provisioning_ansible import DEFAULT_ANSIBLE_CONFIG

logger = logging.getLogger(__name__)


def refuse_retired_settings() -> None:
    """Refuse a configuration stating a setting the service no longer reads.

    Runs before any other step, so a stale profile stops the service before it
    composes anything that would ignore the key. The migration command does not
    refuse it: migration reads no operational configuration, so a retired key
    cannot change what it does.
    """
    settings.refuse_retired_settings()


def apply_ansible_config(
    config: Any = None, environ: MutableMapping[str, str] | None = None
) -> None:
    """Export ``ANSIBLE_CONFIG`` for every playbook the service runs.

    The profile's ``ansible_cfg`` when it names one, verbatim, so an operator's
    own configuration, a log file included, is never overridden; otherwise the
    Ansible distribution's own defaults, which belong to no domain and name no
    log file. Nothing else is exported: the service sets no log path.
    ``config`` is the service's settings and ``environ`` the process
    environment unless given.
    """
    config = settings if config is None else config
    environ = os.environ if environ is None else environ
    ansible_cfg = str(getattr(config, "ansible_cfg", "") or "").strip()
    environ["ANSIBLE_CONFIG"] = ansible_cfg or str(DEFAULT_ANSIBLE_CONFIG)
    logger.info("ANSIBLE_CONFIG set to %s", environ["ANSIBLE_CONFIG"])


def initialise_container_resources() -> None:
    """Wire the DI container and verify the DB schema is up to date.

    Migrations are not applied in-process here (see
    openspec/specs/deployment-state/spec.md, "Service-owned migration history")
    — they must be applied ahead of time via the Helm init container,
    ``compute-provisioning-migrate``, or ``make migrate``. This step only
    checks the schema version and fails fast with an actionable message if
    it's behind, so a missed migration surfaces as an obvious startup error
    rather than a query hitting a missing column later.
    """
    container.identity_context()
    container.init_resources()
    check_schema_version(container.db_engine())
    logger.info("Database schema check passed")


def resolve_request_path_services() -> None:
    # Resolve services as plain module-level variables so controllers
    # can retrieve them via a simple lambda, avoiding any provider
    # machinery on the request path (prevents asyncio.get_event_loop()
    # errors in AnyIO worker threads).
    _container_module.resolved_job_engine = container.job_engine()
    fulfillment_service = container.fulfillment_service()
    container.fulfillment_teardown_port().bind(fulfillment_service)
    _container_module.resolved_fulfillment_service = fulfillment_service
    _container_module.resolved_session_factory = container.session_factory()
    _container_module.resolved_ansible_service = container.ansible_service()
    _container_module.resolved_system_status_service = container.system_status_service()
    _container_module.resolved_inventory_views = container.inventory_views()
    composed = container.composed_adapters()
    _container_module.resolved_definition_documents = composed.definition_documents
    _container_module.resolved_background_tasks = composed.background_tasks
    _container_module.resolved_host_authority = container.host_authority()
    _container_module.resolved_connectivity_probes = container.connectivity_probes()
    _container_module.resolved_vm_operations_service = container.vm_operations_service()
    _container_module.resolved_host_operations_service = container.host_operations_service()
    _container_module.resolved_lease_lifecycle_service = container.lease_lifecycle_service()
    _container_module.resolved_lease_watchdog = container.lease_watchdog()
    _container_module.resolved_fulfillment_convergence_watchdog = (
        container.fulfillment_convergence_watchdog()
    )
    _container_module.resolved_capacity_ledger_service = container.capacity_ledger_service()
    _container_module.resolved_bare_metal_mock_executor = (
        container.bare_metal_mock_executor()
    )
    _container_module.resolved_executor_lease_service = container.executor_lease_service()
    _container_module.resolved_lease_route_service = container.lease_route_service()
    _container_module.resolved_resource_pool_service = container.resource_pool_service()
    _container_module.resolved_relay_service = container.relay_service()
    _container_module.resolved_physical_settlement_scheduler = (
        container.physical_settlement_scheduler()
    )
    _container_module.resolved_capacity_reservation_watchdog = (
        container.capacity_reservation_watchdog()
    )


def import_contributed_definitions_if_configured() -> None:
    _definition_importer(contributed=_definition_documents()).import_contributed_definitions()


def import_pool_definitions_if_configured() -> None:
    _definition_importer().import_pool_definitions()


def seed_initial_pools_if_fresh() -> None:
    """Seed a fresh site's pools from ``pool_seed_path``.

    Runs after the pool document import, which a configured document owns, and
    before the declaration check, which then reads the seeded pools too.
    Migration creates no pool, so this is how a site with no pool document
    starts with any.
    """
    _definition_importer().seed_initial_pools()


def verify_pool_declarations() -> None:
    """Refuse to start while any stored pool lacks valid declarations or a provider handler.

    Runs after the pool document import, so a changed document can repair
    pools before they are checked. A pool without advertisement and backing
    declarations must not reach the resource-pool projection, where a
    consumer could not tell it from a site that predates those declarations.
    A pool whose provider no registered handler serves cannot be read at
    all, and waiting does not repair stored state.
    """
    pool_service = _container_module.resolved_resource_pool_service
    pool_service.require_valid_stored_declarations()
    pool_service.require_served_stored_providers()
    logger.info("Resource-pool declaration and provider check passed")


def import_host_definitions_if_configured() -> None:
    """Reconcile the host definitions document ``host_definitions_path`` names.

    Runs after the declaration check, so every pool an entry names exists and
    is servable, and before capacity definitions, which may name a host. A
    document that cannot be applied fails the start whole, naming each problem,
    and records no digest; startup reads no INI inventory.
    """
    _definition_importer().import_host_definitions()


def import_capacity_definitions_if_configured() -> None:
    _definition_importer().import_capacity_definitions()


def _definition_documents():
    """Every contributed document kind, in composition order."""
    contributed = _container_module.resolved_definition_documents
    if contributed is None:
        raise RuntimeError("contributed definition documents are not composed")
    return contributed


def _definition_importer(contributed=()) -> DefinitionDocumentImporter:
    return DefinitionDocumentImporter(
        session_factory=_container_module.resolved_session_factory,
        settings=settings,
        pool_service=_container_module.resolved_resource_pool_service,
        contributed=contributed,
        capacity_ledger=_container_module.resolved_capacity_ledger_service,
        host_authority=_container_module.resolved_host_authority,
    )


def create_job_queue() -> None:
    # AsyncJobQueue is a plain object; instantiate inside the running event loop.
    _container_module.resolved_job_queue = AsyncJobQueue(
        max_concurrent=settings.max_concurrent_jobs
    )


def startup_steps() -> tuple[ComputeProvisioningStartupStep, ...]:
    return (
        ComputeProvisioningStartupStep("refuse-retired-settings", refuse_retired_settings),
        ComputeProvisioningStartupStep("apply-ansible-config", apply_ansible_config),
        ComputeProvisioningStartupStep(
            "initialise-container-resources",
            initialise_container_resources,
        ),
        ComputeProvisioningStartupStep(
            "resolve-request-path-services",
            resolve_request_path_services,
        ),
        # Contributed documents before pools: a pool's provider configuration
        # may reference what they declare, so a first boot from definition
        # documents needs it to exist before the pool that points at it.
        ComputeProvisioningStartupStep(
            "import-contributed-definitions",
            import_contributed_definitions_if_configured,
        ),
        ComputeProvisioningStartupStep(
            "import-pool-definitions", import_pool_definitions_if_configured
        ),
        ComputeProvisioningStartupStep("seed-initial-pools", seed_initial_pools_if_fresh),
        ComputeProvisioningStartupStep(
            "verify-pool-declarations", verify_pool_declarations
        ),
        ComputeProvisioningStartupStep(
            "import-host-definitions", import_host_definitions_if_configured
        ),
        ComputeProvisioningStartupStep(
            "import-capacity-definitions", import_capacity_definitions_if_configured
        ),
        ComputeProvisioningStartupStep("create-job-queue", create_job_queue),
    )


def background_tasks() -> tuple[ComputeProvisioningBackgroundTask, ...]:
    job_queue = _container_module.resolved_job_queue

    tasks: list[ComputeProvisioningBackgroundTask] = [
        ComputeProvisioningBackgroundTask(
            "job-processing-loop",
            lambda: job_queue.start(
                _container_module.resolved_job_engine.process_job
            ),
            "Job processing loop started (max_concurrent=%d)",
            (settings.max_concurrent_jobs,),
        )
    ]

    # Retry scheduler — re-enqueues queued jobs whose backoff delay has
    # elapsed (the failure path stamps next_retry_at but does not re-enqueue,
    # since the queue is in-process/transient).
    retry_poll_interval = float(
        getattr(settings, "retry_scheduler_poll_interval_seconds", 10)
    )
    tasks.append(
        ComputeProvisioningBackgroundTask(
            "retry-scheduler",
            lambda: _container_module.resolved_job_engine.run_retry_scheduler(
                job_queue, retry_poll_interval
            ),
            "Retry scheduler started (interval=%ds)",
            (int(retry_poll_interval),),
        )
    )

    # Lease watchdog — only started when enabled in config (default: true).
    watchdog_enabled = bool(getattr(settings, "lease_watchdog_enabled", True))
    if watchdog_enabled:
        tasks.append(
            ComputeProvisioningBackgroundTask(
                "lease-watchdog",
                lambda: _container_module.resolved_lease_watchdog.run(),
                "Lease watchdog started (interval=%ds grace=%ds)",
                (
                    getattr(settings, "lease_watchdog_poll_interval_seconds", 60),
                    getattr(settings, "lease_watchdog_grace_period_seconds", 300),
                ),
            )
        )
    else:
        logger.info("Lease watchdog disabled (lease_watchdog_enabled=false)")

    # Capacity reservation watchdog — only started when enabled in config
    # (default: true). Every reserve/commit/release call already lazily
    # sweeps expired holds; this only catches an otherwise-idle site.
    reservation_watchdog_enabled = bool(
        getattr(settings, "capacity_reservation_watchdog_enabled", True)
    )
    if reservation_watchdog_enabled:
        tasks.append(
            ComputeProvisioningBackgroundTask(
                "capacity-reservation-watchdog",
                lambda: _container_module.resolved_capacity_reservation_watchdog.run(),
                "Capacity reservation watchdog started (interval=%ds)",
                (
                    getattr(
                        settings,
                        "capacity_reservation_watchdog_poll_interval_seconds",
                        60,
                    ),
                ),
            )
        )
    else:
        logger.info(
            "Capacity reservation watchdog disabled "
            "(capacity_reservation_watchdog_enabled=false)"
        )

    # Fulfillment convergence watchdog retries durable dispatch work and
    # converges provider operations without holding database transactions
    # across provider calls.
    fulfillment_convergence_enabled = bool(
        getattr(settings, "fulfillment_convergence_watchdog_enabled", True)
    )
    if fulfillment_convergence_enabled:
        tasks.append(
            ComputeProvisioningBackgroundTask(
                "fulfillment-convergence-watchdog",
                lambda: _container_module.resolved_fulfillment_convergence_watchdog.run(),
                "Fulfillment convergence watchdog started (interval=%ds)",
                (
                    getattr(
                        settings,
                        "fulfillment_convergence_watchdog_poll_interval_seconds",
                        30,
                    ),
                ),
            )
        )
    else:
        logger.info(
            "Fulfillment convergence watchdog disabled "
            "(fulfillment_convergence_watchdog_enabled=false)"
        )

    contributed = _container_module.resolved_background_tasks
    if contributed is None:
        raise RuntimeError("contributed background tasks are not composed")
    return _unambiguous_tasks((*tasks, *contributed))


async def close_storefront_client() -> None:
    await container.lifecycle_event_sink().close()



def _unambiguous_tasks(tasks) -> tuple:
    """The tasks to start, refusing two with one name.

    Composition refuses a name two adapters contribute; this also refuses a
    contributed name the service already uses for one of its own workers, so
    every running task has the identity it declares.
    """
    seen: set[str] = set()
    for task in tasks:
        if task.name in seen:
            raise RuntimeError(f"two background tasks are named {task.name!r}")
        seen.add(task.name)
    return tuple(tasks)

def shutdown_steps() -> tuple[ComputeProvisioningShutdownStep, ...]:
    return (
        ComputeProvisioningShutdownStep(
            "close-storefront-client",
            close_storefront_client,
        ),
        ComputeProvisioningShutdownStep(
            "shutdown-container-resources",
            container.shutdown_resources,
        ),
    )
