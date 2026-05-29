"""ERC-20 token metadata, resolved from chain with on-disk caching.

Tokens are identified canonically by ``(chain_id, contract_address)``.
Symbol and decimals are sourced via ``symbol()`` / ``decimals()`` eth_call
against the configured RPC and cached at
``$XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json`` keyed by lowercased
address. ERC-20 metadata is immutable on chain, so the cache never goes
stale.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ERC20TokenMetadata(BaseModel):
    symbol: str
    name: Optional[str] = None
    contract_address: str
    decimals: int
    chain_id: Optional[int] = None


class TokenResolutionError(RuntimeError):
    """Raised when on-chain resolution fails (bad address, RPC down, etc.)."""


def _cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "arkhai" / "tokens"


def _cache_path_for(chain_id: int) -> Path:
    return _cache_root() / f"{chain_id}.json"


_MEMORY_CACHE: dict[int, dict[str, ERC20TokenMetadata]] = {}
_LOCK = RLock()


def _http_rpc_url(rpc_url: str) -> str:
    """Return an HTTP(S) URL suitable for web3 HTTP providers."""
    if rpc_url.startswith("ws://"):
        return "http://" + rpc_url[len("ws://"):]
    if rpc_url.startswith("wss://"):
        return "https://" + rpc_url[len("wss://"):]
    return rpc_url


def _load_chain_cache(chain_id: int) -> dict[str, ERC20TokenMetadata]:
    with _LOCK:
        cached = _MEMORY_CACHE.get(chain_id)
        if cached is not None:
            return cached
        cached = {}
        path = _cache_path_for(chain_id)
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                for addr_key, entry in raw.items():
                    cached[addr_key.lower()] = ERC20TokenMetadata(**entry)
            except Exception as exc:
                logger.warning(
                    "[TOKEN_CACHE] Ignoring unreadable cache %s: %s", path, exc
                )
        _MEMORY_CACHE[chain_id] = cached
        return cached


def _persist_chain_cache(chain_id: int) -> None:
    with _LOCK:
        cached = _MEMORY_CACHE.get(chain_id, {})
        path = _cache_path_for(chain_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {addr: meta.model_dump() for addr, meta in cached.items()}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)


def resolve_token_cached(
    address: str,
    *,
    chain_id: int | None = None,
) -> ERC20TokenMetadata | None:
    """Return cached metadata for ``address`` without RPC.

    When ``chain_id`` is provided, looks up only that chain's cache. When
    omitted, scans every loaded chain — convenient for display paths that
    don't carry chain context, but ambiguous if the same address has been
    resolved on multiple chains (returns first hit).
    """
    if not address or not address.startswith("0x"):
        return None
    key = address.lower()
    with _LOCK:
        if chain_id is not None:
            return _load_chain_cache(chain_id).get(key)
        for cache in _MEMORY_CACHE.values():
            hit = cache.get(key)
            if hit is not None:
                return hit
        return None


def resolve_token(
    address: str,
    *,
    rpc_url: str,
    chain_id: int,
    refresh: bool = False,
) -> ERC20TokenMetadata:
    """Resolve an ERC-20 contract to metadata. RPC + cache.

    Cached hits return immediately. Misses eth_call ``symbol()`` and
    ``decimals()``, store the result, and persist to disk. Set ``refresh``
    to bypass the cache and re-RPC.

    Raises ``TokenResolutionError`` when the contract doesn't respond to
    the standard ERC-20 view methods or RPC is unreachable.
    """
    if not address or not address.startswith("0x") or len(address) != 42:
        raise TokenResolutionError(
            f"Not an ERC-20 contract address: {address!r}"
        )
    key = address.lower()
    cache = _load_chain_cache(chain_id)
    if not refresh:
        hit = cache.get(key)
        if hit is not None:
            return hit

    try:
        from web3 import Web3
        from web3.providers import HTTPProvider
    except ImportError as exc:
        raise TokenResolutionError("web3 package not installed") from exc

    abi = [
        {"inputs": [], "name": "symbol",
         "outputs": [{"type": "string"}],
         "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "decimals",
         "outputs": [{"type": "uint8"}],
         "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "name",
         "outputs": [{"type": "string"}],
         "stateMutability": "view", "type": "function"},
    ]

    try:
        w3 = Web3(HTTPProvider(_http_rpc_url(rpc_url)))
        checksum = Web3.to_checksum_address(address)
        contract = w3.eth.contract(address=checksum, abi=abi)
        symbol = contract.functions.symbol().call()
        decimals = int(contract.functions.decimals().call())
        try:
            name = contract.functions.name().call()
        except Exception:
            name = None
    except Exception as exc:
        raise TokenResolutionError(
            f"Failed to resolve {address} on chain {chain_id}: {exc}"
        ) from exc

    meta = ERC20TokenMetadata(
        symbol=str(symbol),
        name=str(name) if name else None,
        contract_address=checksum,
        decimals=decimals,
        chain_id=chain_id,
    )
    with _LOCK:
        cache[key] = meta
        _persist_chain_cache(chain_id)
    return meta


def resolve_token_by_symbol_in(
    symbol: str,
    addresses: list[str],
    *,
    rpc_url: str,
    chain_id: int,
) -> ERC20TokenMetadata | None:
    """Find the first address whose on-chain symbol matches ``symbol``.

    Used by buyer-side filters: given a set of candidate token addresses
    (e.g. from discovered listings), find the one(s) matching a
    user-supplied symbol. Returns ``None`` when no candidate resolves to
    a matching symbol; raises ``TokenResolutionError`` if RPC fails on
    every candidate (resolve_token errors are swallowed per-address so
    one bad contract doesn't poison the whole filter).
    """
    target = symbol.upper()
    last_exc: Exception | None = None
    for addr in addresses:
        try:
            meta = resolve_token(addr, rpc_url=rpc_url, chain_id=chain_id)
        except TokenResolutionError as exc:
            last_exc = exc
            continue
        if meta.symbol.upper() == target:
            return meta
    if last_exc is not None and not addresses:
        raise last_exc
    return None


async def get_wallet_token_balance(
    wallet_address: str,
    token_address: str,
    rpc_url: str,
) -> int:
    """Query ERC20 balanceOf(wallet_address) on-chain via web3.py.

    Returns raw integer balance (not scaled by decimals).
    Raises ValueError on RPC connection failure or invalid addresses.
    """
    abi = [
        {"inputs": [{"type": "address"}], "name": "balanceOf",
         "outputs": [{"type": "uint256"}],
         "stateMutability": "view", "type": "function"}
    ]
    try:
        from web3 import AsyncWeb3
        from web3.providers import AsyncHTTPProvider

        w3 = AsyncWeb3(AsyncHTTPProvider(_http_rpc_url(rpc_url)))
        contract = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(token_address),
            abi=abi,
        )
        balance = await contract.functions.balanceOf(
            AsyncWeb3.to_checksum_address(wallet_address)
        ).call()
        return int(balance)
    except ImportError as exc:
        raise ValueError("web3 package not installed") from exc
    except Exception as exc:
        raise ValueError(f"Failed to query token balance: {exc}") from exc


def render_token(
    token: ERC20TokenMetadata | str | dict | None,
    *,
    chain_id: int | None = None,
) -> str:
    """Format a token for human display: "SYMBOL (0x...)" when symbol is
    cached, otherwise just the address. Returns "-" for empty input.

    Symbol lookup is cache-only — never triggers RPC. Callers that want
    the symbol guaranteed populated should call ``resolve_token`` first.
    """
    if not token:
        return "-"

    if isinstance(token, ERC20TokenMetadata):
        sym, addr = token.symbol, token.contract_address
    elif isinstance(token, dict):
        addr = str(token.get("contract_address", "") or "")
        sym = str(token.get("symbol", "") or "")
        if not sym and addr:
            looked = resolve_token_cached(addr, chain_id=chain_id)
            if looked is not None:
                sym = looked.symbol
    elif isinstance(token, str):
        addr = token
        looked = (
            resolve_token_cached(addr, chain_id=chain_id)
            if addr.startswith("0x") else None
        )
        sym = looked.symbol if looked is not None else ""
    else:
        return str(token)

    if sym:
        return f"{sym} ({addr})"
    return addr or "-"


__all__ = [
    "ERC20TokenMetadata",
    "TokenResolutionError",
    "resolve_token",
    "resolve_token_cached",
    "resolve_token_by_symbol_in",
    "get_wallet_token_balance",
    "render_token",
]
