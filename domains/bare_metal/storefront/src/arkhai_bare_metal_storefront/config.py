"""The bare-metal storefront's configuration, read through its configuration files.

The storefront reads its settings as every storefront does. The packaged
``settings.toml`` supplies each default, then the files under
``$XDG_CONFIG_HOME/arkhai/`` layer over it: ``storefront.toml`` (an operator's
own file), ``storefront.json`` (the public document a chart renders), and the
Secret overlay ``storefront.secrets.toml``, a later file winning on a
conflicting key. Above them sits the loader's environment override layer,
``STOREFRONT_<KEY>`` with ``__`` between nesting levels, the VM storefront's
prefix: the two storefronts never share a process, so one prefix states one
override the same way for either (prefix a value with ``@str`` to keep one
Dynaconf would read as TOML, such as a hex identifier, a string). That layer is
an operator's escape hatch and is never
refused: whether a deployment supplies a value through its environment is a
compliance check of its charts and Compose files, not a decision the storefront
makes at startup. See docs/development/DEPLOYMENT_AND_CONFIG.md.

The signing credential never enters these settings. ``ARKHAI_IDENTITY_CREDENTIAL``
is read by the composition root and handed to the signer factory alone, and the
override layer's prefix does not match it.

Keys are the ones the VM storefront uses for the same concepts. Section and key
names are read in any case, as Dynaconf reads them; the names inside a table
keyed by name (sites, service peers, administrators, chains, registry URLs)
keep their spelling. A key the storefront does not read is ignored, as VM's
loader ignores one, so a release still starts on configuration a newer release
wrote; a chart's generated values schema is what refuses a misspelled key.
"""

from __future__ import annotations

import functools
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from core_storefront.service_peers import ServicePeerConfigs
from dynaconf import Dynaconf
from market_config.config_loader import storefront_config_files
from market_config.registry_url import normalize_registry_url
from market_config.setting_types import PositiveSeconds, positive_seconds
from market_identity import Identity, Signer, TrustedIdentitySet
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

#: The environment override layer's prefix and its nesting separator.
ENVVAR_PREFIX = "STOREFRONT"
ENVVAR_SEPARATOR = "__"
#: The one secret the storefront reads from its environment, outside its settings.
IDENTITY_CREDENTIAL_ENV = "ARKHAI_IDENTITY_CREDENTIAL"

_DEFAULTS_FILE = Path(__file__).with_name("settings.toml")
#: How many poll intervals an unstated source-confirmation window spans.
_CONFIRMATION_POLL_INTERVALS = 3


class BareMetalConfigurationError(ValueError):
    """The storefront's configuration cannot be read, naming each key at fault.

    Its message names keys and reasons, never a configured value, so it is safe
    to report where an operator reads it.
    """


def _principal_keys_in_any_case(value: Any) -> Any:
    # A principal's own keys, `scheme` and `identifier`, are keys like any
    # other: the override layer states them in upper case.
    if isinstance(value, Mapping):
        return {str(key).lower(): item for key, item in value.items()}
    return value


#: A canonical principal, its keys read in any case.
Principal = Annotated[Identity, BeforeValidator(_principal_keys_in_any_case)]


