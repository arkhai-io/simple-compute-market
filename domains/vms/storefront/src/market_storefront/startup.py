"""Storefront startup hooks.

After the pluggable-identity refactor (Phase 4) the storefront's identity is
just ``settings.wallet.address``. There is no per-chain on-chain registration
step, no agent-card publication, and no heartbeat loop.
"""

import logging
from functools import partial

from market_storefront.services.listing_identity_carryover import carry_over_seller_state
from market_storefront.services.publication_terms import (
    configured_family_rate_problems,
    retired_pricing_configuration_keys,
)
from market_storefront.lifecycle import start_loops
from market_storefront.lifecycle_steps import register_vm_loops
from typing import Any

from core_storefront.app_startup import (
    StorefrontStartupStep,
    run_storefront_startup_steps,
)
from market_core import MarketDomainContract

import market_storefront.container as _container
from market_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    introduction_retention_sweep_interval,
    settings,
    site_projection_poll_interval,
    source_confirmation_seconds,
)
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(settings.log_file_path or None, settings.log_level)

logger = logging.getLogger(__name__)


def _require_readable_family_rates() -> None:
    """Refuse to start with a configured family rate that cannot be read.

    The configured defaults are the operator's own file: a rate in it that cannot
    be read is a configuration error, not a pool to hold, and starting anyway
    would hold every pool that falls through to it.
    """
    problems = configured_family_rate_problems()
    if problems:
        raise RuntimeError(
            "configured family rates cannot be read: " + "; ".join(problems)
        )


def _require_source_confirmation_window() -> None:
    """Refuse to start, naming the key, with a projection poll interval or a
    source-confirmation window that is not a positive, finite number of seconds
    that can be applied to an instant without leaving `datetime`'s range, rather
    than start loops on it or refuse every negotiation round.

    The poll interval is checked first: when the window is not stated it is
    derived from it.
    """
    site_projection_poll_interval()
    source_confirmation_seconds()


def _report_retired_pricing_keys() -> None:
    """Name pricing keys the configuration states that nothing reads any more.

    They are accepted rather than refused, so an upgraded storefront starts with
    its existing configuration; this is where an operator learns to remove them.
    """
    retired = retired_pricing_configuration_keys()
    if retired:
        logger.warning(
            "[STARTUP] Configuration states retired pricing keys that are not "
            "read: %s",
            ", ".join(retired),
        )


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


async def _load_site_projections() -> None:
    """The first load: one cycle of the poller, before its timer starts."""
    await _container.site_projections().poll_once()


def _start_lifecycle_loops() -> None:
    """Register every loop under the running configuration and start them all.

    After the first projection load, so neither the poller nor publication
    runs its first cycle over projections nothing has loaded, and after
    settlement preflight and the escrow backfill the servicing sweep depends
    on. Nothing waits for a dependency to answer: a site, registry, or chain
    that cannot be reached is reported in system status and retried by the
    loop that calls it. Introduction retention runs only while contact
    exchange is composed.
    """
    composition = _container.resolved_contact_exchange
    retention = composition.retention() if composition is not None else None
    probe = _container.resolved_alkahest_chain_probe
    intervals = register_vm_loops(
        retention_interval_seconds=(
            introduction_retention_sweep_interval(retention.policy.sweep_interval_seconds)
            if retention is not None
            else None
        ),
        alkahest_probe_interval_seconds=(
            probe.interval_seconds if probe is not None else None
        ),
    )
    for name in start_loops():
        logger.info("[STARTUP] %s started (interval=%ss)", name, intervals.get(name))


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
                "configured_family_rates",
                _require_readable_family_rates,
            ),
            StorefrontStartupStep(
                "source_confirmation_window",
                _require_source_confirmation_window,
            ),
            StorefrontStartupStep(
                "retired_pricing_keys",
                _report_retired_pricing_keys,
                continue_on_error=True,
            ),
            StorefrontStartupStep(
                "negotiation_thread_store",
                _initialize_negotiation_thread_store,
            ),
            # Before any lifecycle loop: the first publication cycle would
            # otherwise publish a pre-shape listing's successor without the
            # seller's close or pause. Fail-fast, for the same reason.
            StorefrontStartupStep(
                "listing_identity_carryover",
                partial(carry_over_seller_state, sqlite_client),
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
            StorefrontStartupStep(
                "load_site_projections",
                _load_site_projections,
                error_message="[STARTUP] Site projection load failed: %s",
            ),
            StorefrontStartupStep("lifecycle_loops", _start_lifecycle_loops),
        ),
        logger=logger,
    )
