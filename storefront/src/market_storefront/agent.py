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

Module-level state (`_AGENT_IDS`, `agent_card_data`, `ALERTS_USER_ID`) and
the `_startup_tasks` coroutine are imported by `server.py` (lifespan) and
`identity_controller.py`.

Per-chain identity: each `[chains.<name>]` table gets its own on-chain
identity. `_AGENT_IDS[chain_name]` carries the numeric agent ID for that
chain. Populated in parallel at startup; freshly registered IDs get
written back to TOML so the next boot is a no-op.
"""

import asyncio
import logging
from typing import Any

from service.config_loader import (
    ChainConfig,
    set_dotted,
    storefront_config_file,
    load_storefront_config,
    write_user_config,
)

from market_storefront.utils.config import (
    CHAINS,
    settings,
    AGENT_NAME,
    BASE_URL_OVERRIDE,
)
from market_storefront.utils.logging_config import setup_file_logging

setup_file_logging(settings.log_file_path or None, settings.log_level)

logger = logging.getLogger(__name__)

ALERTS_USER_ID = "resource-monitor"

# Build the agent card once at import — identity_controller reads this.
from market_storefront.utils.agent_card import build_agent_card_data
agent_card_data = build_agent_card_data(
    agent_name=AGENT_NAME,
    base_url=BASE_URL_OVERRIDE,
    agent_wallet_address=settings.wallet.address,
)


# Runtime agent identities — one entry per chain that successfully resolved
# its on-chain ID during startup. Keyed by chain name (matches CHAINS).
_AGENT_IDS: dict[str, int] = {}


def _persist_agent_id(chain_name: str, agent_id: int) -> None:
    """Write a freshly-resolved agent_id back to ``storefront.toml``.

    Race-safe in practice: two storefront processes racing to register
    the same wallet on the same chain converge to the same ID, so a
    last-write-wins on the TOML file produces the correct value either
    way. Failures are logged but don't fail the boot — the in-memory
    ID still works for this process; the next boot will just re-discover.
    """
    try:
        doc = load_storefront_config()
        set_dotted(doc, f"chains.{chain_name}.onchain_agent_id", agent_id)
        write_user_config(doc, path=storefront_config_file())
        logger.info(
            "[IDENTITY] Persisted onchain_agent_id=%d for chain %s in %s",
            agent_id, chain_name, storefront_config_file(),
        )
    except Exception as exc:
        logger.warning(
            "[IDENTITY] Could not persist onchain_agent_id=%d for chain %s: %s",
            agent_id, chain_name, exc,
        )


def _build_w3_for_chain(chain: ChainConfig):
    """Construct a web3 HTTPProvider client for one-shot RPC calls.

    Translates ws/wss URLs to http(s) — websocket transport is only
    useful for event subscriptions, and the only RPCs we need here
    (ownerOf, eth_call) work identically over HTTP.
    """
    from web3 import Web3
    from web3.providers import HTTPProvider
    rpc = chain.rpc_url
    if rpc.startswith("ws://"):
        rpc = rpc.replace("ws://", "http://", 1)
    elif rpc.startswith("wss://"):
        rpc = rpc.replace("wss://", "https://", 1)
    return Web3(HTTPProvider(rpc, request_kwargs={"timeout": 5}))


async def _ensure_agent_identity_for_chain(chain: ChainConfig) -> int | None:
    """Resolve the agent ID for a single chain. Stores in ``_AGENT_IDS``.

    Resolution order:
      1. ``chain.onchain_agent_id`` pinned in config — validate ownership
         on-chain when possible, otherwise trust the pin.
      2. Lookup-by-owner on the identity registry — picks up an agent
         the operator registered previously (or in a parallel session)
         without re-minting. Auto-persists the discovered ID.
      3. Fresh on-chain registration when ``settings.auto_register`` is
         true. Auto-persists the new ID.

    Returns the resolved ID (also stored in ``_AGENT_IDS[chain.name]``),
    or ``None`` if no ID could be resolved and ``auto_register`` is off
    (skip rather than crash so other chains can still come up).
    """
    if not chain.identity_registry_address or not settings.wallet.address:
        logger.warning(
            "[IDENTITY] Skipping chain %s: missing identity_registry_address "
            "or wallet.address.", chain.name,
        )
        return None

    if chain.onchain_agent_id:
        agent_id = int(chain.onchain_agent_id)
        # Verify ownership when the chain is reachable; tolerate failures
        # since this is just a sanity check (the operator may have a
        # ZeroTier RPC that comes up later).
        try:
            from service.clients.erc8004.blockchain import get_identity_registry_contract
            w3 = _build_w3_for_chain(chain)
            contract = get_identity_registry_contract(w3, chain.identity_registry_address)
            owner = contract.functions.ownerOf(agent_id).call()
            expected = settings.wallet.address
            if owner.lower() != expected.lower():
                raise RuntimeError(
                    f"[IDENTITY] chain={chain.name} pinned onchain_agent_id={agent_id} "
                    f"is owned by {owner} on-chain, but wallet.address is {expected}. "
                    "These must match. Fix the pin or the wallet address."
                )
            logger.info(
                "[IDENTITY] chain=%s ownership confirmed: agent %d owned by %s",
                chain.name, agent_id, owner,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(
                "[IDENTITY] chain=%s could not verify ownership of agent %d: %s. "
                "Proceeding with pinned ID.",
                chain.name, agent_id, exc,
            )
        _AGENT_IDS[chain.name] = agent_id
        return agent_id

    # No pin — look up by owner first, then fall back to fresh registration.
    try:
        from service.clients.erc8004.blockchain import (
            find_agent_id_by_owner,
            get_identity_registry_contract,
        )
        w3 = _build_w3_for_chain(chain)
        contract = get_identity_registry_contract(w3, chain.identity_registry_address)
        existing = find_agent_id_by_owner(w3, contract, settings.wallet.address)
    except Exception as exc:
        logger.warning(
            "[IDENTITY] chain=%s wallet-lookup failed (%s) — falling through to "
            "fresh registration.", chain.name, exc,
        )
        existing = None

    if existing is not None:
        _AGENT_IDS[chain.name] = int(existing)
        logger.info(
            "[IDENTITY] chain=%s found existing agent %d owned by %s — skipping "
            "registration.", chain.name, existing, settings.wallet.address,
        )
        _persist_agent_id(chain.name, int(existing))
        return int(existing)

    if not settings.auto_register:
        logger.error(
            "[IDENTITY] chain=%s has no pinned onchain_agent_id and auto_register "
            "is false. Skipping. Pin [chains.%s].onchain_agent_id or enable "
            "seller.auto_register.", chain.name, chain.name,
        )
        return None

    logger.info("[IDENTITY] chain=%s performing on-chain registration.", chain.name)
    from market_storefront.commands.register import perform_registration_for_chain
    agent_id = await perform_registration_for_chain(chain)
    _AGENT_IDS[chain.name] = agent_id
    logger.info("[IDENTITY] chain=%s registered with agent ID %d", chain.name, agent_id)
    _persist_agent_id(chain.name, agent_id)
    return agent_id


async def _ensure_all_agent_identities() -> None:
    """Spawn per-chain identity tasks in parallel; gather them.

    Per-chain failures are non-fatal so a single misconfigured chain
    doesn't take down the whole storefront — but a `RuntimeError` from
    the ownership-mismatch check **does** propagate, because that
    indicates a config bug the operator must fix.
    """
    if not CHAINS:
        logger.warning(
            "[IDENTITY] No [chains.<name>] tables configured — skipping identity "
            "resolution. Storefront will fail when it tries to dispatch on-chain "
            "actions.",
        )
        return
    tasks = [
        asyncio.create_task(_ensure_agent_identity_for_chain(c), name=f"identity:{c.name}")
        for c in CHAINS.values()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for chain_name, result in zip(CHAINS.keys(), results):
        if isinstance(result, RuntimeError):
            # Ownership mismatch — operator must fix. Propagate.
            raise result
        if isinstance(result, Exception):
            logger.error(
                "[IDENTITY] chain=%s identity resolution failed: %s",
                chain_name, result,
            )


async def _start_heartbeats() -> None:
    """Start one heartbeat task per chain that has a resolved agent ID.

    Each call to ``start_agent_heartbeat`` itself fans out across every
    configured registry URL — so the total task fan-out is
    (chains × registries). Each task is independent; a slow registry
    or unreachable chain doesn't block the others.
    """
    from service.clients.erc8004.heartbeat import start_agent_heartbeat

    auth_section = getattr(settings.registry, "auth", None)
    try:
        indexer_auth = dict(auth_section) if auth_section else {}
    except (TypeError, ValueError):
        indexer_auth = {}

    for chain in CHAINS.values():
        agent_id = _AGENT_IDS.get(chain.name)
        if agent_id is None:
            logger.debug(
                "[HEARTBEAT] chain=%s no agent ID resolved — skipping heartbeat.",
                chain.name,
            )
            continue
        if not chain.identity_registry_address:
            continue
        await start_agent_heartbeat({
            "indexer_urls": settings.registry.urls,
            "identity_registry_address": chain.identity_registry_address,
            "agent_wallet_address": settings.wallet.address,
            "onchain_agent_id": str(agent_id),
            "chain_rpc_url": chain.rpc_url,
            "agent_priv_key": settings.wallet.private_key,
            "indexer_auth": indexer_auth,
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


async def _probe_chain_addresses() -> None:
    """For each configured chain, eth_getCode-check the contract addresses.

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
        if chain.identity_registry_address:
            addresses[f"{chain.name}/identity_registry"] = chain.identity_registry_address
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

    # Resolve agent identities for every configured chain. Each chain is
    # an independent task so they run in parallel; an unreachable RPC on
    # one chain doesn't gate the others.
    await _ensure_all_agent_identities()

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

    # Probe each chain's configured contract addresses for bytecode.
    await _probe_chain_addresses()

    # Start heartbeats — one per (chain, registry) pair, fired off as
    # background tasks. Doesn't await individual heartbeat loops.
    asyncio.create_task(_start_heartbeats())

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
