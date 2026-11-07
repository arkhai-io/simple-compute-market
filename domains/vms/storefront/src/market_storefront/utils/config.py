"""Storefront configuration via dynaconf.

Public values come from an operator's ``storefront.toml`` and, under Helm, the
chart-rendered ``storefront.json``; environment-specific secrets come from
``storefront.secrets.toml`` or an approved environment Secret, which win over
both. Marketplace signing material is never loaded into Dynaconf:
``ARKHAI_IDENTITY_CREDENTIAL`` is resolved at the composition root and passed
directly to the identity signer factory.

Wallet and chain tables are EVM-mechanism configuration. Alkahest call sites
read them through the explicit ``get_evm_wallet_*`` helpers only after that mechanism is selected.
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
from market_alkahest import (
    AlkahestSettlementConfig,
    alkahest_address_book,
    retired_address_book_keys,
    retired_address_book_refusal,
    wallet_account_address,
)
from market_config.config_loader import (  # type: ignore[import-not-found]
    ChainConfig,
    chains_from_config,
    storefront_config_files,
)
from market_config.registry_url import normalize_registry_url
from market_config.setting_types import PositiveSeconds, SiteAuthorityUrl
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
from market_settlement_runtime import (
    compile_settlement_publication_clause,
    parse_settlement_publication_clause,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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

def delivery_config_mapping(source: Dynaconf | None = None) -> dict[str, Any] | None:
    """Return the storefront's ``[Delivery]`` section, or None when absent.

    Dynaconf merges top-level keys case-insensitively, so ``[Delivery]`` and
    ``[delivery]`` are the same section.
    """
    active = source or settings
    raw = active.get("delivery")
    if raw is None:
        return None
    value = _detached(raw)
    if not isinstance(value, dict):
        raise ValueError("Delivery must be a table")
    return value


def _detached(value: Any) -> Any:
    """Detach Dynaconf containers keeping key spelling.

    ``[Delivery]`` names its instances both as table keys and as values in
    ``enabled`` and ``origins``; lowercasing only the keys would separate the
    two spellings of one name.
    """
    if hasattr(value, "items"):
        return {str(key): _detached(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_detached(item) for item in value]
    return value


def storefront_domain_registry(
    source: Dynaconf | None = None,
    *,
    installed: Any = None,
):
    """Build the frozen registry from explicit public contribution assertions."""

    from core_storefront.domain_plugins import (
        discover_storefront_domain_registry,
        parse_storefront_contribution_selections,
    )

    active = source or settings
    raw = _plain_config_value(active.get("storefront_domains"))
    selections = parse_storefront_contribution_selections(raw)
    kwargs = {} if installed is None else {"installed": installed}
    return discover_storefront_domain_registry(selections, **kwargs)


def settlement_publication_defaults(
    source: Dynaconf | None = None,
) -> tuple[Any, ...]:
    """Return validated structured publication defaults as complete clauses.

    A clause naming a mechanism whose section is absent or disabled is read in
    full but not compiled against its section, which a disabled mechanism has
    no use for: publication drops it, so the storefront's own configuration
    rules that mechanism out, and a listing it alone priced closes. A clause
    that cannot be read, whatever its mechanism, is refused here.
    """

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
    clauses = []
    for item in raw:
        clause = parse_settlement_publication_clause(item, registry=registry, role="seller")
        section = config.mechanisms.get(registry.registration(clause.mechanism).config_key)
        if section is None or getattr(section, "enabled", False) is not True:
            clauses.append(clause)
            continue
        clauses.append(
            compile_settlement_publication_clause(
                item,
                registry=registry,
                config=config,
                role="seller",
            )
        )
    return tuple(clauses)


def _build_chains(s: Dynaconf) -> dict[str, ChainConfig]:
    """Build the typed CHAINS dict from the merged dynaconf settings."""
    raw = s.get("chains")
    return chains_from_config({"chains": _coerce_chains_table(raw)})


settings: Dynaconf = _build_settings()
CHAINS: dict[str, ChainConfig] = _build_chains(settings)


def chain_address_books() -> dict[str, str | None]:
    """Each configured chain's Alkahest address book, by chain name.

    Resolved from `[Settlement.alkahest.address_books]` through the Alkahest
    kit, ``None`` for a chain the table names no book for, which uses the
    SDK's built-in addresses. The storefront hands this mapping to the
    packages it composes; none of them reads the table itself.

    Raises ``ValueError`` naming each retired address-book key the
    configuration states. Nothing reads those keys, so a command run without
    the server, which refuses them at startup, would otherwise resolve a chain
    the operator gave a book to as using the built-in addresses.
    """
    problems = retired_address_book_problems()
    if problems:
        raise ValueError("; ".join(problems))
    raw = settlement_config_mapping().get("alkahest")
    section = (
        AlkahestSettlementConfig.model_validate(raw) if isinstance(raw, dict) else None
    )
    return {name: alkahest_address_book(section, name) for name in CHAINS}


def retired_address_book_problems(source: Dynaconf | None = None) -> list[str]:
    """Each retired Alkahest address-book key the configuration states, as the
    refusal naming what replaces it."""
    active = settings if source is None else source
    try:
        settlement = settlement_config_mapping(active)
    except ValueError:
        # A [Settlement] that is not a table is reported as unresolvable.
        settlement = {}
    return [
        retired_address_book_refusal(path)
        for path in retired_address_book_keys(settlement, active.get("chains"))
    ]


def chain_address_book(chain_name: str) -> str | None:
    """The Alkahest address book of one chain, as :func:`chain_address_books`."""
    return chain_address_books().get(chain_name)


def get_evm_wallet_address(source: Dynaconf | None = None) -> str:
    """The seller's EVM address: `[Wallet].address`, else the account its key
    signs as, so every place naming the seller names one account."""

    active = settings if source is None else source
    return wallet_account_address(
        {
            "address": str(active.get("wallet.address", "") or ""),
            "private_key": get_evm_wallet_private_key(active),
        }
    )


def get_evm_wallet_private_key(source: Dynaconf | None = None) -> str:
    """Return the explicitly configured EVM mechanism credential, if any."""

    active = settings if source is None else source
    return str(active.get("wallet.private_key", "") or "").strip()


def settlement_servicing_interval(source: Dynaconf | None = None) -> float:
    """Seconds between the settlement servicing sweeps:
    `settlement_servicing_interval_seconds`, thirty unless stated, refused by
    key unless it is a positive, finite number of seconds that can be applied
    to an instant."""

    active = settings if source is None else source
    return _positive_seconds(
        active.get("settlement_servicing_interval_seconds", 30),
        key="settlement_servicing_interval_seconds",
    )


def introduction_retention_sweep_interval(seconds: Any) -> float:
    """The introduction retention sweep's interval,
    `[Settlement.contact].retention_sweep_interval_seconds`, refused by key
    unless it is a positive, finite number of seconds that can be applied to an
    instant."""

    return _positive_seconds(seconds, key="Settlement.contact.retention_sweep_interval_seconds")


_POSITIVE_SECONDS: TypeAdapter[float] = TypeAdapter(PositiveSeconds)
_SITE_AUTHORITY_URL: TypeAdapter[str] = TypeAdapter(SiteAuthorityUrl)


def _validated_setting(adapter: TypeAdapter[Any], value: Any) -> tuple[Any, str | None]:
    """``value`` validated by a shared setting type, and ``None``; or ``None``
    and the reason the type refused it, which names no configured value.

    The caller raises its refusal outside this handler, so the refusal carries
    no exception context: a `ValidationError` keeps the value it refused.
    """

    try:
        return adapter.validate_python(value), None
    except ValidationError as exc:
        return None, "; ".join(
            str(error.get("ctx", {}).get("error", error["msg"])) for error in exc.errors()
        )


def configured_capacity_sites(source: Dynaconf | None = None) -> dict[str, str]:
    """`[capacity.sites]`: each stable site ID and its authority URL, an
    HTTP(S) origin; a URL that is not one is refused under its site's key."""

    active = settings if source is None else source
    raw_sites = active.get("capacity.sites")
    if not raw_sites:
        raise RuntimeError(
            "No capacity site authority configured: [capacity.sites] must map "
            "each stable site ID to an authority URL."
        )
    sites: dict[str, str] = {}
    for raw_name, raw_url in dict(raw_sites).items():
        site_id = str(raw_name).strip()
        if not site_id:
            raise RuntimeError("capacity site IDs must be non-empty")
        url, reason = _validated_setting(_SITE_AUTHORITY_URL, raw_url)
        if reason is not None:
            raise RuntimeError(f"[capacity.sites.{site_id}] {reason}")
        sites[site_id] = url
    return sites


