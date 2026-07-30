from __future__ import annotations

import logging
import os

from compute_provisioning.startup import (
    ComputeProvisioningBackgroundTask,
    ComputeProvisioningShutdownStep,
    ComputeProvisioningStartupStep,
)

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.config import settings
from compute_provisioning_service.container import container
from compute_provisioning_service.db.migrations import check_schema_version
from compute_provisioning_service.services.async_job_queue import AsyncJobQueue

logger = logging.getLogger(__name__)


def apply_ansible_config() -> None:
    """Apply ANSIBLE_CONFIG from the active profile if configured."""

    ansible_cfg = str(getattr(settings, "ansible_cfg", "") or "").strip()
    if ansible_cfg:
        os.environ["ANSIBLE_CONFIG"] = ansible_cfg
        logger.info("ANSIBLE_CONFIG set to %s", ansible_cfg)


def initialise_container_resources() -> None:
    """Wire the DI container and verify the DB schema is up to date.

    Migrations are no longer applied in-process here (see ARCHITECTURE.md
    § Schema Migration Execution) — they must be applied ahead of time via
    the Helm init container, ``compute-provisioning-migrate``, or ``make migrate``.
    This step only checks the schema version and fails fast with an
    actionable message if it's behind, so a missed migration surfaces as an
    obvious startup error rather than a query hitting a missing column
    later.
    """
    container.init_resources()
    check_schema_version(container.db_engine())
    logger.info("Database schema check passed")


def resolve_request_path_services() -> None:
    # Resolve services as plain module-level variables so controllers
    # can retrieve them via a simple lambda, avoiding any provider
    # machinery on the request path (prevents asyncio.get_event_loop()
    # errors in AnyIO worker threads).
    _container_module.resolved_job_service = container.job_service()
    fulfillment_service = container.fulfillment_service()
    container.fulfillment_teardown_port().bind(fulfillment_service)
    _container_module.resolved_fulfillment_service = fulfillment_service
    _container_module.resolved_session_factory = container.session_factory()
    _container_module.resolved_ansible_service = container.ansible_service()
    _container_module.resolved_system_service = container.system_service()
    _container_module.resolved_host_service = container.host_service()
    _container_module.resolved_vm_operations_service = container.vm_operations_service()
    _container_module.resolved_host_operations_service = container.host_operations_service()
    _container_module.resolved_lease_lifecycle_service = container.lease_lifecycle_service()
    _container_module.resolved_lease_watchdog = container.lease_watchdog()
    _container_module.resolved_fulfillment_convergence_watchdog = (
        container.fulfillment_convergence_watchdog()
    )
    _container_module.resolved_capacity_ledger_service = container.capacity_ledger_service()
    _container_module.resolved_bare_metal_lease_service = container.bare_metal_lease_service()
    _container_module.resolved_bare_metal_operations_service = (
        container.bare_metal_operations_service()
    )
    _container_module.resolved_executor_lease_service = container.executor_lease_service()
    _container_module.resolved_compute_contract_service = container.compute_contract_service()
    _container_module.resolved_resource_pool_service = container.resource_pool_service()
    _container_module.resolved_physical_settlement_scheduler = (
        container.physical_settlement_scheduler()
    )
    _container_module.resolved_capacity_reservation_watchdog = (
        container.capacity_reservation_watchdog()
    )


