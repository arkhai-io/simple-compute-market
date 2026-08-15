"""Alkahest client construction from immutable domain-supplied configuration."""

from __future__ import annotations

import logging
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


def build_alkahest_clients(
    policy: AlkahestClientPolicy,
    *,
    logger: LoggerLike | None = None,
) -> dict[str, Any]:
    """Build every usable configured client and isolate per-chain failures."""

    active_logger = logger or logging.getLogger(__name__)
    missing = tuple(item for item in policy.missing_requirements if item)
    if not policy.private_key and "wallet.private_key" not in missing:
        missing = (*missing, "wallet.private_key")
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

    (
        client_type,
        get_network,
        prewarm_address_config,
        resolve_address_config,
    ) = _load_dependencies()
    clients: dict[str, Any] = {}
    for chain in policy.chains:
        try:
            prewarm_address_config(chain.address_config_path)
            network = get_network(chain.name)
            address_config = resolve_address_config(
                network,
                config_path=chain.address_config_path,
            )
            clients[chain.name] = client_type(
                private_key=policy.private_key,
                rpc_url=chain.rpc_url,
                address_config=address_config,
            )
            active_logger.info(
                "[ALKAHEST] Client initialised for chain %s",
                chain.name,
            )
        except Exception as exc:
            active_logger.warning(
                "[ALKAHEST] Failed to initialise client for chain %s: %s. "
                "This chain will not be available at runtime.",
                chain.name,
                exc,
            )
    return clients