def _lowered(value: Any) -> Any:
    """Every key lowercased, at every depth, as the settlement kit reads its root."""
    if isinstance(value, Mapping):
        return {str(key).lower(): _lowered(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_lowered(item) for item in value]
    return value


def _detached(value: Any) -> Any:
    """Plain mappings and lists in place of Dynaconf's, keeping key spelling."""
    if hasattr(value, "items"):
        return {str(key): _detached(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_detached(item) for item in value]
    return value


class _Section(BaseModel):
    """A typed section: its own keys read in any case, any other key ignored.

    Its JSON Schema is closed nonetheless. The loader ignores a key it does not
    read, so a release still starts on configuration a newer one wrote; the
    chart's values schema, generated from these models, refuses one, so a
    misspelled key is caught where the configuration is written.
    """

    model_config = ConfigDict(
        extra="ignore", frozen=True, json_schema_extra={"additionalProperties": False}
    )

    @model_validator(mode="before")
    @classmethod
    def _keys_in_any_case(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        folded: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).lower()
            if name in folded:
                raise ValueError(f"{key!r} is stated in two spellings")
            folded[name] = item
        return folded


class AdministratorSettings(_Section):
    """One ``[Identity.administrators.<subject>]``: the principals it signs as."""

    principals: list[Principal] = Field(min_length=1, max_length=2)


class ServicePeerSettings(_Section):
    """One ``[Identity.service_peers.<peer>]``: the site it is bound to and its
    principals."""

    role: str
    site_id: str = Field(min_length=1)
    principals: list[Principal] = Field(min_length=1, max_length=2)


class StorefrontIdentitySettings(_Section):
    """``[Identity]``: the storefront's own public principal, its administrators,
    and the service peers its sites are trusted through. Private identity
    material arrives only through ``ARKHAI_IDENTITY_CREDENTIAL``."""

    principal: Principal | None = None
    administrators: dict[str, AdministratorSettings] = Field(default_factory=dict)
    service_peers: dict[str, ServicePeerSettings] = Field(default_factory=dict)


class RegistryAuthoritySettings(_Section):
    """One ``[registry.authorities."<url>"]``: the registry's authority and the
    principals its responses are signed by."""

    authority: str = Field(min_length=1)
    principals: list[Principal] = Field(min_length=1, max_length=2)


class RegistrySettings(_Section):
    """``[registry]``: every registry the storefront publishes to, each pinned."""

    urls: list[str] = Field(default_factory=list)
    authorities: dict[str, RegistryAuthoritySettings] = Field(default_factory=dict)


class CapacitySettings(_Section):
    """``[capacity]``: the sites, how reservations are placed among them, the
    projection poll and publication intervals, and how long a poll's
    confirmation lets the opening recheck confirm a listing."""

    sites: dict[str, str] = Field(default_factory=dict)
    placement: str
    poll_interval: PositiveSeconds
    publication_interval_seconds: PositiveSeconds
    source_confirmation_seconds: PositiveSeconds | None = None

    @model_validator(mode="after")
    def _derived_window_is_usable(self) -> "CapacitySettings":
        # An unstated window is three poll intervals, which can exceed what a
        # timedelta holds although the interval itself does not; unrefused here,
        # the opening recheck would raise at every comparison instead.
        if self.source_confirmation_seconds is not None:
            return self
        try:
            positive_seconds(_CONFIRMATION_POLL_INTERVALS * self.poll_interval)
        except ValueError as exc:
            reason = str(exc)
        else:
            return self
        raise ValueError(
            "poll_interval sets source_confirmation_seconds when it is not "
            f"stated, to {_CONFIRMATION_POLL_INTERVALS} poll intervals, which {reason}"
        )

    @property
    def confirmation_window_seconds(self) -> float:
        """The source-confirmation window: as stated, else three poll intervals."""
        if self.source_confirmation_seconds is not None:
            return self.source_confirmation_seconds
        return _CONFIRMATION_POLL_INTERVALS * self.poll_interval


class PricingSettings(_Section):
    """``[pricing]``: the storefront's publication clauses and default lease bound.

    A pool's override replaces either for that pool; a pool whose maximum lease
    duration resolves to nothing positive from either tier is held at
    publication, so neither is required here.
    """

    settlements: list[dict[str, Any]] = Field(default_factory=list)
    default_max_duration_seconds: StrictInt | None = None

    @field_validator("settlements", mode="before")
    @classmethod
    def _clauses_in_any_case(cls, value: Any) -> Any:
        return _lowered(value)


class NegotiationSettings(_Section):
    """``[negotiation]``: the seller policy chain after the required guards, in
    any form the policy kit normalizes; absent selects the default chain."""

    policies: Any = None


class WalletSettings(_Section):
    """``[Wallet]``: the seller's EVM address, and its key from the Secret overlay."""

    address: str = ""
    private_key: str = Field(default="", repr=False, json_schema_extra={"secret": True})


class ChainSettings(_Section):
    """One ``[Chains.<name>]``: an EVM chain the storefront settles Alkahest on."""

    rpc_url: str = Field(min_length=1)
    chain_id: StrictInt | None = None
    alkahest_address_config_path: str | None = None


class BareMetalStorefrontSettings(_Section):
    """Every setting the bare-metal storefront reads.

    The packaged ``settings.toml`` supplies each scalar default, so a field with
    no default here is one the defaults always state.
    """

    base_url: str = Field(min_length=1)
    db_path: str = Field(min_length=1)
    port: StrictInt = Field(ge=1, le=65535)
    negotiation_timeout_seconds: PositiveSeconds
    negotiation_watchdog_interval: PositiveSeconds
    settlement_servicing_interval_seconds: PositiveSeconds
    payment_reconciliation_interval: PositiveSeconds
    identity: StorefrontIdentitySettings = Field(default_factory=StorefrontIdentitySettings)
    settlement: dict[str, Any] = Field(default_factory=dict)
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    capacity: CapacitySettings
    pricing: PricingSettings = Field(default_factory=PricingSettings)
    negotiation: NegotiationSettings = Field(default_factory=NegotiationSettings)
    # Its sinks' credentials sit here when the overlay states them.
    delivery: dict[str, Any] | None = Field(default=None, repr=False)
    wallet: WalletSettings = Field(default_factory=WalletSettings)
    chains: dict[str, ChainSettings] = Field(default_factory=dict)

    @field_validator("settlement", mode="before")
    @classmethod
    def _settlement_in_any_case(cls, value: Any) -> Any:
        return {} if value is None else _lowered(value)

    @property
    def storefront_url(self) -> str:
        """The storefront's public URL, ``base_url``, without a trailing slash."""
        return self.base_url.rstrip("/")

    def signer(self, credential: bytes | str) -> Signer:
        """The storefront's marketplace signer, from ``[Identity.principal]`` and
        the credential, refused unless the credential owns that principal."""
        principal = self.identity.principal
        if principal is None:
            raise BareMetalConfigurationError(
                "[Identity.principal] is required: the storefront's public principal"
            )
        return resolve_storefront_signer(
            IdentityConfig(scheme=principal.scheme, identifier=principal.identifier),
            credential,
        )

    def administrator_principals(self) -> TrustedIdentitySet:
        """Every principal ``[Identity.administrators]`` names, one or two in all."""
        principals = [
            principal
            for subject in self.identity.administrators.values()
            for principal in subject.principals
        ]
        try:
            return TrustedIdentitySet(identities=tuple(principals))
        except ValidationError:
            raise BareMetalConfigurationError(
                "[Identity.administrators] must name one or two distinct principals "
                "in all"
            ) from None

    def service_peer_configs(self) -> ServicePeerConfigs:
        """Each configured service peer as core's service-peer state reads it:
        its role, its site, and its principals."""
        configs: dict[str, tuple[str, str, TrustedIdentitySet]] = {}
        for peer_id, peer in self.identity.service_peers.items():
            try:
                principals = TrustedIdentitySet(identities=tuple(peer.principals))
            except ValidationError:
                raise BareMetalConfigurationError(
                    f"[Identity.service_peers.{peer_id}].principals must be distinct"
                ) from None
            configs[peer_id] = (peer.role, peer.site_id, principals)
        return configs

    def registry_authorities(self) -> dict[str, RegistryAuthorityTrust]:
        """Each ``[registry].urls`` entry, normalized, with its authority pin.

        The pins must name exactly the configured URLs: a registry without one
        could not be verified, and a pin for no configured registry is a
        mistake to report rather than ignore.
        """
        urls = [normalize_registry_url(url) for url in self.registry.urls]
        if len(set(urls)) != len(urls):
            raise BareMetalConfigurationError(
                "[registry].urls are duplicated after normalization"
            )
        pins: dict[str, RegistryAuthoritySettings] = {}
        for raw_url, pin in self.registry.authorities.items():
            url = normalize_registry_url(raw_url)
            if url in pins:
                raise BareMetalConfigurationError(
                    f"[registry.authorities] pins {url!r} twice"
                )
            pins[url] = pin
        missing = sorted(set(urls) - set(pins))
        unexpected = sorted(set(pins) - set(urls))
        if missing or unexpected:
            raise BareMetalConfigurationError(
                "[registry.authorities] must pin exactly the [registry].urls "
                f"(missing={missing}, unexpected={unexpected})"
            )
        authorities: dict[str, RegistryAuthorityTrust] = {}
        for url in urls:
            pin = pins[url]
            try:
                principals = TrustedIdentitySet(identities=tuple(pin.principals))
            except ValidationError:
                raise BareMetalConfigurationError(
                    f"[registry.authorities.{url!r}].principals must be distinct"
                ) from None
            authorities[url] = RegistryAuthorityTrust(
                authority=pin.authority, principals=principals
            )
        return authorities


def settings_source() -> Dynaconf:
    """The layered settings as Dynaconf merges them, read from disk now.

    Built afresh on each call, so a process or a test reads the files present
    when it asks rather than when this module was imported.
    """
    layers = [str(path) for path in storefront_config_files() if Path(path).exists()]
    return Dynaconf(
        settings_file=[str(_DEFAULTS_FILE)],
        includes=layers,
        envvar_prefix=ENVVAR_PREFIX,
        envvar_separator=ENVVAR_SEPARATOR,
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )


@functools.cache
def packaged_settings() -> BareMetalStorefrontSettings:
    """The settings the packaged ``settings.toml`` states, before any file or the
    override layer: every default in one place, for whatever composes a
    runtime without reading configuration files."""
    with _DEFAULTS_FILE.open("rb") as defaults:
        return _validated(tomllib.load(defaults))


def _error_location(location: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in location) or "configuration"


def load_storefront_settings(source: Dynaconf | None = None) -> BareMetalStorefrontSettings:
    """Read and validate the storefront's settings, naming every key at fault."""
    active = settings_source() if source is None else source
    return _validated(_detached(active.as_dict()))


def _validated(raw: Mapping[str, Any]) -> BareMetalStorefrontSettings:
    raw = {str(key).lower(): value for key, value in raw.items()}
    try:
        return BareMetalStorefrontSettings.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{_error_location(error['loc'])}: {error['msg']}" for error in exc.errors()
        )
    # Raised outside the handler: the ValidationError keeps the values it
    # refused, a wallet key among them, so the refusal carries no context.
    raise BareMetalConfigurationError(
        f"the storefront's configuration cannot be read: {problems}"
    )


def identity_credential(environ: Mapping[str, str] | None = None) -> str:
    """The signing credential, ``ARKHAI_IDENTITY_CREDENTIAL``, kept out of settings."""
    active = os.environ if environ is None else environ
    credential = active.get(IDENTITY_CREDENTIAL_ENV, "")
    if not credential:
        raise BareMetalConfigurationError(f"{IDENTITY_CREDENTIAL_ENV} is required")
    return credential


__all__ = [
    "ENVVAR_PREFIX",
    "IDENTITY_CREDENTIAL_ENV",
    "AdministratorSettings",
    "BareMetalConfigurationError",
    "BareMetalStorefrontSettings",
    "CapacitySettings",
    "ChainSettings",
    "NegotiationSettings",
    "PricingSettings",
    "RegistryAuthoritySettings",
    "RegistrySettings",
    "ServicePeerSettings",
    "StorefrontIdentitySettings",
    "WalletSettings",
    "identity_credential",
    "load_storefront_settings",
    "packaged_settings",
    "settings_source",
]
