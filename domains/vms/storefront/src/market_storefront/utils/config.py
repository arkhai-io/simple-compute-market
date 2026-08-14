"""Storefront configuration via dynaconf.

Public profile values come from ``storefront.toml`` and environment-specific
secrets come from ``storefront.secrets.toml`` or an approved environment
Secret. Marketplace signing material is never loaded into Dynaconf:
``ARKHAI_IDENTITY_CREDENTIAL`` is resolved at the composition root and passed
directly to the identity signer factory.

Wallet and chain tables are optional EVM-mechanism configuration. Hosted-only
storefronts leave them absent; Alkahest call sites read them through the
explicit ``get_evm_wallet_*`` helpers only after that mechanism is selected.
"""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path
from typing import Any

from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from dynaconf import Dynaconf
from market_config.config_loader import (  # type: ignore[import-not-found]
    ChainConfig,
    EscrowTemplate,
    chains_from_config,
    escrow_templates_from_config,
    storefront_config_files,
)
from market_config.registry_url import normalize_registry_url
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet

from .zerotier import BaseUrlResolutionError, resolve_base_url_best_effort

logger = logging.getLogger(__name__)


DEFAULT_AGENT_ID = "root_agent"
IDENTITY_CREDENTIAL_ENV = "ARKHAI_IDENTITY_CREDENTIAL"
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
            out[name] = dict(sub.items())
        elif isinstance(sub, dict):
            out[name] = sub
    return out


def _plain_config_value(value: Any) -> Any:
    """Recursively detach Dynaconf containers from typed configuration input."""
    if hasattr(value, "items"):
        return {
            str(key).lower(): _plain_config_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_config_value(item) for item in value]
    return value


def settlement_config_mapping(source: Dynaconf | None = None) -> dict[str, Any]:
    """Return the one canonical settlement table for registry resolution."""
    active = source or settings
    raw = active.get("settlement")
    if raw is None:
        return {}
    value = _plain_config_value(raw)
    if not isinstance(value, dict):
        raise ValueError("Settlement must be a table")
    return value


def settlement_publication_defaults(
    source: Dynaconf | None = None,
) -> tuple[Any, ...]:
    """Return validated structured publication defaults as complete clauses."""

    from market_settlement_runtime import compile_settlement_publication_clause

    from market_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )

    active = source or settings
    raw = _plain_config_value(active.get("pricing.settlements", []) or [])
    if not isinstance(raw, list):
        raise ValueError("pricing.settlements must be a list of complete clauses")
    if not raw:
        return ()
    if any(not isinstance(item, dict) for item in raw):
        raise ValueError("each pricing.settlements entry must be a table")

    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(active), role="seller")
    return tuple(
        compile_settlement_publication_clause(
            item,
            registry=registry,
            config=config,
            role="seller",
        )
        for item in raw
    )


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
                coerced[k] = dict(v.items())
            else:
                coerced[k] = v
        out[name] = coerced
    return out


def _build_escrow_templates(
    s: Dynaconf, chains: dict[str, ChainConfig]
) -> dict[str, EscrowTemplate]:
    """Build the typed templates with the installed Alkahest address resolver."""
    raw = s.get("escrow_templates")
    settlement = _plain_config_value(s.get("settlement") or {})
    alkahest = settlement.get("alkahest", {}) if isinstance(settlement, dict) else {}
    address_config_path = (
        alkahest.get("address_config_path") if isinstance(alkahest, dict) else None
    )

    def resolve_address(key: str, chain: ChainConfig) -> str:
        from market_alkahest import alkahest as alkahest_module

        resolver = getattr(alkahest_module, f"get_{key}", None)
        if not callable(resolver):
            raise ValueError(f"unknown Alkahest address key {key!r}")
        return str(
            resolver(
                chain.name,
                config_path=address_config_path,
            )
        )

    return escrow_templates_from_config(
        {"escrow_templates": _coerce_templates_table(raw)},
        chains=chains,
        address_resolver=resolve_address,
    )


settings: Dynaconf = _build_settings()
CHAINS: dict[str, ChainConfig] = _build_chains(settings)
ESCROW_TEMPLATES: dict[str, EscrowTemplate] = _build_escrow_templates(settings, CHAINS)


def get_evm_wallet_address(source: Dynaconf | None = None) -> str:
    """Return the explicitly configured EVM mechanism address, if any."""

    active = settings if source is None else source
    return str(active.get("wallet.address", "") or "").strip()


def get_evm_wallet_private_key(source: Dynaconf | None = None) -> str:
    """Return the explicitly configured EVM mechanism credential, if any."""

    active = settings if source is None else source
    return str(active.get("wallet.private_key", "") or "").strip()


def _trusted_identity_set(raw: Any, *, field: str) -> TrustedIdentitySet:
    """Parse one ordered old/new authority overlap from public config."""
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{field}.principals must be a list")
    try:
        identities = tuple(Identity.model_validate(value) for value in raw)
        return TrustedIdentitySet(identities=identities)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field}.principals must contain 1-2 unique identities"
        ) from exc


