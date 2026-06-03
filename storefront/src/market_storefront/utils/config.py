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
* ``CHAINS`` — ``dict[str, ChainConfig]`` built from the ``[chains.<name>]``
  TOML tables. Storefront call sites that need on-chain dispatch look up
  ``CHAINS[chain_name]`` where ``chain_name`` comes from the incoming
  proposal / escrow context.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from service.config_loader import (  # type: ignore[import-not-found]
    ChainConfig,
    EscrowTemplate,
    chains_from_config,
    derive_wallet_address,
    escrow_templates_from_config,
    storefront_config_files,
)

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

    # Derive wallet.address from wallet.private_key when only the key is
    # set. The address is a deterministic function of the key, so there's
    # no reason to require both in config. When both are set and disagree
    # the configured address wins (user might be intentionally signing
    # for a delegated address), but we log a warning so the mismatch
    # doesn't hide later confusion.
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
                    "derived from wallet.private_key (%s); using the configured "
                    "address.",
                    addr_cfg, derived_addr,
                )
    return s


def _coerce_chains_table(raw: Any) -> dict[str, dict[str, Any]]:
    """Materialise dynaconf's ``settings.chains`` into a plain dict-of-dicts.

    Dynaconf hands the nested table back as a ``DynaBox`` (or similar
    mapping wrapper); :func:`chains_from_config` requires real dicts to
    walk its ``isinstance(..., dict)`` checks. The dance below is just
    to break that wrapper open.
    """
    if raw is None:
        return {}
    if not hasattr(raw, "items"):
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


def _build_chains(s: Dynaconf) -> dict[str, ChainConfig]:
    """Build the typed CHAINS dict from the merged dynaconf settings."""
    raw = s.get("chains")
    return chains_from_config({"chains": _coerce_chains_table(raw)})


def _coerce_templates_table(raw: Any) -> dict[str, dict[str, Any]]:
    """Materialise dynaconf's ``settings.escrow_templates`` into a plain dict.

    Mirror of :func:`_coerce_chains_table`. The values can include nested
    ``literal`` / ``rates`` sub-tables, so recurse one level deep — that's
    enough for the current schema (no four-level nesting).
    """
    if raw is None or not hasattr(raw, "items"):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, sub in raw.items():
        if not isinstance(name, str) or not hasattr(sub, "items"):
            continue
        coerced: dict[str, Any] = {}
        for k, v in sub.items():
            if hasattr(v, "items") and not isinstance(v, dict):
                coerced[k] = {sk: sv for sk, sv in v.items()}
            else:
                coerced[k] = v
        out[name] = coerced
    return out


def _build_escrow_templates(
    s: Dynaconf, chains: dict[str, ChainConfig]
) -> dict[str, EscrowTemplate]:
    """Build the typed ESCROW_TEMPLATES dict from merged dynaconf settings."""
    raw = s.get("escrow_templates")
    return escrow_templates_from_config(
        {"escrow_templates": _coerce_templates_table(raw)},
        chains=chains,
    )


settings: Dynaconf = _build_settings()
CHAINS: dict[str, ChainConfig] = _build_chains(settings)
ESCROW_TEMPLATES: dict[str, EscrowTemplate] = _build_escrow_templates(settings, CHAINS)

if not CHAINS:
    logger.warning(
        "[CONFIG] no [chains.<name>] tables configured — the storefront will "
        "fail when it needs to dispatch any on-chain call. Add at least one "
        "chain entry to storefront.toml."
    )


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
