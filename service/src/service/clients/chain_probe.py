"""Lightweight ``eth_getCode`` probe for startup config validation.

Each role at startup hands this helper a dict of ``{label: address}``
for the contracts it expects to interact with. The probe issues one
JSON-RPC ``eth_getCode`` per address against the configured RPC and
returns ``{label: has_bytecode}``. Anything mapping to ``False`` means
the address is unconfigured, has nothing deployed at it, or the RPC
points at the wrong chain — operator misconfig that should surface at
startup, not at first transaction.

Sync via ``urllib`` so this module has no extra dependencies; an async
wrapper is provided for callers running inside FastAPI lifespans.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0


class ChainProbeError(RuntimeError):
    """Raised when ``probe_addresses`` is told to fail-closed and one or
    more addresses don't resolve to bytecode."""


def _eth_get_code(rpc_url: str, address: str, *, timeout: float) -> str:
    """Issue a single ``eth_getCode(address, "latest")`` JSON-RPC call.

    Returns the hex-string ``result`` (e.g. ``"0x6080..."``). Empty
    bytecode is the literal string ``"0x"``. Raises on transport error,
    non-200 response, or malformed JSON-RPC envelope.
    """
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getCode",
        "params": [address, "latest"],
    }).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(f"eth_getCode error: {payload['error']}")
    result = payload.get("result")
    if not isinstance(result, str):
        raise RuntimeError(f"eth_getCode returned no `result` field: {payload}")
    return result


def probe_addresses_sync(
    rpc_url: str,
    addresses: dict[str, str],
    *,
    fail_on_missing: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, bool]:
    """Probe a set of addresses for deployed bytecode.

    Args:
        rpc_url: The chain RPC endpoint to query.
        addresses: ``{label: address}``. Labels are operator-readable
            identifiers used in log output (e.g. ``"identity_registry"``,
            ``"alkahest.recipient_arbiter"``). Pairs whose address is
            falsy (``None``/``""``) are skipped — caller has more
            context than we do about which fields are required.
        fail_on_missing: When True, raises ``ChainProbeError`` if any
            address has no bytecode. When False (default), logs a
            warning and returns the result map.
        timeout: Per-call socket timeout.

    Returns:
        ``{label: has_bytecode}``. Skipped (falsy address) entries map
        to ``False``.
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
            code = _eth_get_code(rpc_url, addr.strip(), timeout=timeout)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            errors.append((label, f"{type(exc).__name__}: {exc}"))
            results[label] = False
            continue
        # Empty bytecode is the literal "0x" — anything longer is real code.
        has_code = bool(code) and code != "0x"
        results[label] = has_code
        if not has_code:
            missing.append(f"{label}={addr}")

    if errors:
        logger.warning(
            "[CHAIN_PROBE] Failed to probe %d address(es) on %s: %s",
            len(errors), rpc_url,
            ", ".join(f"{l} ({e})" for l, e in errors),
        )

    if missing:
        msg = (
            f"[CHAIN_PROBE] No bytecode at {len(missing)} configured "
            f"address(es) on {rpc_url}: {', '.join(missing)}. "
            "Check the chain selection and contract addresses in config.toml."
        )
        if fail_on_missing:
            raise ChainProbeError(msg)
        logger.warning(msg)
    elif results:
        logger.info(
            "[CHAIN_PROBE] All %d configured contract address(es) "
            "have bytecode on %s.",
            len(results), rpc_url,
        )

    return results


async def probe_addresses(
    rpc_url: str,
    addresses: dict[str, str],
    *,
    fail_on_missing: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, bool]:
    """Async wrapper for callers inside FastAPI lifespans.

    The probe itself is sync (urllib + plain HTTP); we just offload it to
    a thread so it doesn't block the event loop while the RPC responds.
    """
    return await asyncio.to_thread(
        probe_addresses_sync,
        rpc_url,
        addresses,
        fail_on_missing=fail_on_missing,
        timeout=timeout,
    )