def get_administrator_configs(
    source: Dynaconf | None = None,
) -> dict[str, TrustedIdentitySet]:
    """Resolve stable administrator subjects and bounded rotation trust sets."""

    active = settings if source is None else source
    raw = active.get("identity.administrators", {}) or {}
    if not hasattr(raw, "items"):
        raise ValueError("identity.administrators must be a mapping")
    administrators: dict[str, TrustedIdentitySet] = {}
    for subject, value in raw.items():
        if not hasattr(value, "get"):
            raise ValueError(f"identity.administrators.{subject} must be a mapping")
        administrators[str(subject)] = _trusted_identity_set(
            value.get("principals"),
            field=f"identity.administrators.{subject}",
        )
    return administrators


def get_registry_authorities(
    source: Dynaconf | None = None,
) -> dict[str, RegistryAuthorityTrust]:
    """Resolve stable authority names and old/new signer pins per registry."""

    active = settings if source is None else source
    urls = [str(url) for url in (active.get("registry.urls") or [])]
    raw = active.get("registry.authorities") or {}
    authorities: dict[str, RegistryAuthorityTrust] = {}
    for raw_url, authority_raw in dict(raw).items():
        url = normalize_registry_url(str(raw_url))
        if url in authorities:
            raise ValueError(f"duplicate registry authority pin for {url!r}")
        value = dict(authority_raw)
        authority = str(value.get("authority") or "").strip()
        if not authority:
            raise ValueError(
                f"registry.authorities.{raw_url}.authority must be non-empty"
            )
        authorities[url] = RegistryAuthorityTrust(
            authority=authority,
            principals=_trusted_identity_set(
                value.get("principals"),
                field=f"registry.authorities.{raw_url}",
            ),
        )
    normalized_urls = [normalize_registry_url(url) for url in urls]
    if len(normalized_urls) != len(set(normalized_urls)):
        raise ValueError("configured registry URLs are duplicated after normalization")
    if set(authorities) != set(normalized_urls):
        missing = sorted(set(normalized_urls) - set(authorities))
        unexpected = sorted(set(authorities) - set(normalized_urls))
        raise ValueError(
            "registry authority pins must exactly match registry.urls "
            f"(missing={missing}, unexpected={unexpected})"
        )
    return authorities


def get_provisioning_authorities(
    source: Dynaconf | None = None,
) -> TrustedIdentitySet:
    """Return the ordered public trust pins for the provisioning service."""

    active = settings if source is None else source
    return _trusted_identity_set(
        active.get("provisioning.identity.principals"),
        field="provisioning.identity",
    )


def get_service_peer_configs(
    source: Dynaconf | None = None,
) -> dict[str, tuple[str, str, TrustedIdentitySet]]:
    """Resolve peer role/site bindings and bounded principal rotation sets."""

    active = settings if source is None else source
    raw = active.get("identity.service_peers", {}) or {}
    if not hasattr(raw, "items"):
        raise ValueError("identity.service_peers must be a mapping")
    peers: dict[str, tuple[str, str, TrustedIdentitySet]] = {}
    for peer_id, value in raw.items():
        if not hasattr(value, "get"):
            raise ValueError(f"identity.service_peers.{peer_id} must be a mapping")
        role = str(value.get("role", "") or "").strip()
        site_id = str(value.get("site_id", "") or "").strip()
        if role != "service" or not site_id:
            raise ValueError(
                f"identity.service_peers.{peer_id} requires role='service' and site_id"
            )
        principals = _trusted_identity_set(
            value.get("principals"),
            field=f"identity.service_peers.{peer_id}",
        )
        peers[str(peer_id)] = (role, site_id, principals)
    return peers


def get_identity_config(source: Dynaconf | None = None) -> IdentityConfig:
    """Resolve the current public marketplace principal without its credential."""

    active = settings if source is None else source
    principal_raw = active.get("identity.principal") or {}
    if hasattr(principal_raw, "to_dict"):
        principal_raw = principal_raw.to_dict()
    try:
        principal = Identity.model_validate(principal_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "identity.principal is required and must be canonical"
        ) from exc
    return IdentityConfig(
        scheme=IdentityScheme(principal.scheme),
        identifier=principal.identifier,
    )


def resolve_marketplace_signer(
    source: Dynaconf | None = None,
    *,
    credential: bytes | str | None = None,
) -> Signer:
    """Build the configured signer from the dedicated Secret boundary."""

    secret = (
        os.environ.get(IDENTITY_CREDENTIAL_ENV) if credential is None else credential
    )
    if secret is None or secret == "" or secret == b"":
        raise ValueError(f"{IDENTITY_CREDENTIAL_ENV} is required")
    return resolve_storefront_signer(get_identity_config(source), secret)


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
            stacklevel=2,
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
                "[CONFIG] base_url resolved to %s (network=%s)",
                resolved,
                zerotier,
            )
        return resolved
    except BaseUrlResolutionError as exc:
        logger.warning("[CONFIG] base_url is invalid (%s); using raw value", exc)
        return raw


AGENT_ID: str = get_agent_id()
AGENT_NAME: str = str(settings.get("agent_name") or AGENT_ID)
BASE_URL_OVERRIDE: str = _resolve_base_url()
