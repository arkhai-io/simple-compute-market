"""Simple ERC-20 token registry loader."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock

from app.schema.pydantic_models import ERC20TokenMetadata
from app.utils.config import CONFIG

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "token_registry.json"


class TokenRegistryError(RuntimeError):
    """Raised when the registry encounters unrecoverable issues."""


class TokenRegistry:
    """Handles token metadata lookups backed by a JSON file."""

    def __init__(self, source_path: str | Path | None = None):
        self._path = Path(source_path) if source_path else DEFAULT_REGISTRY_PATH
        self._lock = RLock()
        self._tokens_by_symbol: dict[str, ERC20TokenMetadata] = {}
        self._tokens_by_address: dict[str, ERC20TokenMetadata] = {}
        self.reload()

    def reload(self) -> None:
        """Reload registry data from disk."""
        with self._lock:
            self._tokens_by_symbol.clear()
            self._tokens_by_address.clear()
            if not self._path.exists():
                logger.warning("[TOKEN_REGISTRY] Path %s does not exist; registry empty", self._path)
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

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._tokens_by_symbol)

    def __contains__(self, symbol: str) -> bool:  # pragma: no cover - convenience
        return self.get_by_symbol(symbol) is not None


TOKEN_REGISTRY = TokenRegistry(CONFIG.token_registry_path)

__all__ = ["TokenRegistry", "TokenRegistryError", "TOKEN_REGISTRY"]
