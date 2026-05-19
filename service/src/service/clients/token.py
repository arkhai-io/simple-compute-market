"""ERC-20 token registry and on-chain balance queries."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[4] / "core" / "agent" / "app" / "data" / "token_registry_docker_compose.json"


class ERC20TokenMetadata(BaseModel):
    """Metadata for an ERC-20 token."""
    symbol: str
    name: Optional[str] = None
    contract_address: str
    decimals: int
    chain_id: Optional[int] = None


class TokenRegistryError(RuntimeError):
    """Raised when the registry encounters unrecoverable issues."""


class TokenRegistry:
    """Handles token metadata lookups backed by a JSON file."""

    def __init__(self, source_path: str | Path | None = None):
        if source_path:
            self._path = Path(source_path)
        else:
            # Falls back to a bundled default JSON if it exists; callers
            # that want a specific registry pass `source_path` explicitly.
            core_data = Path(__file__).resolve().parents[4] / "core" / "agent" / "app" / "data" / "token_registry.json"
            self._path = core_data if core_data.exists() else _DEFAULT_REGISTRY_PATH
        self._lock = RLock()
        self._tokens_by_symbol: dict[str, ERC20TokenMetadata] = {}
        self._tokens_by_address: dict[str, ERC20TokenMetadata] = {}
        self.reload()

    def reload(self) -> None:
        """Reload registry data from disk.

        Silent when the configured path is missing — the registry stays
        empty and lookups raise ``Unknown token: <symbol>`` at use time.
        Callers that explicitly point the registry at a user-supplied path
        (``init_token_registry``) are responsible for surfacing that case;
        unconditional warning here was noisy on every CLI invocation for
        the bundled-default fallback that no longer ships.
        """
        with self._lock:
            self._tokens_by_symbol.clear()
            self._tokens_by_address.clear()
            if not self._path.exists():
                return
            try:
                raw_tokens = json.loads(self._path.read_text())
            except json.JSONDecodeError as exc:
                raise TokenRegistryError(f"Invalid registry file: {exc}") from exc
            if not isinstance(raw_tokens, list):
                raise TokenRegistryError("Registry payload must be a list of token entries")
            for entry in raw_tokens:
                try:
                    token = ERC20TokenMetadata(**entry)
                except Exception as exc:
                    raise TokenRegistryError(f"Invalid token entry: {entry}") from exc
                self._store(token)

    def _store(self, token: ERC20TokenMetadata) -> None:
        symbol_key = token.symbol.upper()
        address_key = token.contract_address.lower()
        if symbol_key in self._tokens_by_symbol:
            raise TokenRegistryError(f"Duplicate symbol detected: {token.symbol}")
        if address_key in self._tokens_by_address:
            raise TokenRegistryError(f"Duplicate contract address detected: {token.contract_address}")
        self._tokens_by_symbol[symbol_key] = token
        self._tokens_by_address[address_key] = token

    def list_tokens(self) -> list[ERC20TokenMetadata]:
        with self._lock:
            return list(self._tokens_by_symbol.values())

    def get_by_symbol(self, symbol: str) -> ERC20TokenMetadata | None:
        with self._lock:
            return self._tokens_by_symbol.get(symbol.upper())

    def get_by_address(self, address: str) -> ERC20TokenMetadata | None:
        with self._lock:
            return self._tokens_by_address.get(address.lower())

    def resolve(self, identifier: str) -> ERC20TokenMetadata | None:
        """Resolve either a symbol (USDC) or contract address."""
        if identifier.startswith("0x"):
            return self.get_by_address(identifier)
        return self.get_by_symbol(identifier)

    def register_token(self, token: ERC20TokenMetadata, persist: bool = False) -> None:
        with self._lock:
            self._store(token)
            if persist:
                self._persist()

    def require(self, identifier: str) -> ERC20TokenMetadata:
        token = self.resolve(identifier)
        if token is None:
            raise TokenRegistryError(f"Unknown token: {identifier}")
        return token

    def _persist(self) -> None:
        payload = [token.model_dump() for token in self._tokens_by_symbol.values()]
        payload.sort(key=lambda entry: entry["symbol"].upper())
        self._path.write_text(json.dumps(payload, indent=2))

    def __len__(self) -> int:
        return len(self._tokens_by_symbol)

    def __contains__(self, symbol: str) -> bool:
        return self.get_by_symbol(symbol) is not None


async def get_wallet_token_balance(
    wallet_address: str,
    token_address: str,
    rpc_url: str,
) -> int:
    """Query ERC20 balanceOf(wallet_address) on-chain via web3.py.

    Returns raw integer balance (not scaled by decimals).
    Raises ValueError on RPC connection failure or invalid addresses.
    """
    _BALANCE_OF_ABI = [
        {
            "inputs": [{"type": "address"}],
            "name": "balanceOf",
            "outputs": [{"type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]
    try:
        from web3 import AsyncWeb3
        from web3.providers import AsyncHTTPProvider

        w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        contract = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(token_address),
            abi=_BALANCE_OF_ABI,
        )
        balance = await contract.functions.balanceOf(
            AsyncWeb3.to_checksum_address(wallet_address)
        ).call()
        return int(balance)
    except ImportError as exc:
        raise ValueError("web3 package not installed") from exc
    except Exception as exc:
        raise ValueError(f"Failed to query token balance: {exc}") from exc


# Module-level singleton — bound to the bundled default registry on
# import. Callers that need a specific registry path call
# ``init_token_registry(path)`` once at startup; the singleton is
# mutated in place so any module that already did
# ``from service.clients.token import TOKEN_REGISTRY`` keeps seeing the
# updated data through the same object.
TOKEN_REGISTRY = TokenRegistry()


def init_token_registry(source_path: str | Path | None) -> TokenRegistry:
    """Re-point the module-level ``TOKEN_REGISTRY`` at a registry file.

    Mutates the existing singleton in place rather than returning a new
    object — this preserves references that other modules captured via
    ``from service.clients.token import TOKEN_REGISTRY`` at their own
    import time.

    No env reads — callers pass the path resolved from their own config.
    """
    if source_path is None:
        return TOKEN_REGISTRY
    path = Path(source_path)
    TOKEN_REGISTRY._path = path
    TOKEN_REGISTRY.reload()
    if not path.exists():
        logger.warning(
            "[TOKEN_REGISTRY] Configured path %s does not exist; registry empty",
            path,
        )
    return TOKEN_REGISTRY


def render_token(
    token: ERC20TokenMetadata | str | dict | None,
    *,
    registry: TokenRegistry | None = None,
) -> str:
    """Format a token for human display: "SYMBOL (0x...)" when known.

    Address is always shown — strict-mode storage carries addresses as the
    canonical identity, and surfacing both prevents the chain-ambiguity
    confusion that bare symbols ("USDC on which chain?") cause. When the
    symbol is unknown or the input is just an address, returns "0x...".
    Returns "-" for None / missing.

    Inputs:
      * ``ERC20TokenMetadata`` — full metadata, render directly.
      * ``str`` — 0x address; look up symbol via ``registry`` (defaults
        to the module singleton) for the parenthetical.
      * ``dict`` — partial metadata; uses keys present.
      * ``None`` / falsy — returns "-".
    """
    if not token:
        return "-"
    reg = registry if registry is not None else TOKEN_REGISTRY

    if isinstance(token, ERC20TokenMetadata):
        sym, addr = token.symbol, token.contract_address
    elif isinstance(token, dict):
        addr = str(token.get("contract_address", "") or "")
        sym = str(token.get("symbol", "") or "")
        if not sym and addr:
            looked = reg.get_by_address(addr)
            if looked is not None:
                sym = looked.symbol
    elif isinstance(token, str):
        addr = token
        looked = reg.get_by_address(addr) if addr.startswith("0x") else None
        sym = looked.symbol if looked is not None else ""
    else:
        return str(token)

    if sym:
        return f"{sym} ({addr})"
    return addr or "-"


__all__ = [
    "ERC20TokenMetadata",
    "TokenRegistry",
    "TokenRegistryError",
    "TOKEN_REGISTRY",
    "init_token_registry",
    "get_wallet_token_balance",
    "render_token",
]
