"""API-tokens storefront configuration via dynaconf.

Layered (highest priority last):
  1. ``settings.toml`` next to this package — committed defaults
     documenting every supported key.
  2. ``$XDG_CONFIG_HOME/arkhai/storefront.toml`` — ConfigMap base.
  3. ``$XDG_CONFIG_HOME/arkhai/storefront.secrets.toml`` — Secret overlay.
  4. ``APITOKENS_STOREFRONT_*`` environment variables (separator ``__``).

The overlay files are the same ones the VM storefront reads — one
storefront per container, each with its own mount; the env prefix
differs so colocated local runs can still be steered independently.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from market_config.config_loader import (
    ChainConfig,
    chains_from_config,
    derive_wallet_address,
    storefront_config_files,
)

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "root_agent"
_DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "settings.toml"


def _build_settings() -> Dynaconf:
    overlays = [str(p) for p in storefront_config_files() if Path(p).exists()]
    s = Dynaconf(
        settings_file=[str(_DEFAULTS_FILE)],
        includes=overlays,
        envvar_prefix="APITOKENS_STOREFRONT",
        envvar_separator="__",
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )
    pk = str(s.get("wallet.private_key", "") or "")
    addr_cfg = str(s.get("wallet.address", "") or "")
    if pk:
        derived_addr = derive_wallet_address(pk)
        if derived_addr:
            if not addr_cfg:
                s.set("wallet.address", derived_addr)
            elif addr_cfg.lower() != derived_addr.lower():
                logger.warning(
                    "[CONFIG] wallet.address (%s) does not match the address "
                    "derived from wallet.private_key (%s); using the "
                    "configured address.", addr_cfg, derived_addr,
                )
    return s


def _coerce_chains_table(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None or not hasattr(raw, "items"):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, sub in raw.items():
        if not isinstance(name, str):
            continue
        if hasattr(sub, "items"):
            out[name] = {k: v for k, v in sub.items()}
        elif isinstance(sub, dict):
            out[name] = sub
    return out


settings: Dynaconf = _build_settings()
CHAINS: dict[str, ChainConfig] = chains_from_config(
    {"chains": _coerce_chains_table(settings.get("chains"))},
)

if not CHAINS:
    logger.warning(
        "[CONFIG] no [chains.<name>] tables configured — the storefront "
        "will fail when it needs to dispatch any on-chain call."
    )


def _validate_agent_id(raw: Any) -> str:
    if not raw:
        return DEFAULT_AGENT_ID
    s = str(raw)
    if not s.isidentifier():
        raise ValueError(
            f"agent_id {s!r} is not a valid identifier (letters, digits, "
            "underscores; must not start with a digit)."
        )
    return s


def tokens_service_url() -> str:
    """The tokens service this storefront sells for."""
    return str(settings.get("tokens.service_url", "") or "").rstrip("/")


def tokens_admin_key() -> str:
    """Admin key for the tokens service; falls back to admin_api_key."""
    return str(
        settings.get("tokens.admin_key", "")
        or settings.get("admin_api_key", "")
        or ""
    )


AGENT_ID: str = _validate_agent_id(settings.get("agent_id", ""))
AGENT_NAME: str = str(settings.get("agent_name") or AGENT_ID)
BASE_URL_OVERRIDE: str = str(settings.get("base_url", "http://localhost:8002"))