def seed_inventory_if_empty() -> None:
    # ------------------------------------------------------------------
    # Inventory seeding — runs once at startup if the hosts table is empty.
    #
    # Source priority:
    #   1. inventory_ini setting (non-empty string) — used by the Helm chart,
    #      injected via the provisioning-secrets config profile.
    #   2. inventory_path on disk — used by the Docker profile, which points
    #      at the IAC hosts file baked into the image.
    #
    # Seeding is skipped when the hosts table already has rows, so that
    # operator changes made via the API (POST /hosts, PUT /hosts/{host}, etc.)
    # are not overwritten on pod restart.  To force a re-seed, use
    # POST /api/v1/hosts/import which always upserts regardless of table state.
    # ------------------------------------------------------------------
    host_service = _container_module.resolved_host_service
    existing_hosts = host_service.list_hosts(enabled_only=False)
    if existing_hosts:
        logger.info(
            "Inventory seeding: skipped — %d host(s) already registered",
            len(existing_hosts),
        )
        return

    inventory_ini = str(getattr(settings, "inventory_ini", "") or "").strip()
    inventory_path = getattr(settings, "resolved_inventory_path", None)

    ini_text: str | None = None
    source: str | None = None

    if inventory_ini:
        ini_text = inventory_ini
        source = "inventory_ini setting (provisioning-secrets profile)"
    elif inventory_path and inventory_path.exists():
        try:
            ini_text = inventory_path.read_text(encoding="utf-8")
            source = str(inventory_path)
        except OSError as exc:
            logger.warning("Inventory seeding: could not read %s: %s", inventory_path, exc)

    if ini_text:
        try:
            seeded = host_service.seed_from_ini(ini_text)
            logger.info(
                "Inventory seeding: registered %d host(s) from %s",
                len(seeded),
                source,
            )
        except Exception as exc:
            logger.error("Inventory seeding failed (source: %s): %s", source, exc)
    else:
        logger.info(
            "Inventory seeding: no inventory source configured — "
            "starting with empty host registry"
        )


def import_pool_definitions_if_configured() -> None:
    # ------------------------------------------------------------------
    # Pool-definitions import — runs at every startup when configured.
    #
    # Unlike the old "empty table" seeding idea, this always imports when
    # pool_definitions_path is set: import is idempotent/diff-based (see
    # ResourcePoolService.import_pools), so re-running it on every restart
    # is the correct behavior — the same idiom as the `inventory_ini`
    # setting ("parsed and upserted... at every service startup").
    #
    # The system-created "default" pool always exists by this point (the
    # resource_pools migration seeds it), so there is no "create default if
    # empty" fallback here — that concern moved into the migration.
    # ------------------------------------------------------------------
    path = getattr(settings, "resolved_pool_definitions_path", None)
    if path is None:
        logger.info("Pool-definitions import: no pool_definitions_path configured — skipped")
        return

    if not path.exists():
        raise FileNotFoundError(f"Configured pool-definitions file does not exist: {path}")

    pool_service = _container_module.resolved_resource_pool_service
    yaml_text = path.read_text(encoding="utf-8")
    diff = pool_service.import_pools(yaml_text, validate_only=False)
    logger.info(
        "Pool-definitions import from %s: created=%d updated=%d disabled=%d unchanged=%d",
        path,
        len(diff.created), len(diff.updated), len(diff.disabled), len(diff.unchanged),
    )


def create_job_queue() -> None:
    # AsyncJobQueue is a plain object; instantiate inside the running event loop.
    _container_module.resolved_job_queue = AsyncJobQueue(
        max_concurrent=settings.max_concurrent_jobs
    )


def startup_steps() -> tuple[ComputeProvisioningStartupStep, ...]:
    return (
        ComputeProvisioningStartupStep("apply-ansible-config", apply_ansible_config),
        ComputeProvisioningStartupStep(
            "initialise-container-resources",
            initialise_container_resources,
        ),
        ComputeProvisioningStartupStep(
            "resolve-request-path-services",
            resolve_request_path_services,
        ),
        ComputeProvisioningStartupStep("seed-inventory", seed_inventory_if_empty),
        ComputeProvisioningStartupStep(
            "import-pool-definitions", import_pool_definitions_if_configured
        ),
        ComputeProvisioningStartupStep("create-job-queue", create_job_queue),
    )


def background_tasks() -> tuple[ComputeProvisioningBackgroundTask, ...]:
    job_queue = _container_module.resolved_job_queue

    tasks: list[ComputeProvisioningBackgroundTask] = [
        ComputeProvisioningBackgroundTask(
            "job-processing-loop",
            lambda: job_queue.start(
                _container_module.resolved_job_service._process_job
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
            lambda: _container_module.resolved_job_service.run_retry_scheduler(
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

    return tuple(tasks)


def shutdown_steps() -> tuple[ComputeProvisioningShutdownStep, ...]:
    return (
        ComputeProvisioningShutdownStep(
            "shutdown-container-resources",
            container.shutdown_resources,
        ),
    )
