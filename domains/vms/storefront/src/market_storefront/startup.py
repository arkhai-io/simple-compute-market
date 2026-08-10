"""Storefront startup hooks.

After the pluggable-identity refactor (Phase 4) the storefront's identity is
just ``settings.wallet.address``. There is no per-chain on-chain registration
step, no agent-card publication, and no heartbeat loop.
"""

import asyncio
import logging

from core_storefront.app_startup import (
    StorefrontBackgroundTask,
    StorefrontStartupStep,
    run_storefront_startup_steps,
    start_storefront_background_task,
)

from market_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    CHAINS,
    settings,
)
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(settings.log_file_path or None, settings.log_level)

logger = logging.getLogger(__name__)


async def _probe_chain_addresses() -> None:
    """For each configured chain, eth_getCode-check the alkahest addresses."""
    if not CHAINS:
        return
    from market_alkahest.alkahest import resolve_alkahest_address_config
    from market_alkahest.chain_probe import probe_addresses

    for chain in CHAINS.values():
        addresses: dict[str, str] = {}
        try:
            cfg = resolve_alkahest_address_config(
                chain.name,
                config_path=chain.alkahest_address_config_path,
            )
        except Exception as exc:
            logger.warning(
                "[STARTUP] chain=%s could not resolve alkahest config: %s",
                chain.name,
                exc,
            )
            cfg = None
        if cfg is not None:
            for path, label in (
                (
                    ("arbiters_addresses", "recipient_arbiter"),
                    f"{chain.name}/alkahest.recipient_arbiter",
                ),
                (("arbiters_addresses", "eas"), f"{chain.name}/alkahest.eas"),
                (
                    ("erc20_addresses", "escrow_obligation_default"),
                    f"{chain.name}/alkahest.erc20_escrow_obligation",
                ),
            ):
                obj: object | None = cfg
                for attr in path:
                    obj = getattr(obj, attr, None)
                    if obj is None:
                        break
                if isinstance(obj, str) and obj.strip():
                    addresses[label] = obj
        if not addresses:
            continue
        await probe_addresses(chain.rpc_url, addresses)


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


def _start_negotiation_watchdog() -> None:
    from market_storefront.negotiation_watchdog import (
        watchdog_loop as _neg_watchdog_loop,
    )

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="negotiation_watchdog",
            task_factory=_neg_watchdog_loop,
            log_message=(
                "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)"
            ),
            log_args=(
                settings.negotiation_watchdog_interval,
                settings.negotiation_timeout_seconds,
            ),
        ),
        logger=logger,
    )


def _start_claims_engine() -> None:
    from market_storefront.services.claims_runtime import claims_engine_loop

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="claims_engine",
            task_factory=claims_engine_loop,
            log_message="[STARTUP] Claims engine started (interval=%ss)",
            log_args=(getattr(settings, "claims_sweep_interval", 30),),
        ),
        logger=logger,
    )


def _start_fulfillment_resume() -> None:
    from market_storefront.services.fulfillment_resume_runtime import (
        fulfillment_resume_loop,
    )

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="fulfillment_resume",
            task_factory=fulfillment_resume_loop,
            log_message="[STARTUP] Fulfillment resume worker started (interval=%ss)",
            log_args=(getattr(settings, "fulfillment_resume_sweep_interval", 30),),
        ),
        logger=logger,
    )


def _start_capacity_events_poller() -> None:
    # Tail every authority's capacity-event feed after provisioning preflight.
    from market_storefront.services.capacity_client import capacity_events_poller_loop

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="capacity_events_poller",
            task_factory=capacity_events_poller_loop,
        ),
        logger=logger,
    )


async def _load_site_projections() -> None:
    from market_storefront.services.site_projection_cache import load_site_projections

    await load_site_projections()


def _start_site_projection_poller() -> None:
    from market_storefront.services.site_projection_cache import (
        site_projection_poller_loop,
    )

    start_storefront_background_task(
        StorefrontBackgroundTask(
            name="site_projection_poller",
            task_factory=site_projection_poller_loop,
        ),
        logger=logger,
    )


async def _startup_tasks() -> None:
    """Initialize background tasks. Called from server.py lifespan."""
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
            StorefrontStartupStep("probe_chain_addresses", _probe_chain_addresses),
            StorefrontStartupStep(
                "negotiation_watchdog",
                _start_negotiation_watchdog,
            ),
            StorefrontStartupStep("claims_engine", _start_claims_engine),
            StorefrontStartupStep("fulfillment_resume", _start_fulfillment_resume),
            StorefrontStartupStep("preflight_provisioning", _preflight_provisioning),
            StorefrontStartupStep(
                "load_site_projections",
                _load_site_projections,
                error_message="[STARTUP] Site projection load failed: %s",
            ),
            StorefrontStartupStep(
                "site_projection_poller",
                _start_site_projection_poller,
            ),
            StorefrontStartupStep(
                "capacity_events_poller",
                _start_capacity_events_poller,
            ),
        ),
        logger=logger,
    )
