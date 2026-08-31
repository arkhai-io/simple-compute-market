"""Storefront startup hooks.

After the pluggable-identity refactor (Phase 4) the storefront's identity is
just ``settings.wallet.address``. There is no per-chain on-chain registration
step, no agent-card publication, and no heartbeat loop.
"""

import asyncio
import logging
from functools import partial
from typing import Any

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    StorefrontStartupStep,
    run_storefront_startup_steps,
    start_storefront_background_task,
)
from core_storefront.stage_log import stage_event
from market_core import MarketDomainContract
from market_storefront_kit import (
    NegotiationWatchdogPolicy,
    run_negotiation_watchdog,
)

from market_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    settings,
)
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(settings.log_file_path or None, settings.log_level)

logger = logging.getLogger(__name__)




async def _preflight_provisioning() -> None:
    """Block startup until the provisioning service responds, or give up."""
    import httpx

    url = settings.provisioning.service_url.rstrip("/") + "/health"
    timeout_s = max(int(settings.provisioning.preflight_timeout), 1)
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_error: str | None = None
    attempt = 0

    while True:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.get(url)
            if resp.status_code == 200:
                logger.info(
                    "[STARTUP] Provisioning service reachable at %s (attempt %d)",
                    settings.provisioning.service_url,
                    attempt,
                )
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(2.0, remaining))

    msg = (
        f"[STARTUP] Provisioning service at {settings.provisioning.service_url} "
        f"unreachable after {timeout_s}s ({last_error}). "
        "For e2e tests without hardware, set ACTIVE_PROFILES=mock on the "
        "provisioning-service container."
    )
    if settings.provisioning.fail_on_unreachable:
        raise RuntimeError(
            msg + " Set [seller.provisioning].fail_on_unreachable = false "
            "to start the storefront anyway (fulfillment will fail until the "
            "service is reachable)."
        )
    logger.error(msg + " Continuing because fail_on_unreachable=false.")


def _maybe_join_zerotier_network() -> None:
    """Join the configured ZeroTier network using the local CLI, if any."""
    network = settings.zerotier_network
    if not network:
        return
    import subprocess

    try:
        subprocess.run(
            ["sudo", "zerotier-cli", "join", network],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("[STARTUP] Joined ZeroTier network %s", network)
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        logger.warning(
            "[STARTUP] ZeroTier join failed for network=%s: %s. "
            "The storefront will continue serving on its host network.",
            network,
            exc,
        )


def _initialize_negotiation_thread_store() -> None:
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    import market_storefront.container as _container

    storefront_url = BASE_URL_OVERRIDE or f"http://localhost:{settings.port}"
    get_thread_store(
        sqlite_client=_container.resolved_sqlite_client,
        identity=Identity(agent_url=storefront_url),
    )
    logger.info(
        "[STARTUP] Negotiation thread store initialized (storefront_url=%s)",
        storefront_url,
    )


async def _seed_resources_if_empty() -> None:
    import market_storefront.container as _container

    result = await _container.resolved_system_service.seed_resources_if_empty(
        csv_inline=settings.resources_csv_inline,
        csv_path=settings.resources_csv_path,
    )
    if result["seeded"]:
        logger.info(
            "[STARTUP] Seeded %d resource(s) from %s",
            result["imported_count"],
            result["source"],
        )
    elif result["source"] is None:
        logger.info(
            "[STARTUP] No resource source configured - starting with empty inventory"
        )
    else:
        logger.info(
            "[STARTUP] Resource seeding skipped - %d resource(s) already present",
            result["imported_count"],
        )


def _negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    return NegotiationWatchdogPolicy(
        timeout_seconds=float(settings.negotiation_timeout_seconds),
        interval_seconds=float(settings.negotiation_watchdog_interval),
    )


def _start_negotiation_watchdog(sqlite_client: Any) -> None:
    policy = _negotiation_watchdog_policy()
    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="negotiation_watchdog",
            task_factory=partial(
                run_negotiation_watchdog,
                sqlite_client,
                policy,
                emit_stage_event=stage_event,
                logger=logger,
            ),
            log_message=(
                "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)"
            ),
            log_args=(
                policy.interval_seconds,
                policy.timeout_seconds,
            ),
        ),
        logger=logger,
    )


async def _preflight_settlement_mechanisms() -> None:
    import market_storefront.container as _container
    from market_storefront.settlement_composition import (
        preflight_settlement_mechanisms,
    )

    composition = _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    await preflight_settlement_mechanisms(composition)


async def _backfill_escrow_identity(sqlite_client: Any) -> None:
    import market_storefront.container as _container
    from core_storefront.escrow_identity import backfill_escrow_obligation_records

    composition = _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    backfilled = await backfill_escrow_obligation_records(
        sqlite_client=sqlite_client,
        settlement_runtime=composition.runtime,
        local_principal=composition.local_principal,
    )
    if backfilled:
        logger.info(
            "[STARTUP] Backfilled %d legacy escrow obligation records",
            backfilled,
        )