#: The site-projection poller's interval when `[capacity].poll_interval` is unset.
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0

#: How many poll intervals a confirmed generation confirms a listing-source
#: check for, when `[capacity].source_confirmation_seconds` is not stated.
_CONFIRMATION_POLL_INTERVALS = 3


def site_projection_poll_interval(source: Dynaconf | None = None) -> float:
    """`[capacity].poll_interval`: seconds between the projection poller's
    cycles and the capacity-event pollers', five unless stated.

    A stated value that is not a positive, finite number of seconds that can be
    applied to an instant is refused by key rather than defaulted: it also sets
    the default source-confirmation window, which must stay a usable bound.
    """

    active = settings if source is None else source
    stated = active.get("capacity.poll_interval")
    if stated is None:
        return _DEFAULT_POLL_INTERVAL_SECONDS
    return _positive_seconds(stated, key="capacity.poll_interval")


def source_confirmation_seconds(source: Dynaconf | None = None) -> float:
    """How old a site's last confirmed poll may be for a listing-source check
    to rely on it: `[capacity].source_confirmation_seconds`, else three poll
    intervals.

    A cache turns stale only when a poll fails, so while no poll runs -- the
    loops held with trading live, or a poller that has stopped -- a generation
    would stay loaded indefinitely; this window is what bounds how far a
    source check can lag its site. An operator holding the loops restores it by
    stepping `site-projections`.
    """

    active = settings if source is None else source
    stated = active.get("capacity.source_confirmation_seconds")
    if stated is not None:
        return _positive_seconds(stated, key="capacity.source_confirmation_seconds")
    derived = _CONFIRMATION_POLL_INTERVALS * site_projection_poll_interval(active)
    window, reason = _validated_setting(_POSITIVE_SECONDS, derived)
    if reason is not None:
        # The interval is usable, but three of them are not: refused by the
        # interval's key, since no window is stated.
        raise ValueError(
            "[capacity.poll_interval] sets [capacity].source_confirmation_seconds "
            f"when it is not stated, to {_CONFIRMATION_POLL_INTERVALS} poll "
            f"intervals, which {reason}"
        )
    return window


