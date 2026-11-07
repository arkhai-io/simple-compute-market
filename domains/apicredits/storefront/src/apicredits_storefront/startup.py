"""Storefront startup hooks: the thread store, the escrow backfill, and the loops."""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.escrow_identity import backfill_escrow_obligation_records
from market_core import MarketDomainContract

from apicredits_storefront.lifecycle_steps import register_api_credit_loops
from apicredits_storefront.utils.config import BASE_URL_OVERRIDE, settings

logging.basicConfig(
    level=getattr(logging, str(settings.get("log_level", "INFO")).upper(), logging.INFO)
)

logger = logging.getLogger(__name__)


async def _startup_tasks(
    *, domain: MarketDomainContract, capacity_runtime: Any | None = None
) -> None:
    """Initialize background tasks for the exact app-selected domain.

    ``capacity_runtime`` is the runtime the capacity-event pollers drain, the
    one the storefront's configuration composes unless given.
    """
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    import apicredits_storefront.container as _container

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

    loops = _container.resolved_loop_controller
    if loops is None:
        raise RuntimeError("loop controller is not initialized")

    settlement_runtime = _container.resolved_settlement_runtime
    marketplace_signer = _container.resolved_marketplace_signer
    if settlement_runtime is not None and marketplace_signer is not None:
        backfilled = await backfill_escrow_obligation_records(
            sqlite_client=_container.resolved_sqlite_client,
            settlement_runtime=settlement_runtime,
            local_principal=marketplace_signer.identity,
        )
        if backfilled:
            logger.info(
                "[STARTUP] Backfilled %d legacy escrow obligation records",
                backfilled,
            )

    if _container.resolved_settlement_worker is None:
        raise RuntimeError("settlement servicing worker is not initialized")

    # Every loop starts here, after the escrow backfill the servicing sweep
    # depends on: each sweep's timer, the chain probe and the listing seed while
    # composed, and the capacity-event pollers' fan-out, which `start_loops`
    # starts together. Nothing waits for the credits service to answer: the
    # configured seed listing is created by its loop's step, never here, and
    # waits while the service or a mechanism it uses cannot be reached.
    intervals = register_api_credit_loops(loops, capacity_runtime=capacity_runtime)
    loops.start_loops(task_logger=logger)
    for name, interval in intervals.items():
        logger.info("[STARTUP] %s loop started (interval=%ss)", name, interval)