def _start_settlement_servicing() -> None:
    import market_storefront.container as _container

    composition = _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="settlement_servicing",
            task_factory=composition.worker.run,
            log_message="[STARTUP] Settlement servicing started (interval=%ss)",
            log_args=(getattr(settings, "claims_sweep_interval", 30),),
        ),
        logger=logger,
    )


def _start_fulfillment_resume(sqlite_client: Any) -> None:
    from market_storefront.services.fulfillment_resume_runtime import (
        fulfillment_resume_loop,
    )

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="fulfillment_resume",
            task_factory=partial(fulfillment_resume_loop, sqlite_client),
            log_message="[STARTUP] Fulfillment resume worker started (interval=%ss)",
            log_args=(getattr(settings, "fulfillment_resume_sweep_interval", 30),),
        ),
        logger=logger,
    )


def _start_capacity_events_poller(sqlite_client: Any) -> None:
    # Tail every authority's capacity-event feed after provisioning preflight.
    from market_storefront.services.capacity_client import capacity_events_poller_loop

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="capacity_events_poller",
            task_factory=partial(capacity_events_poller_loop, sqlite_client),
        ),
        logger=logger,
    )


async def _load_site_projections(sqlite_client: Any) -> None:
    from market_storefront.services.site_projection_cache import load_site_projections

    await load_site_projections(sqlite_client)


def _start_site_projection_poller(sqlite_client: Any) -> None:
    from market_storefront.services.site_projection_cache import (
        site_projection_poller_loop,
    )

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="site_projection_poller",
            task_factory=partial(site_projection_poller_loop, sqlite_client),
        ),
        logger=logger,
    )


def _assert_startup_registry(registry: Any, domain: MarketDomainContract) -> Any:
    """Reject mixed composition before preflight or background work."""
    import market_storefront.container as _container

    sqlite_client = _container.resolved_sqlite_client
    listing_service = _container.resolved_listing_service
    negotiation_service = _container.resolved_negotiation_service
    settlement_composition = _container.resolved_settlement_composition
    negotiation_runtime = _container.resolved_negotiation_runtime
    callback = getattr(negotiation_service, "_continue_negotiation", None)
    callback_runtime = getattr(callback, "__self__", None)
    collaborators = (
        ("container", _container.resolved_domain_registry),
        ("SQLite repository", getattr(sqlite_client, "domain_registry", None)),
        ("listing service", getattr(listing_service, "domain_registry", None)),
    )
    for label, collaborator_registry in collaborators:
        if collaborator_registry is not registry:
            raise RuntimeError(
                f"{label} is not bound to the app-selected storefront "
                "domain registry object"
            )
    if callback_runtime is not negotiation_runtime:
        raise RuntimeError(
            "negotiation callback is not bound to the app-selected "
            "negotiation runtime object"
        )
    if registry.registration_for_contract(domain).contract is not domain:
        raise RuntimeError("settlement domain is not the startup-owned contract")
    if getattr(settlement_composition, "domain", None) is not domain:
        raise RuntimeError(
            "settlement composition is not bound to its registered contract"
        )
    return sqlite_client


async def _startup_tasks(*, registry: Any, domain: MarketDomainContract) -> None:
    """Initialize background tasks for one frozen storefront registry."""
    sqlite_client = _assert_startup_registry(registry, domain)
    await run_storefront_startup_steps(
        (
            StorefrontStartupStep("join_zerotier", _maybe_join_zerotier_network),
            StorefrontStartupStep(
                "negotiation_thread_store",
                _initialize_negotiation_thread_store,
            ),
            StorefrontStartupStep(
                "seed_resources",
                _seed_resources_if_empty,
                error_message="[STARTUP] Resource seeding failed: %s",
            ),
            StorefrontStartupStep(
                "negotiation_watchdog",
                partial(_start_negotiation_watchdog, sqlite_client),
            ),
            StorefrontStartupStep(
                "settlement_mechanism_preflight",
                _preflight_settlement_mechanisms,
            ),
            StorefrontStartupStep(
                "escrow_identity_backfill",
                partial(_backfill_escrow_identity, sqlite_client),
                error_message="[STARTUP] Escrow identity backfill failed: %s",
            ),
            StorefrontStartupStep("settlement_servicing", _start_settlement_servicing),
            StorefrontStartupStep(
                "fulfillment_resume",
                partial(_start_fulfillment_resume, sqlite_client),
            ),
            StorefrontStartupStep("preflight_provisioning", _preflight_provisioning),
            StorefrontStartupStep(
                "load_site_projections",
                partial(_load_site_projections, sqlite_client),
                error_message="[STARTUP] Site projection load failed: %s",
            ),
            StorefrontStartupStep(
                "site_projection_poller",
                partial(_start_site_projection_poller, sqlite_client),
            ),
            StorefrontStartupStep(
                "capacity_events_poller",
                partial(_start_capacity_events_poller, sqlite_client),
            ),
        ),
        logger=logger,
    )