def _positive_seconds(value: Any, *, key: str) -> float:
    """A stated duration, refused by key unless it is a positive, finite number
    of seconds that can be applied to an instant without leaving `datetime`'s
    range."""

    seconds, reason = _validated_setting(_POSITIVE_SECONDS, value)
    if reason is not None:
        raise ValueError(f"[{key}] {reason}")
    return seconds


class AdministratorDeclaration(BaseModel):
    """One ``[Identity.administrators.<subject>]`` entry."""

    model_config = ConfigDict(extra="forbid")

    principals: list[Identity] = Field(default_factory=list)


class ServicePeerDeclaration(BaseModel):
    """One ``[Identity.service_peers.<peer_id>]`` entry."""

    model_config = ConfigDict(extra="forbid")

    role: str = ""
    site_id: str = ""
    principals: list[Identity] = Field(default_factory=list)


class IdentityConfigDeclaration(BaseModel):
    """The public shape of ``[Identity]``, read above through Dynaconf.

    Not used to parse the section at runtime; the parsers above do that and
    use the same identity models for each principal. It declares the keys the
    section may hold, all public, so a chart's generated values schema refuses
    anything else under ``Identity`` — private identity material arrives only
    through ``ARKHAI_IDENTITY_CREDENTIAL``. A key the parsers gain must be
    added here, or the values schema refuses it; see
    docs/development/DEPLOYMENT_AND_CONFIG.md.
    """

    model_config = ConfigDict(extra="forbid")

    principal: IdentityConfig | None = None
    administrators: dict[str, AdministratorDeclaration] = Field(default_factory=dict)
    service_peers: dict[str, ServicePeerDeclaration] = Field(default_factory=dict)


class WalletConfigDeclaration(BaseModel):
    """The public and secret shape of ``[Wallet]``, read above through Dynaconf.

    Not used to parse the section at runtime. It declares which of its keys
    are secret so a chart's generated values schema can keep them out of a
    ConfigMap; see docs/development/DEPLOYMENT_AND_CONFIG.md. The section is
    closed: these are the only keys any reader uses.
    """

    model_config = ConfigDict(extra="forbid")

    address: str = ""
    ssh_public_key: str = ""
    private_key: str = Field(default="", json_schema_extra={"secret": True})


class RegistryConfigDeclaration(BaseModel):
    """The secret part of ``[registry]``, whose other keys stay untyped.

    ``auth`` maps a registry URL to its write token and is read through
    Dynaconf by publication and status. Declared here only so a chart's
    generated values schema refuses it outside the Secret overlay.
    """

    model_config = ConfigDict(extra="allow")

    auth: dict[str, str] = Field(
        default_factory=dict, json_schema_extra={"secret": True}
    )


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
