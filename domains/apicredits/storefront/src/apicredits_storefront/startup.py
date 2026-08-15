"""Storefront startup hooks: preflight + background tasks."""

from __future__ import annotations

import asyncio
import logging

from apicredits_storefront.utils import config
from apicredits_storefront.utils.config import BASE_URL_OVERRIDE, settings
from core_storefront.stage_log import stage_event
from market_core import MarketDomainContract
from market_storefront_kit import (
    NegotiationWatchdogPolicy,
    run_negotiation_watchdog,
)

logging.basicConfig(
    level=getattr(logging, str(settings.get("log_level", "INFO")).upper(), logging.INFO)
)

logger = logging.getLogger(__name__)


async def _preflight_credits_service() -> None:
    """Block startup until the credits service responds, or give up."""
    import httpx

    url = config.credits_service_url()
    if not url:
        raise RuntimeError(
            "[STARTUP] [credits].service_url is not configured — the "
            "storefront has nothing to sell for."
        )
    health = url + "/health"
    timeout_s = max(int(settings.get("credits.preflight_timeout", 30)), 1)
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_error: str | None = None

    while True:
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.get(health)
            if resp.status_code == 200:
                logger.info("[STARTUP] Credits service reachable at %s", url)
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(2.0, remaining))

    msg = (
        f"[STARTUP] Credits service at {url} unreachable after {timeout_s}s "
        f"({last_error})."
    )
    if settings.get("credits.fail_on_unreachable", True):
        raise RuntimeError(
            msg + " Set [credits].fail_on_unreachable = false to start the "
            "storefront anyway (issuance will fail until it is reachable)."
        )
    logger.error(msg + " Continuing because fail_on_unreachable=false.")


def _negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    return NegotiationWatchdogPolicy(
        timeout_seconds=float(settings.negotiation_timeout_seconds),
        interval_seconds=float(settings.negotiation_watchdog_interval),
        log_loop_start=False,
        log_cutoff=False,
    )


async def _startup_tasks(*, domain: MarketDomainContract) -> None:
    """Initialize background tasks for the exact app-selected domain."""
    import apicredits_storefront.container as _container
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    if _container.resolved_market_domain is not domain:
        raise RuntimeError(
            "API-credit startup is not bound to the app-selected "
            "market-domain contract object"
        )

    storefront_url = BASE_URL_OVERRIDE or f"http://localhost:{settings.port}"
    get_thread_store(
        sqlite_client=_container.resolved_sqlite_client,
        identity=Identity(agent_url=storefront_url),
    )
    logger.info(
        "[STARTUP] Negotiation thread store initialized (storefront_url=%s)",
        storefront_url,
    )

    watchdog_policy = _negotiation_watchdog_policy()
    asyncio.create_task(
        run_negotiation_watchdog(
            _container.resolved_sqlite_client,
            watchdog_policy,
            emit_stage_event=stage_event,
            logger=logger,
        )
    )
    logger.info(
        "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)",
        watchdog_policy.interval_seconds,
        watchdog_policy.timeout_seconds,
    )

    settlement_worker = _container.resolved_settlement_worker
    if settlement_worker is None:
        raise RuntimeError("settlement servicing worker is not initialized")
    asyncio.create_task(settlement_worker.run())
    logger.info(
        "[STARTUP] Settlement servicing worker started (interval=%ss)",
        settings.get("claims_sweep_interval", 30),
    )

    await _preflight_credits_service()

    await _seed_demo_listing()

    from apicredits_storefront.services.capacity_client import (
        capacity_events_poller_loop,
    )

    asyncio.create_task(capacity_events_poller_loop())
    logger.info("[STARTUP] Quota capacity event poller started")


def _capacity_authority_site():
    """Resolve the explicitly pinned site used for demo quota registration."""
    from apicredits_storefront.services.capacity_client import _capacity_settings

    sites, _ = _capacity_settings()
    selected = str(settings.get("capacity.seed_site", "") or "")
    if selected:
        try:
            return sites[selected]
        except KeyError as exc:
            raise RuntimeError(f"unknown capacity.seed_site {selected!r}") from exc
    if len(sites) != 1:
        raise RuntimeError("capacity.seed_site is required with multiple sites")
    return next(iter(sites.values()))


