"""Inference storefront configuration via dynaconf.

Layered (highest priority last):
  1. ``settings.toml`` next to this package — committed defaults.
  2. ``$XDG_CONFIG_HOME/arkhai/storefront.toml`` — an operator's own file.
  3. ``$XDG_CONFIG_HOME/arkhai/storefront.json`` — a chart-rendered document.
  4. ``$XDG_CONFIG_HOME/arkhai/storefront.secrets.toml`` — Secret overlay.
  5. ``INFERENCE_STOREFRONT_*`` environment variables (separator ``__``).

The overlay files are shared with the other storefronts (one per container);
the env prefix differs so colocated local runs can be steered independently.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from arkhai_api_selling.capacity import CapacitySite, read_capacity_sites
from arkhai_api_selling.lifecycle import LoopSettings
from arkhai_api_selling.negotiation import RoundSettings
from arkhai_api_selling.system import SystemSettings
from dynaconf import Dynaconf
from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from market_alkahest import (
    AlkahestSettlementConfig,
    alkahest_address_book,
    retired_address_book_keys,
    retired_address_book_refusal,
    wallet_account_address,
)
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
from market_config.config_loader import (
    ChainConfig,
    chains_from_config,
)
from market_config.registry_url import normalize_registry_url
from market_config.setting_types import positive_seconds
from market_settlement_runtime import compile_settlement_publication_clause
from market_storefront_kit import NegotiationWatchdogPolicy
from market_storefront_kit import configured_time_source as kit_configured_time_source

from inference_storefront.settings_source import settings_source

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "root_agent"


def _build_settings() -> Dynaconf:
    return settings_source()


def seller_wallet_address() -> str:
    """The seller's EVM address: `[wallet].address`, else the account its key
    signs as, so every place naming the seller names one account."""
    return wallet_account_address(
        {
            "address": str(settings.get("wallet.address", "") or ""),
            "private_key": str(settings.get("wallet.private_key", "") or ""),
        }
    )


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


def configured_time_source(source: Dynaconf | None = None) -> Any:
    """The value ``[Time] source`` states, or ``None`` when unset."""
    return kit_configured_time_source(source or settings)


def chain_address_books() -> dict[str, str | None]:
    """Each configured chain's Alkahest address book, by chain name.

    Resolved from `[Settlement.alkahest.address_books]` through the Alkahest
    kit, ``None`` for a chain the table names no book for, which uses the SDK's
    built-in addresses. Raises ``ValueError`` naming each retired address-book
    key the configuration states, since nothing reads those keys.
    """
    try:
        settlement = settlement_config_mapping()
    except ValueError:
        # A [Settlement] that is not a table is refused when it is resolved.
        settlement = {}
    retired = retired_address_book_keys(settlement, settings.get("chains"))
    if retired:
        raise ValueError("; ".join(map(retired_address_book_refusal, retired)))
    raw = settlement.get("alkahest")
    section = (
        AlkahestSettlementConfig.model_validate(raw) if isinstance(raw, dict) else None
    )
    return {name: alkahest_address_book(section, name) for name in CHAINS}


def settlement_publication_defaults(
    source: Dynaconf | None = None,
) -> tuple[Any, ...]:
    """Validate configured inference settlement publication clauses."""
    active = source or settings
    raw = _plain_config_value(active.get("pricing.settlements", []) or [])
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError("pricing.settlements must be a list of complete clauses")
    if not raw:
        return ()
    # Local: the settlement composition imports the container, which imports
    # this module, so a module-level import here is circular.
    from inference_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )
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
    """The inference authority this storefront sells for."""
    return str(settings.get("credits.service_url", "") or "").rstrip("/")


def credits_expected_authorities() -> TrustedIdentitySet | None:
    """The authority principals whose signed responses this storefront accepts.

    ``None`` when unset, which startup refuses. Kept apart from the capacity
    site's authorities: that dynaconf list is merged, so anything appended
    there would silently widen what issuance trusts.
    """
    raw = settings.get("credits.expected_authorities.identities", None)
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        raise RuntimeError(
            "credits.expected_authorities.identities must be a list"
        )
    try:
        return TrustedIdentitySet(
            identities=tuple(Identity.model_validate(v) for v in raw),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "invalid credits.expected_authorities pin"
        ) from exc


def seconds_setting(key: str, default: float, source: Dynaconf | None = None) -> float:
    """A duration setting, refused by key unless positive, finite seconds."""

    active = settings if source is None else source
    try:
        return positive_seconds(active.get(key, default))
    except ValueError as exc:
        reason = str(exc)
    # Raised outside the handler, so the refusal carries no exception context.
    raise ValueError(f"[{key}] {reason}")


def settlement_servicing_interval(source: Dynaconf | None = None) -> float:
    """Seconds between settlement servicing sweeps."""

    return seconds_setting("settlement_servicing_interval_seconds", 30, source)


AGENT_ID: str = _validate_agent_id(settings.get("agent_id", ""))
AGENT_NAME: str = str(settings.get("agent_name") or AGENT_ID)
BASE_URL_OVERRIDE: str = str(settings.get("base_url", "http://localhost:8006"))


def capacity_sites() -> tuple[dict[str, CapacitySite], str]:
    """Each configured capacity site, and the placement."""
    return read_capacity_sites(
        settings.get("capacity.sites"),
        settings.get("capacity.placement", ""),
        sites_key="capacity.sites",
    )


def configured_site_ids() -> tuple[str, ...]:
    return tuple(capacity_sites()[0])


def capacity_poll_interval() -> float:
    """`[capacity].poll_interval` in seconds."""
    return seconds_setting("capacity.poll_interval", 5)


def negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    """The negotiation watchdog's timeout and interval."""
    return NegotiationWatchdogPolicy(
        timeout_seconds=seconds_setting("negotiation_timeout_seconds", 1800),
        interval_seconds=seconds_setting("negotiation_watchdog_interval", 60),
        log_loop_start=False,
        log_cutoff=False,
    )


LOOP_SETTINGS = LoopSettings(
    watchdog=negotiation_watchdog_policy,
    settlement_servicing_interval=settlement_servicing_interval,
    capacity_poll_interval=capacity_poll_interval,
)


def round_settings() -> RoundSettings:
    """What the seller's round reads, once per round."""
    return RoundSettings(
        floor_key="pricing.default_min_price",
        negotiation_config=settings.get("negotiation"),
        chain_config_paths=chain_address_books(),
        default_min_price=settings.get("pricing.default_min_price"),
    )


def system_settings() -> SystemSettings:
    return SystemSettings(
        registry_urls=tuple(settings.registry.urls or ()),
        registry_auth=settings.registry.auth or {},
        authority_url=credits_service_url(),
    )


def seed_settings() -> Any:
    """The ``[seed]`` table as plain data, its ``[seed.model_card]`` the listing's card."""
    seed = settings.get("seed")
    if not isinstance(seed, Mapping):
        return seed
    return _plain_config_value(seed)
