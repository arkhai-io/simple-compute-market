"""Lightweight ``eth_getCode`` probe for startup config validation.

Vendored from ``service.clients.chain_probe`` because registry-service is
a standalone deployable that doesn't depend on the market-service
package. Refresh in lockstep if the upstream module's interface changes.

The probe issues one JSON-RPC ``eth_getCode`` per address against the
configured RPC and returns ``{label: has_bytecode}``. Anything mapping
to ``False`` means the address is unconfigured, has nothing deployed at
it, or the RPC points at the wrong chain — operator misconfig that
should surface at startup, not at first transaction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0


class ChainProbeError(RuntimeError):
    """Raised when ``probe_addresses`` is told to fail-closed and one or
    more addresses don't resolve to bytecode."""


def _eth_get_code(rpc_url: str, address: str, *, timeout: float) -> str:
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
        addresses: ``{label: address}``. Pairs whose address is falsy
            are skipped.
        fail_on_missing: When True, raises ``ChainProbeError`` if any
            address has no bytecode.
        timeout: Per-call socket timeout.

    Returns:
        ``{label: has_bytecode}``.
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
            "Check the chain selection and contract addresses in env."
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
    """Async wrapper for callers inside FastAPI lifespans."""
    return await asyncio.to_thread(
        probe_addresses_sync,
        rpc_url,
        addresses,
        fail_on_missing=fail_on_missing,
        timeout=timeout,
    )
