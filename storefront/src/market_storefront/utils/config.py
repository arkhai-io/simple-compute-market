"""Storefront configuration via dynaconf.

Layered (highest priority last):
  1. ``settings.toml`` next to this package — committed defaults documenting
     every supported key.
  2. ``$XDG_CONFIG_HOME/arkhai/storefront.toml`` — ConfigMap base.
  3. ``$XDG_CONFIG_HOME/arkhai/storefront.secrets.toml`` — Secret overlay
     (wallet key, admin API key, gemini key, inline resources CSV).
  4. ``STOREFRONT_*`` environment variables (separator ``__``).

Direct attribute access: ``settings.port``, ``settings.wallet.private_key``,
``settings.provisioning.service_url``, ``settings.registry.urls``. See
``settings.toml`` for the schema.

Module-level constants are computed once at import:

* ``AGENT_ID`` — validated Python identifier, default ``"root_agent"``.
* ``AGENT_NAME`` — ``settings.agent_name``, falling back to ``AGENT_ID``.
* ``BASE_URL_OVERRIDE`` — ``settings.base_url`` with ZeroTier placeholder
  resolution applied.

Free function:

* ``chain_id()`` — returns ``settings.chain.chain_id`` when non-zero, otherwise
  issues a live ``eth_chainId`` RPC call against ``settings.chain.rpc_url``.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from service.config_loader import (  # type: ignore[import-not-found]
    KNOWN_IDENTITY_REGISTRY,
    storefront_config_files,
)
from service.clients.erc8004.blockchain import (  # type: ignore[import-not-found]
    rpc_url_for_http_provider,
)
from web3 import Web3
from web3.providers import HTTPProvider

from .zerotier import BaseUrlResolutionError, resolve_base_url_best_effort

logger = logging.getLogger(__name__)


DEFAULT_AGENT_ID = "root_agent"
_DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "settings.toml"


def _build_settings() -> Dynaconf:
    overlays = [str(p) for p in storefront_config_files() if Path(p).exists()]
    s = Dynaconf(
        settings_file=[str(_DEFAULTS_FILE)],
        includes=overlays,
        envvar_prefix="STOREFRONT",
        envvar_separator="__",
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )
    # Inject per-chain default for the ERC-8004 IdentityRegistry when the
    # operator hasn't set one. The canonical CREATE2 deployment uses the
    # same vanity address on every chain, so for the standard chain.name
    # values the operator gets a working default with no config required.
    if not s.get("registry.identity_registry_address"):
        chain = str(s.get("chain.name", "") or "")
        default = KNOWN_IDENTITY_REGISTRY.get(chain)
        if default:
            s.set("registry.identity_registry_address", default)
    return s


settings: Dynaconf = _build_settings()


# ---------------------------------------------------------------------------
# Composites — computed once at module load.
# ---------------------------------------------------------------------------


def _validate_agent_id(raw: Any) -> str:
    if not raw:
        warnings.warn(
            f"agent_id not set in storefront.toml. Using default "
            f"'{DEFAULT_AGENT_ID}'. Set agent_id to a valid identifier "
            f"(letters, digits, underscores only).",
            UserWarning,
        )
        return DEFAULT_AGENT_ID
    s = str(raw)
    if not s.isidentifier():
        raise ValueError(
            f"agent_id '{s}' is not a valid identifier. Must start with a "
            f"letter or underscore, and only contain letters, digits, and "
            f"underscores. Examples: 'my_agent', 'agent_123', '_internal_agent'"
        )
    return s


def get_agent_id(explicit_value: str | None = None) -> str:
    """Validated agent ID. Used by call sites that allow an explicit override
    (CLI flags, logging-config init). Most code should just import ``AGENT_ID``.
    """
    if explicit_value is not None:
        return _validate_agent_id(explicit_value)
    return _validate_agent_id(settings.get("agent_id", ""))


def _resolve_base_url() -> str:
    raw = str(settings.get("base_url", "http://localhost:8000"))
    zerotier = settings.get("zerotier_network") or None
    try:
        resolved = resolve_base_url_best_effort(raw, zerotier)
        if resolved != raw:
            logger.info(
                "[CONFIG] base_url resolved to %s (network=%s)", resolved, zerotier,
            )
        return resolved
    except BaseUrlResolutionError as exc:
        logger.warning("[CONFIG] base_url is invalid (%s); using raw value", exc)
        return raw


AGENT_ID: str = get_agent_id()
AGENT_NAME: str = str(settings.get("agent_name") or AGENT_ID)
BASE_URL_OVERRIDE: str = _resolve_base_url()


# ---------------------------------------------------------------------------
# chain_id — live composite, not cached (RPC may need re-evaluation in tests).
# ---------------------------------------------------------------------------


def chain_id() -> int:
    """Return the effective EVM chain ID.

    Resolution order:
      1. ``settings.chain.chain_id`` — pinned in ``[chain].chain_id``. This is
         the fast path and the expected state for all deployments.
      2. Live ``eth_chainId`` RPC call against ``settings.chain.rpc_url`` —
         fallback when ``chain.chain_id`` is 0 (unset).

    Raises ``RuntimeError`` when ``chain.chain_id`` is 0 and the RPC call fails,
    so callers surface the misconfiguration loudly rather than silently using
    a wrong value.
    """
    explicit = int(settings.get("chain.chain_id", 0) or 0)
    if explicit:
        return explicit
    rpc_url = settings.get("chain.rpc_url")
    if not rpc_url:
        raise RuntimeError(
            "chain.chain_id is not set in storefront.toml and chain.rpc_url is "
            "absent — cannot determine chain ID. Add chain_id = <N> under "
            "[chain] in storefront.toml."
        )
    try:
        w3 = Web3(
            HTTPProvider(
                rpc_url_for_http_provider(rpc_url),
                request_kwargs={"timeout": 5},
            )
        )
        return w3.eth.chain_id
    except Exception as exc:
        raise RuntimeError(
            f"chain.chain_id is not set in storefront.toml and the RPC fallback "
            f"failed ({exc}). Add chain_id = <N> under [chain] in storefront.toml."
        ) from exc
