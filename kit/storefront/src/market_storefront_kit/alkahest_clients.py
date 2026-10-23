"""Alkahest client construction from immutable domain-supplied configuration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class LoggerLike(Protocol):
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class AlkahestChain:
    """One configured chain accepted by the reusable client factory."""

    name: str
    rpc_url: str
    address_config_path: str | None = None


@dataclass(frozen=True, slots=True)
class AlkahestClientPolicy:
    """Domain-supplied readiness and chain values for client construction."""

    private_key: str | None
    chains: tuple[AlkahestChain, ...]
    missing_requirements: tuple[str, ...] = ()
    warn_if_no_chains: bool = False


def _load_dependencies() -> tuple[Any, Any, Any, Any]:
    from alkahest_py import AlkahestClient
    from market_alkahest.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )

    return (
        AlkahestClient,
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )


def _missing_requirements(policy: AlkahestClientPolicy) -> tuple[str, ...]:
    missing = tuple(item for item in policy.missing_requirements if item)
    if not policy.private_key and "wallet.private_key" not in missing:
        missing = (*missing, "wallet.private_key")
    return missing


def alkahest_client_constructor(
    policy: AlkahestClientPolicy,
) -> Callable[[str], Any] | None:
    """A constructor of one configured chain's client by name, which raises
    when the client cannot be built.

    ``None`` when the policy is missing a requirement, such as the wallet key,
    since no chain's client could then be built. The SDK builds a client over an HTTP ``rpc_url``
    without contacting the RPC, so an unreachable chain still gets one; over a
    websocket ``rpc_url`` it connects at construction, so construction fails
    until the chain answers, or never returns from an endpoint that accepts the
    connection and never upgrades it. A storefront hands this to the chain
    probe, which constructs each missing client at each probe until it
    succeeds, waiting on it no longer than its RPC timeout.
    """

    if _missing_requirements(policy):
        return None
    chains = {chain.name: chain for chain in policy.chains}

    def construct(chain_name: str) -> Any:
        chain = chains[chain_name]
        (
            client_type,
            get_network,
            prewarm_address_config,
            resolve_address_config,
        ) = _load_dependencies()
        prewarm_address_config(chain.address_config_path)
        address_config = resolve_address_config(
            get_network(chain.name),
            config_path=chain.address_config_path,
        )
        return client_type(
            private_key=policy.private_key,
            rpc_url=chain.rpc_url,
            address_config=address_config,
        )

    return construct


def build_alkahest_clients(
    policy: AlkahestClientPolicy,
    *,
    logger: LoggerLike | None = None,
    constructor: Callable[
        [AlkahestClientPolicy], Callable[[str], Any] | None
    ] = alkahest_client_constructor,
) -> dict[str, Any]:
    """Build every usable configured client and isolate per-chain failures.

    ``constructor`` gives the per-chain construction, the SDK boundary. Each
    client is built on the calling thread with no bound, and a websocket client
    connects while it is built, so a storefront's startup does not call this:
    its chain probe constructs every client, bounded by its RPC timeout.
    """

    active_logger = logger or logging.getLogger(__name__)
    missing = _missing_requirements(policy)
    if missing:
        active_logger.warning(
            "[ALKAHEST] Mechanism unavailable; required EVM settings are missing: %s",
            ", ".join(missing),
        )
        return {}
    if not policy.chains:
        if policy.warn_if_no_chains:
            active_logger.warning(
                "[ALKAHEST] no [chains.<name>] tables configured; nothing to build."
            )
        return {}

    construct = constructor(policy)
    if construct is None:
        return {}
    clients: dict[str, Any] = {}
    for chain in policy.chains:
        try:
            clients[chain.name] = construct(chain.name)
            active_logger.info(
                "[ALKAHEST] Client initialised for chain %s",
                chain.name,
            )
        except Exception as exc:
            active_logger.warning(
                "[ALKAHEST] Failed to initialise client for chain %s: %s. "
                "This chain has no client until it is constructed again.",
                chain.name,
                exc,
            )
    return clients
