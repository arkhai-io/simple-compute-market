"""Probing each configured Alkahest chain apart from readiness.

Readiness is evaluated per publication candidate, per status read, and at
startup, so it must never call a chain itself. :class:`AlkahestChainProbe` holds
each configured chain's last result instead, and a storefront registers its
:meth:`~AlkahestChainProbe.step` as a lifecycle loop whose timer runs it once
per probe interval. Each step probes every chain, reading the chain's identity
(``eth_chainId``) and then the code at each contract address its address
configuration requires (``eth_getCode``), every call bounded by the RPC
timeout; so an operator's explicit step always probes, and the timer bounds how
often a chain is called. A result does not expire: while the loop is held,
readiness reads the last one however old.

A chain's result is one of:

- ``reachable``;
- ``alkahest.chain_unreachable``, when a call errors or times out, which tells
  publication the mechanism's readiness is unknown;
- ``alkahest.chain_id_mismatch``, ``alkahest.contract_missing``, or
  ``alkahest.address_config_invalid``, which the configuration causes.

The probe also holds the storefront's live map of chain clients. A chain whose
client could not be constructed has its client constructed again at each probe
until that succeeds, bounded by the RPC timeout, and the map is updated in
place, so every consumer handed the map reaches the rebuilt client without a
restart. Until then the chain reads ``alkahest.chain_unreachable``, whatever
its JSON-RPC calls answer.

The JSON-RPC calls go over each chain's ``rpc_url`` directly rather than
through a chain client, because a probe must answer for a chain whose client
does not exist. A websocket ``rpc_url`` is called over HTTP at the same host,
port, and path (``ws://`` as ``http://``, ``wss://`` as ``https://``), so a
provider serving the two on different endpoints reads as unreachable.
:func:`probe_addresses_sync` is the one-shot form an operator's chain check
uses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .alkahest import (
    _sdk_addresses_for_chain,
    get_alkahest_network,
    resolve_alkahest_address_config,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_PROBE_INTERVAL_SECONDS = 30.0

#: The lifecycle loop each storefront composing Alkahest registers the probe's
#: step as, and the route its pause and explicit step take.
ALKAHEST_CHAIN_PROBE_LOOP = "alkahest_chain_probe"
ALKAHEST_CHAIN_PROBE_ROUTE = "alkahest-chain-probe"

CHAIN_REACHABLE = "reachable"
CHAIN_UNREACHABLE = "alkahest.chain_unreachable"
CHAIN_ID_MISMATCH = "alkahest.chain_id_mismatch"
CONTRACT_MISSING = "alkahest.contract_missing"
ADDRESS_CONFIG_INVALID = "alkahest.address_config_invalid"

#: The contracts every Alkahest settlement on a chain uses, by their place in
#: the chain's address configuration and the label a report gives them.
REQUIRED_CONTRACTS: tuple[tuple[tuple[str, str], str], ...] = (
    (("arbiters_addresses", "recipient_arbiter"), "alkahest.recipient_arbiter"),
    (("arbiters_addresses", "eas"), "alkahest.eas"),
    (
        ("erc20_addresses", "escrow_obligation_default"),
        "alkahest.erc20_escrow_obligation",
    ),
)

#: ``(rpc_url, method, params, timeout_seconds)`` to the call's ``result``.
JsonRpcCall = Callable[[str, str, list[Any], float], Any]


def _http_rpc_url(rpc_url: str) -> str:
    """The HTTP form of ``rpc_url``: a seller may configure a websocket URL for
    the SDK's subscriptions, and a one-shot call is plain HTTP."""
    s = rpc_url.strip()
    if s.startswith("ws://"):
        return "http://" + s[len("ws://"):]
    if s.startswith("wss://"):
        return "https://" + s[len("wss://"):]
    return s


