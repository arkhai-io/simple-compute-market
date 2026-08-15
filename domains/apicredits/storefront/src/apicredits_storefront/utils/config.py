"""API-credits storefront configuration via dynaconf.

Layered (highest priority last):
  1. ``settings.toml`` next to this package — committed defaults
     documenting every supported key.
  2. ``$XDG_CONFIG_HOME/arkhai/storefront.toml`` — ConfigMap base.
  3. ``$XDG_CONFIG_HOME/arkhai/storefront.secrets.toml`` — Secret overlay.
  4. ``APICREDITS_STOREFRONT_*`` environment variables (separator ``__``).

The overlay files are the same ones the VM storefront reads — one
storefront per container, each with its own mount; the env prefix
differs so colocated local runs can still be steered independently.
"""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
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
        envvar_prefix="APICREDITS_STOREFRONT",
        envvar_separator="__",
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )
    return s


def resolve_evm_wallet() -> tuple[str, str]:
    """Resolve explicit, matching Alkahest mechanism credentials."""
    address = str(settings.get("wallet.address", "") or "")
    private_key = str(settings.get("wallet.private_key", "") or "")
    if not address or not private_key:
        raise RuntimeError(
            "API-credits Alkahest settlement requires wallet.address and "
            "wallet.private_key",
        )
    derived = derive_wallet_address(private_key)
    if not derived or derived.lower() != address.lower():
        raise RuntimeError("configured Alkahest wallet address/private key mismatch")
    return address, private_key


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


def _plain_config_value(value: Any) -> Any:
    """Recursively detach Dynaconf containers from typed configuration."""
    if hasattr(value, "items"):
        return {str(key): _plain_config_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_config_value(item) for item in value]
    return value


def settlement_config_mapping(source: Dynaconf | None = None) -> dict[str, Any]:
    """Return the one canonical settlement table for registry resolution."""
    raw = (source or settings).get("settlement")
    if raw is None:
        return {}
    value = _plain_config_value(raw)
    if not isinstance(value, dict):
        raise ValueError("Settlement must be a table")
    return value


def settlement_publication_defaults(
    source: Dynaconf | None = None,
) -> tuple[Any, ...]:
    """Validate configured API-credit settlement publication clauses."""
    active = source or settings
    raw = _plain_config_value(active.get("pricing.settlements", []) or [])
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("pricing.settlements must be a list of complete clauses")
    if not raw:
        return ()
    from apicredits_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )
    from market_settlement_runtime import compile_settlement_publication_clause

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


settings: Dynaconf = _build_settings()
CHAINS: dict[str, ChainConfig] = chains_from_config(
    {"chains": _coerce_chains_table(settings.get("chains"))},
)

if not CHAINS:
    logger.warning(
        "[CONFIG] no [chains.<name>] tables configured — the storefront "
        "will fail when it needs to dispatch any on-chain call."
    )


def resolve_identity_config() -> IdentityConfig:
    """Load the public marketplace principal without reading its credential."""
    scheme_raw = str(settings.get("identity.scheme", "") or "")
    identifier = str(settings.get("identity.identifier", "") or "")
    if not scheme_raw or not identifier:
        raise RuntimeError(
            "[identity].scheme and [identity].identifier are required",
        )
    try:
        config = IdentityConfig(
            scheme=IdentityScheme(scheme_raw),
            identifier=identifier,
        )
        config.principal
    except (TypeError, ValueError) as exc:
        raise RuntimeError("invalid storefront marketplace identity") from exc
    return config


def resolve_admin_identities() -> TrustedIdentitySet:
    """Load the ordered public principals trusted for admin requests."""
    raw = settings.get("identity.admin_principals.identities")
    if not isinstance(raw, (list, tuple)):
        raise RuntimeError(
            "[identity.admin_principals].identities must contain 1-2 principals",
        )
    try:
        return TrustedIdentitySet(
            identities=tuple(Identity.model_validate(value) for value in raw),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("invalid storefront admin trust set") from exc


def resolve_registry_authorities() -> dict[str, RegistryAuthorityTrust]:
    """Resolve stable registry authorities and signer sets for every URL."""
    from market_config.registry_url import normalize_registry_url

    raw_urls = settings.get("registry.urls")
    urls = list(raw_urls) if raw_urls else []
    if not urls:
        raise RuntimeError("[registry].urls must configure at least one registry")
    raw_trust = settings.get("registry.authorities")
    if not raw_trust or not hasattr(raw_trust, "items"):
        raise RuntimeError("[registry.authorities] authority pins are required")
    resolved: dict[str, RegistryAuthorityTrust] = {}
    for raw_url, raw_principal in dict(raw_trust).items():
        url = normalize_registry_url(str(raw_url))
        if url in resolved:
            raise RuntimeError(f"duplicate registry trust pin for {url!r}")
        try:
            values = dict(raw_principal)
            if set(values) != {"authority", "identities"}:
                raise ValueError("authority entry requires authority and identities")
            authority = values["authority"]
            identities = values["identities"]
            if not isinstance(authority, str) or not authority.strip():
                raise ValueError("authority must be nonempty text")
            if not isinstance(identities, (list, tuple)):
                raise TypeError("identities must be a list")
            resolved[url] = RegistryAuthorityTrust(
                authority=authority.strip(),
                principals=TrustedIdentitySet(
                    identities=tuple(
                        Identity.model_validate(value) for value in identities
                    ),
                ),
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid registry authority trust pin for {url!r}"
            ) from exc
    expected = {normalize_registry_url(str(url)) for url in urls}
    if set(resolved) != expected:
        missing = sorted(expected - set(resolved))
        unexpected = sorted(set(resolved) - expected)
        raise RuntimeError(
            "registry trust pins must exactly match configured URLs "
            f"(missing={missing}, unexpected={unexpected})"
        )
    return resolved


def resolve_identity_signer(
    environ: Mapping[str, str] | None = None,
) -> Signer:
    """Resolve the env-only credential and require its public identity to match."""
    credential = (environ or os.environ).get("ARKHAI_IDENTITY_CREDENTIAL")
    if not credential:
        raise RuntimeError("ARKHAI_IDENTITY_CREDENTIAL is required")
    return resolve_storefront_signer(resolve_identity_config(), credential)


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


def credits_service_url() -> str:
    """The credits service this storefront sells for."""
    return str(settings.get("credits.service_url", "") or "").rstrip("/")


def credits_admin_key() -> str:
    """Resolve one exact credits-service mechanism credential."""
    inline = str(settings.get("credits.admin_key", "") or "")
    file_name = str(settings.get("credits.admin_key_file", "") or "")
    if inline and file_name:
        raise RuntimeError(
            "credits.admin_key and credits.admin_key_file are mutually exclusive"
        )
    if inline:
        return inline
    if not file_name:
        return ""
    path = Path(file_name)
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("credits.admin_key_file must be a regular file")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("credits.admin_key_file cannot be read") from exc
    if not value:
        raise RuntimeError("credits.admin_key_file is empty")
    return value


AGENT_ID: str = _validate_agent_id(settings.get("agent_id", ""))
AGENT_NAME: str = str(settings.get("agent_name") or AGENT_ID)
BASE_URL_OVERRIDE: str = str(settings.get("base_url", "http://localhost:8002"))
