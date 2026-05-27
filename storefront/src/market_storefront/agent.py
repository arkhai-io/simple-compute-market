"""Storefront startup hooks.

After the pluggable-identity refactor (Phase 4) the storefront's
identity is just ``settings.wallet.address`` — there is no per-chain
on-chain registration step, no agent-card publication, and no
heartbeat loop. ``_startup_tasks`` is what ``server.py``'s lifespan
imports.
"""

import asyncio
import logging

from market_storefront.utils.config import (
    CHAINS,
    settings,
    BASE_URL_OVERRIDE,
)
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(settings.log_file_path or None, settings.log_level)

logger = logging.getLogger(__name__)

ALERTS_USER_ID = "resource-monitor"


async def _probe_chain_addresses() -> None:
    """For each configured chain, eth_getCode-check the alkahest addresses.

    Catches operator typos and wrong-chain configs. Warns rather than
    fails so other endpoints stay available while the operator fixes
    the misconfig.
    """
    if not CHAINS:
        return
    from service.clients.alkahest import resolve_alkahest_address_config
    from service.clients.chain_probe import probe_addresses

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
                chain.name, exc,
            )
            cfg = None
        if cfg is not None:
            for path, label in (
                (("arbiters_addresses", "recipient_arbiter"), f"{chain.name}/alkahest.recipient_arbiter"),
                (("arbiters_addresses", "eas"), f"{chain.name}/alkahest.eas"),
                (("erc20_addresses", "escrow_obligation_nontierable"),
                 f"{chain.name}/alkahest.erc20_escrow_obligation"),
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
    """Block startup until the provisioning service responds, or give up.

    Polls ``provisioning_service_url/health`` until it returns 200 or the
    configured ``preflight_timeout`` elapses. On timeout:
      * ``fail_on_unreachable=True`` (default): raise ``RuntimeError``,
        which propagates out of ``_startup_tasks`` and crashes the
        process. An orchestrator restart loop surfaces the misconfig
        immediately rather than letting it hide in logs until the first
        settle attempt fails.
      * ``fail_on_unreachable=False``: log loud and return — useful for
        dev where the service comes up later in the same pod.

    The hint about ``ACTIVE_PROFILES=mock`` is preserved in the error
    message because that's the most common e2e setup.
    """
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
                    settings.provisioning.service_url, attempt,
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
    """If a ZeroTier network is configured, ask the local zerotier-one
    daemon to join it. The daemon itself is brought up by the deploy
    layer (compose entrypoint, helm initContainer, or systemd unit) —
    we don't manage its lifecycle here, just talk to its CLI socket.

    Errors are logged and swallowed: a misconfigured ZeroTier setup
    should not block the agent from serving on its host network.
    """
    network = settings.zerotier_network
    if not network:
        return
    import subprocess
    try:
        subprocess.run(
            ["sudo", "zerotier-cli", "join", network],
            check=True, capture_output=True, text=True, timeout=10,
        )
        logger.info("[STARTUP] Joined ZeroTier network %s", network)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "[STARTUP] ZeroTier join failed for network=%s: %s. "
            "The agent will continue serving on its host network.",
            network, exc,
        )


async def _startup_tasks():
    """Initialize background tasks. Called from server.py lifespan."""
    from market_storefront.negotiation_watchdog import watchdog_loop as _neg_watchdog_loop

    _maybe_join_zerotier_network()

    # Initialize the global NegotiationThreadStore so any subsequent
    # request handler can call NegotiationThreadTransaction (which
    # reaches into get_thread_store() with no args). Must run before
    # any request can hit /api/v1/negotiate/*.
    import market_storefront.container as _container
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store
    _agent_url = BASE_URL_OVERRIDE or f"http://localhost:{settings.port}"
    get_thread_store(
        sqlite_client=_container.resolved_sqlite_client,
        identity=Identity(agent_url=_agent_url),
    )
    logger.info("[STARTUP] Negotiation thread store initialized (agent_url=%s)", _agent_url)

    # Seed the resources table on startup if it is empty. Source priority:
    # inline CSV content (Helm Secret injection) > explicit resources_csv_path
    # > auto-discovery of /app/resources.csv (compose bind-mount default).
    # Must run before the resource poller so the poller has rows to query.
    try:
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
            logger.info("[STARTUP] No resource source configured — starting with empty inventory")
        else:
            logger.info(
                "[STARTUP] Resource seeding skipped — %d resource(s) already present",
                result["imported_count"],
            )
    except Exception as exc:
        logger.error("[STARTUP] Resource seeding failed: %s", exc)
        raise

    # Probe each chain's configured alkahest addresses for bytecode.
    await _probe_chain_addresses()

    # Start negotiation watchdog (marks stale threads as abandoned)
    asyncio.create_task(_neg_watchdog_loop())
    logger.info(
        "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)",
        settings.negotiation_watchdog_interval,
        settings.negotiation_timeout_seconds,
    )

    # Preflight: block startup until the provisioning service is reachable.
    # Crashes the process on timeout if [seller.provisioning].fail_on_unreachable
    # is true (default), so the misconfig surfaces immediately rather than
    # going silent until the first settle attempt fails.
    await _preflight_provisioning()