def json_rpc_call(rpc_url: str, method: str, params: list[Any], timeout: float) -> Any:
    """One JSON-RPC call, returning its ``result``.

    Raises on a transport error, a timeout, a non-200 response, an error
    envelope, or a response with no ``result``.
    """
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    req = urllib.request.Request(
        _http_rpc_url(rpc_url),
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(f"{method} error: {payload['error']}")
    if "result" not in payload:
        raise RuntimeError(f"{method} returned no `result` field")
    return payload["result"]


@dataclass(frozen=True, slots=True)
class ProbedChain:
    """One configured chain, as the probe reads it."""

    name: str
    rpc_url: str
    chain_id: int | None = None
    address_config_path: str | None = None

    @classmethod
    def from_config(cls, name: str, chain: Any) -> ProbedChain:
        """One configured chain, given as a mapping or an object with the
        ``rpc_url``, ``chain_id``, and ``alkahest_address_config_path`` a
        ``[Chains.<name>]`` table states."""

        def value(key: str) -> Any:
            return chain.get(key) if isinstance(chain, Mapping) else getattr(chain, key, None)

        chain_id = value("chain_id")
        path = value("alkahest_address_config_path")
        return cls(
            name=name,
            rpc_url=str(value("rpc_url") or ""),
            chain_id=int(chain_id) if chain_id is not None else None,
            address_config_path=str(path) if path else None,
        )


@dataclass(frozen=True, slots=True)
class ChainProbeResult:
    """One chain's last probe: its result and when it was taken."""

    result: str
    probed_at: datetime

    @property
    def reachable(self) -> bool:
        return self.result == CHAIN_REACHABLE

    def public(self) -> dict[str, str]:
        return {"result": self.result, "probed_at": self.probed_at.isoformat()}


def required_contract_addresses(chain: ProbedChain) -> dict[str, str]:
    """``{label: address}`` for every contract :data:`REQUIRED_CONTRACTS` names.

    Read from the chain's address configuration, or the SDK's own addresses
    where the chain names none. Raises when the configuration cannot be
    resolved or names none of a required contract.
    """
    network = get_alkahest_network(chain.name)
    config = resolve_alkahest_address_config(
        network, config_path=chain.address_config_path
    )
    if config is None:
        config = _sdk_addresses_for_chain(network)
    addresses: dict[str, str] = {}
    for path, label in REQUIRED_CONTRACTS:
        value: Any = config
        for attr in path:
            value = getattr(value, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"address configuration names no {label}")
        addresses[label] = value.strip()
    return addresses


class AlkahestChainProbe:
    """Each configured chain's last probe result and the live chain-client map.

    ``build_client`` constructs one chain's client by name and raises when it
    cannot; ``clients`` is the map construction at startup already filled, which
    the probe then owns and updates in place. ``json_rpc`` and ``clock`` are the
    boundaries a test replaces.
    """

    def __init__(
        self,
        chains: Iterable[ProbedChain],
        *,
        build_client: Callable[[str], Any] | None = None,
        clients: MutableMapping[str, Any] | None = None,
        interval_seconds: float = DEFAULT_PROBE_INTERVAL_SECONDS,
        rpc_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        json_rpc: JsonRpcCall = json_rpc_call,
        required_addresses: Callable[[ProbedChain], Mapping[str, str]] = (
            required_contract_addresses
        ),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._chains = {chain.name: chain for chain in chains}
        self._build_client = build_client
        self._clients: MutableMapping[str, Any] = clients if clients is not None else {}
        self._interval = timedelta(seconds=interval_seconds)
        self._timeout = rpc_timeout_seconds
        self._json_rpc = json_rpc
        self._required_addresses = required_addresses
        self._clock = clock
        self._results: dict[str, ChainProbeResult] = {}

    @property
    def clients(self) -> MutableMapping[str, Any]:
        """The live chain-client map, which every client consumer is handed."""
        return self._clients

    @property
    def chain_names(self) -> tuple[str, ...]:
        return tuple(self._chains)

    @property
    def interval_seconds(self) -> float:
        """The probe interval, which the loop's timer runs the step at."""
        return self._interval.total_seconds()

    @property
    def rpc_timeout_seconds(self) -> float:
        """The bound on each JSON-RPC call."""
        return self._timeout

    def result(self, chain_name: str) -> ChainProbeResult | None:
        """The chain's last result, or ``None`` before its first probe."""
        return self._results.get(chain_name)

    def public_results(self) -> dict[str, dict[str, str] | None]:
        """Every configured chain's last result, as status reports it."""
        return {
            name: (result.public() if (result := self._results.get(name)) else None)
            for name in self._chains
        }

    async def step(self) -> dict[str, Any]:
        """Probe every chain, and rebuild any client still missing."""
        now = self._clock()
        names = list(self._chains)
        outcomes = await asyncio.gather(*(self._probe(name) for name in names))
        for name, result in zip(names, outcomes):
            self._results[name] = ChainProbeResult(result=result, probed_at=now)
        return {"probed": sorted(names), "chains": self.public_results()}

    async def _probe(self, chain_name: str) -> str:
        chain = self._chains[chain_name]
        has_client = await self._construct_missing_client(chain_name)
        result = await asyncio.to_thread(self._probe_sync, chain)
        # Servicing settles through the client, not the HTTP calls: a chain
        # whose client could not be built reads unreachable whatever its HTTP
        # side answers, so its listings are held and the next step builds again.
        if result == CHAIN_REACHABLE and not has_client:
            return CHAIN_UNREACHABLE
        return result

    async def _construct_missing_client(self, chain_name: str) -> bool:
        """Construct the chain's client if the map lacks one; whether it has one.

        A probe given no constructor has none it could build, and reports what
        the chain answers. Construction is bounded by the RPC timeout, since a
        websocket client connects while it is built and an endpoint that
        accepts the connection but never upgrades it would otherwise hold the
        step, and with it the loop's cycle lock, for good. A worker thread
        cannot be stopped, so a construction that finishes after its timeout is
        discarded: the map takes only the result the probe awaited.
        """
        if chain_name in self._clients or self._build_client is None:
            return True
        try:
            client = await asyncio.wait_for(
                asyncio.to_thread(self._build_client, chain_name),
                timeout=self._timeout,
            )
        except Exception as exc:  # each chain's construction is isolated
            logger.warning(
                "[ALKAHEST] client for chain %s could not be constructed: %s",
                chain_name,
                type(exc).__name__,
            )
            return False
        self._clients[chain_name] = client
        return True

    def _probe_sync(self, chain: ProbedChain) -> str:
        try:
            addresses = self._required_addresses(chain)
        except Exception:
            return ADDRESS_CONFIG_INVALID
        try:
            observed = self._json_rpc(chain.rpc_url, "eth_chainId", [], self._timeout)
            observed_id = int(str(observed), 16)
        except Exception:
            return CHAIN_UNREACHABLE
        if chain.chain_id is not None and observed_id != int(chain.chain_id):
            return CHAIN_ID_MISMATCH
        for address in addresses.values():
            try:
                code = self._json_rpc(
                    chain.rpc_url, "eth_getCode", [address, "latest"], self._timeout
                )
            except Exception:
                return CHAIN_UNREACHABLE
            if not isinstance(code, str) or code in ("", "0x"):
                return CONTRACT_MISSING
        return CHAIN_REACHABLE


def probe_addresses_sync(
    rpc_url: str,
    addresses: dict[str, str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, bool]:
    """Probe a set of addresses for deployed bytecode, once.

    ``addresses`` is ``{label: address}``; a label with no address maps to
    ``False``, as does one whose call fails or finds no code. Each problem is
    logged as a warning.
    """
    results: dict[str, bool] = {}
    missing: list[str] = []
    errors: list[tuple[str, str]] = []

    for label, addr in addresses.items():
        if not addr or not isinstance(addr, str) or not addr.strip():
            results[label] = False
            missing.append(f"{label} (no address configured)")
            continue
        try:
            code = json_rpc_call(
                rpc_url, "eth_getCode", [addr.strip(), "latest"], timeout
            )
        except (urllib.error.URLError, RuntimeError, OSError, ValueError) as exc:
            errors.append((label, f"{type(exc).__name__}: {exc}"))
            results[label] = False
            continue
        # Empty bytecode is the literal "0x" — anything longer is real code.
        has_code = isinstance(code, str) and bool(code) and code != "0x"
        results[label] = has_code
        if not has_code:
            missing.append(f"{label}={addr}")

    if errors:
        logger.warning(
            "[CHAIN_PROBE] Failed to probe %d address(es) on %s: %s",
            len(errors), rpc_url,
            ", ".join(f"{label} ({error})" for label, error in errors),
        )
    if missing:
        logger.warning(
            "[CHAIN_PROBE] No bytecode at %d configured address(es) on %s: %s. "
            "Check the chain selection and contract addresses in config.toml.",
            len(missing), rpc_url, ", ".join(missing),
        )
    elif results:
        logger.info(
            "[CHAIN_PROBE] All %d configured contract address(es) "
            "have bytecode on %s.",
            len(results), rpc_url,
        )
    return results


__all__ = [
    "ADDRESS_CONFIG_INVALID",
    "ALKAHEST_CHAIN_PROBE_LOOP",
    "ALKAHEST_CHAIN_PROBE_ROUTE",
    "CHAIN_ID_MISMATCH",
    "CHAIN_REACHABLE",
    "CHAIN_UNREACHABLE",
    "CONTRACT_MISSING",
    "DEFAULT_PROBE_INTERVAL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "REQUIRED_CONTRACTS",
    "AlkahestChainProbe",
    "ChainProbeResult",
    "JsonRpcCall",
    "ProbedChain",
    "json_rpc_call",
    "probe_addresses_sync",
    "required_contract_addresses",
]
