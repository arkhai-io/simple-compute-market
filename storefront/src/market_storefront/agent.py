# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Storefront startup/background-task helpers.

Module-level state (`_AGENT_ID`, `agent_card_data`, `ALERTS_USER_ID`) and
the `_startup_tasks` coroutine are imported by `server.py` (lifespan) and
`identity_controller.py`.

The legacy `TraderAgent` class, the `_RootAgentShim`, the queue/Redis
event-ingestion pipeline, and `_parse_domain_event` were removed in the
event-system prune — none of them were reachable under the default config
and the `_RootAgentShim` was forwarding to a non-existent
`StorefrontService.process_event_with_pipeline`. Live event flows go
through `services/policy_service.py` directly.
"""

import asyncio
import logging

from market_storefront.utils.config import CONFIG
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(CONFIG.log_file_path, CONFIG.log_level)

logger = logging.getLogger(__name__)

ALKAHEST_NETWORK = None  # populated lazily; agent_card_data does not need it

ALERTS_USER_ID = "resource-monitor"

# Build the agent card once at import — identity_controller reads this.
from market_storefront.utils.agent_card import build_agent_card_data
agent_card_data = build_agent_card_data(
    agent_name=CONFIG.agent_name,
    base_url=CONFIG.base_url_override,
    agent_wallet_address=CONFIG.agent_wallet_address,
)


# Runtime agent identity — set once by _ensure_agent_identity() during startup.
_AGENT_ID: int | None = None


async def _ensure_agent_identity() -> int:
    """Resolve the numeric on-chain agent ID, registering if necessary.

    Resolution order:
      1. CONFIG.onchain_agent_id (pinned in TOML / helm values) — fast path,
         no chain interaction.
      2. auto_register=True → call perform_registration() and hold the result
         in memory for this process lifetime.
      3. auto_register=False and no ID pinned → crash with a clear message.
         This protects operators who have already registered an agent and
         don't want a misconfigured deploy to silently mint a new one.

    Sets the module-level _AGENT_ID and returns it.
    """
    global _AGENT_ID

    if CONFIG.onchain_agent_id:
        try:
            _AGENT_ID = int(CONFIG.onchain_agent_id)
            logger.info(
                "[IDENTITY] Using pinned agent ID %d from config", _AGENT_ID
            )
        except ValueError:
            raise RuntimeError(
                f"[IDENTITY] seller.onchain_agent_id '{CONFIG.onchain_agent_id}' "
                "is not a valid integer."
            )

        # Validate that this wallet actually owns the pinned ID on-chain.
        # Skipped when chain config is absent (local dev without a node).
        if CONFIG.chain_rpc_url and CONFIG.identity_registry_address and CONFIG.agent_wallet_address:
            try:
                from service.clients.erc8004.blockchain import (
                    get_identity_registry_contract,
                )
                from web3 import Web3
                from web3.providers import HTTPProvider

                rpc = CONFIG.chain_rpc_url
                if rpc.startswith("ws"):
                    # Use HTTP fallback for the ownership check — websocket is
                    # only needed for event subscriptions, not one-shot calls.
                    rpc_http = rpc.replace("ws://", "http://").replace("wss://", "https://")
                    w3 = Web3(HTTPProvider(rpc_http, request_kwargs={"timeout": 5}))
                else:
                    w3 = Web3(HTTPProvider(rpc, request_kwargs={"timeout": 5}))

                contract = get_identity_registry_contract(w3, CONFIG.identity_registry_address)
                owner = contract.functions.ownerOf(_AGENT_ID).call()
                expected = CONFIG.agent_wallet_address

                if owner.lower() != expected.lower():
                    raise RuntimeError(
                        f"[IDENTITY] Pinned onchain_agent_id={_AGENT_ID} is owned by "
                        f"{owner} on-chain, but [seller].wallet_address in config is "
                        f"{expected}. These must match.\n"
                        "Fix: either update [seller].onchain_agent_id to the correct "
                        "agent ID for this wallet, or correct [seller].wallet_address."
                    )
                logger.info(
                    "[IDENTITY] Ownership confirmed: agent %d owned by %s",
                    _AGENT_ID, owner,
                )
            except RuntimeError:
                raise
            except Exception as exc:
                # Chain unreachable / contract not deployed — log but don't block
                # startup.  This matches the existing behaviour for ZeroTier
                # environments where the chain may not be reachable until the
                # ZeroTier IP is assigned.
                logger.warning(
                    "[IDENTITY] Could not verify ownership of agent %d on-chain: %s. "
                    "Proceeding with pinned ID.",
                    _AGENT_ID, exc,
                )

        return _AGENT_ID

    if not CONFIG.auto_register:
        raise RuntimeError(
            "[IDENTITY] seller.onchain_agent_id is not set and "
            "seller.auto_register is false. "
            "Either pin [seller].onchain_agent_id in config.toml / helm values, "
            "or set seller.auto_register = true to allow automatic registration."
        )

    logger.info("[IDENTITY] No agent ID pinned — performing on-chain registration.")
    from market_storefront.commands.register import perform_registration
    _AGENT_ID = await perform_registration(chain_id=CONFIG.chain_id)
    logger.info("[IDENTITY] Registered with agent ID %d", _AGENT_ID)
    return _AGENT_ID


async def _start_heartbeat():
    """Start heartbeat loop after server is ready."""
    from service.clients.erc8004.heartbeat import start_agent_heartbeat
    await start_agent_heartbeat({
        "indexer_url": CONFIG.indexer_url,
        "identity_registry_address": CONFIG.identity_registry_address,
        "agent_wallet_address": CONFIG.agent_wallet_address,
        "onchain_agent_id": str(_AGENT_ID) if _AGENT_ID is not None else None,
        "chain_rpc_url": CONFIG.chain_rpc_url,
        "agent_priv_key": CONFIG.agent_priv_key,
    })


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

    url = CONFIG.provisioning_service_url.rstrip("/") + "/health"
    timeout_s = max(int(CONFIG.provisioning_preflight_timeout), 1)
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
                    CONFIG.provisioning_service_url, attempt,
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
        f"[STARTUP] Provisioning service at {CONFIG.provisioning_service_url} "
        f"unreachable after {timeout_s}s ({last_error}). "
        "For e2e tests without hardware, set ACTIVE_PROFILES=mock on the "
        "provisioning-service container."
    )
    if CONFIG.provisioning_fail_on_unreachable:
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
    network = CONFIG.zerotier_network
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
    from market_storefront.resource_poller import resource_poller_loop
    from market_storefront.negotiation_watchdog import watchdog_loop as _neg_watchdog_loop

    _maybe_join_zerotier_network()

    # Resolve agent identity first — everything else (heartbeat, registration
    # file endpoint) depends on having a valid numeric agent ID.
    # Raises RuntimeError on hard failure (missing config + auto_register=False),
    # which crashes the startup and surfaces as a clear pod CrashLoopBackOff.
    await _ensure_agent_identity()

    # Start heartbeat after server is ready
    asyncio.create_task(_start_heartbeat())

    # Start resource availability poller
    asyncio.create_task(resource_poller_loop())
    logger.info("[STARTUP] Resource poller started (interval=%ds)",
            CONFIG.resource_check_interval)

    # Start negotiation watchdog (marks stale threads as abandoned)
    asyncio.create_task(_neg_watchdog_loop())
    logger.info(
        "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)",
        CONFIG.negotiation_watchdog_interval,
        CONFIG.negotiation_timeout_seconds,
    )

    # Preflight: block startup until the provisioning service is reachable.
    # Crashes the process on timeout if [seller.provisioning].fail_on_unreachable
    # is true (default), so the misconfig surfaces immediately rather than
    # going silent until the first settle attempt fails.
    await _preflight_provisioning()