async def _register_seed_quota(*, resource_id: str, total_units: int) -> None:
    """Register the demo quota resource in the credits-service ledger.

    The ledger is the credits service's; the storefront is a client, so
    registration goes through the typed capacity-administration client
    (``SiteCapacityClient`` only reads/commits, never registers). A
    re-registration on restart re-asserts the resource.
    """
    from market_site_client import SiteCapacityAdminClient, SiteCapacityAdminClientError

    import apicredits_storefront.container as container

    site = _capacity_authority_site()
    signer = container.resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("marketplace signer is unavailable for quota registration")
    admin_client = SiteCapacityAdminClient(
        site.url,
        signer=signer,
        expected_authorities=site.expected_authorities,
        timeout=30.0,
        transport=None,
        max_timestamp_skew=300,
    )
    try:
        await admin_client.register_resource(
            resource_id,
            total_units=total_units,
            resource_type="api_credits",
        )
    except SiteCapacityAdminClientError as exc:
        raise RuntimeError(
            f"quota registration for {resource_id!r} at {site.url!r} failed: {exc}"
        ) from exc
    logger.info(
        "[STARTUP] Seeded quota resource %s (total_units=%d) in the ledger",
        resource_id,
        total_units,
    )


async def _seed_demo_listing() -> None:
    """Self-seed one quota-backed listing from a ``[seed]`` config block.

    Demo/e2e convenience, mirroring the VM storefront's CSV inventory
    seed: with a ``[seed]`` block present, register the quota resource
    and publish a listing from it on startup, so a fresh ``compose up``
    has something to discover without an out-of-band admin step. Omit
    the block in production — operators seed quota and publish via the
    admin API / CLI. Seed failures are logged, not fatal: the storefront
    still serves, and the cause is visible in its logs.
    """
    seed = settings.get("seed")
    if not isinstance(seed, dict) or not seed.get("resource_id"):
        return
    resource_id = str(seed["resource_id"])
    try:
        import apicredits_storefront.container as _container
        from apicredits_storefront.services.listing_service import ListingService
        from apicredits_storefront.utils.config import CHAINS

        db = _container.resolved_sqlite_client
        # Idempotent: skip if a listing already derives from this resource.
        existing = await db.list_listings(status="open", limit=500)
        for row in existing or []:
            offer = row.get("offer_resource") or {}
            if isinstance(offer, str):
                import json as _json

                try:
                    offer = _json.loads(offer)
                except (ValueError, TypeError):
                    offer = {}
            if isinstance(offer, dict) and offer.get("resource_id") == resource_id:
                logger.info(
                    "[STARTUP] Demo listing for resource %s already present; "
                    "skipping seed",
                    resource_id,
                )
                return

        await _register_seed_quota(
            resource_id=resource_id,
            total_units=int(seed.get("total_units", 100)),
        )

        chain = str(seed.get("chain", "anvil"))
        chain_cfg = CHAINS.get(chain)
        if chain_cfg is None:
            raise RuntimeError(f"seed chain {chain!r} is not configured")
        escrow_address = seed.get("escrow_address")
        if not escrow_address:
            from market_alkahest.alkahest import (
                get_erc20_escrow_obligation_default,
            )

            escrow_address = get_erc20_escrow_obligation_default(
                chain,
                config_path=chain_cfg.alkahest_address_config_path,
            )
        price = str(seed.get("price_per_token", "1"))
        accepted_escrows = [
            {
                "chain_name": chain,
                "escrow_address": str(escrow_address).lower(),
                "literal_fields": {"token": str(seed["token"])},
                "rates": [{"field": "amount", "per": "token", "value": price}],
            }
        ]

        from apicredits_storefront.utils.config import resolve_identity_config

        result = await ListingService(
            sqlite_client=db,
            seller_principal=resolve_identity_config().principal,
        ).publish_from_quota(
            resource_id=resource_id,
            service_name=str(seed.get("service_name", "service")),
            accepted_escrows=accepted_escrows,
            description=seed.get("description"),
            openapi_url=seed.get("openapi_url"),
            base_url=seed.get("base_url"),
        )
        logger.info(
            "[STARTUP] Seeded demo listing %s (service=%s, registry=%s)",
            result.get("listing_id"),
            seed.get("service_name"),
            result.get("registry_status"),
        )
    except Exception as exc:  # noqa: BLE001 — seed must not crash the storefront
        logger.error("[STARTUP] Demo listing seed failed: %s", exc, exc_info=True)
