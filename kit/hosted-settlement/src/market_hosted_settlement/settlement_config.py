"""Typed consumer configuration and registration for hosted Stripe settlement."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from hosted_settlement_client import (
    ClientConfig,
    ConditionDescriptor,
    HostedSettlementAsyncClient,
)
from market_identity import Identity, TrustedIdentitySet
from market_settlement_runtime import (
    MechanismReadiness,
    MechanismRegistration,
    ReadinessBlocker,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .adapter import (
    MECHANISM,
    REQUIRED_HOSTED_CAPABILITIES,
    HostedConditionalEscrowClient,
    MarketplaceSignerAdapter,
    adapt_expected_authorities,
)

STRIPE_CONFIG_KEY = "stripe"
REQUIRED_STRIPE_CAPABILITIES = tuple(
    sorted(
        REQUIRED_HOSTED_CAPABILITIES.union(
            {
                "conditional-escrow.v1",
                "stripe-connect-separate-charges-transfers.v1",
                "portable-attestation.v1",
                "eas-arbiter.v1",
            }
        )
    )
)
_API_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_MANIFEST_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_CURRENCY = re.compile(r"^[a-z]{3}$")


class StripeAuthorityTrust(BaseModel):
    """One public authority identity or an overlapping rotation pair."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    principals: tuple[Identity, ...] = Field(min_length=1, max_length=2)

    @field_validator("principals", mode="before")
    @classmethod
    def accept_toml_principal_lists(cls, values: Any) -> Any:
        return tuple(values) if isinstance(values, list) else values

    @model_validator(mode="after")
    def principals_are_unique(self) -> StripeAuthorityTrust:
        if len(set(self.principals)) != len(self.principals):
            raise ValueError("authority principals must be unique")
        return self

    def as_trusted_set(self) -> TrustedIdentitySet:
        return TrustedIdentitySet(identities=self.principals)


class StripeResolverConfig(BaseModel):
    """Public evidence resolver selection; RPC credentials remain chain-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chain_name: str = Field(min_length=1, max_length=128)
    evidence_mode: Literal["eas.v1", "portable-remote.v1"]

    @field_validator("chain_name")
    @classmethod
    def require_trimmed_chain(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("resolver chain_name must be trimmed")
        return value


class StripeSettlementConfig(BaseModel):
    """Strict public hosted-consumer settings with no provider authority secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    base_url: str | None = None
    authority_id: str | None = None
    environment: str | None = None
    authority: StripeAuthorityTrust | None = None
    expected_manifest_digest: str | None = None
    expected_api_version: str = "0.1.0"
    expected_schema_version: int = Field(default=4, ge=1)
    required_capabilities: tuple[str, ...] = REQUIRED_STRIPE_CAPABILITIES
    account_ref: str | None = Field(
        default=None,
        json_schema_extra={"roles": ["seller"]},
    )
    currency: str = Field(
        default="usd",
        json_schema_extra={"roles": ["seller"]},
    )
    condition_profile: str | None = Field(
        default=None,
        json_schema_extra={"roles": ["seller"]},
    )
    condition_profiles: dict[str, ConditionDescriptor] = Field(
        default_factory=dict,
        json_schema_extra={"roles": ["seller"]},
    )
    resolvers: dict[str, StripeResolverConfig] = Field(
        default_factory=dict,
        json_schema_extra={"roles": ["seller"]},
    )
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    preflight_timeout_seconds: float = Field(default=5.0, gt=0)
    allow_insecure_loopback: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip() or value.endswith("/"):
            raise ValueError(
                "base_url must be non-empty, trimmed, and have no trailing slash"
            )
        parsed = urlsplit(value)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("base_url must use HTTPS or an explicit loopback URL")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
        ):
            raise ValueError(
                "base_url must not contain credentials, query, or fragment"
            )
        return value

    @field_validator("authority_id", "environment", "account_ref", "condition_profile")
    @classmethod
    def validate_optional_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or not _TOKEN.fullmatch(value):
            raise ValueError("hosted identifiers must be trimmed public tokens")
        return value

    @field_validator("expected_manifest_digest")
    @classmethod
    def validate_manifest(cls, value: str | None) -> str | None:
        if value is not None and not _MANIFEST_DIGEST.fullmatch(value):
            raise ValueError(
                "expected_manifest_digest must be a lowercase SHA-256 digest"
            )
        return value

    @field_validator("expected_api_version")
    @classmethod
    def validate_api_version(cls, value: str) -> str:
        if not _API_VERSION.fullmatch(value):
            raise ValueError("expected_api_version must be a semantic version")
        return value

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def accept_toml_capability_lists(cls, values: Any) -> Any:
        return tuple(values) if isinstance(values, list) else values

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _TOKEN.fullmatch(value) for value in values):
            raise ValueError("required capabilities must be public tokens")
        if len(set(values)) != len(values):
            raise ValueError("required capabilities must be unique")
        return values

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not _CURRENCY.fullmatch(value):
            raise ValueError("currency must be lowercase ISO 4217")
        return value

    @model_validator(mode="after")
    def validate_cross_field_policy(self) -> StripeSettlementConfig:
        if (
            self.condition_profile is not None
            and self.condition_profile not in self.condition_profiles
        ):
            raise ValueError("condition_profile must name a configured condition")
        if (
            self.base_url is not None
            and urlsplit(self.base_url).scheme == "http"
            and not self.allow_insecure_loopback
        ):
            raise ValueError("HTTP loopback requires allow_insecure_loopback")
        return self


def _blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message)


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _required_config_blockers(
    config: StripeSettlementConfig,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> list[ReadinessBlocker]:
    blockers: list[ReadinessBlocker] = []
    required = (
        (
            "base_url",
            config.base_url,
            "hosted.base_url_missing",
            "a public hosted URL is required",
        ),
        (
            "authority_id",
            config.authority_id,
            "hosted.authority_missing",
            "an authority identifier is required",
        ),
        (
            "environment",
            config.environment,
            "hosted.environment_missing",
            "an authority environment is required",
        ),
        (
            "authority",
            config.authority,
            "hosted.trust_missing",
            "an authority trust pin is required",
        ),
        (
            "expected_manifest_digest",
            config.expected_manifest_digest,
            "hosted.manifest_pin_missing",
            "a hosted manifest digest pin is required",
        ),
        (
            "marketplace_signer",
            resources.get("marketplace_signer") or resources.get("signer"),
            "hosted.signer_missing",
            "an injected marketplace signer is required",
        ),
    )
    for _name, value, code, message in required:
        if value is None or value == "":
            blockers.append(_blocker(code, message))
    if role == "seller":
        if not config.account_ref:
            blockers.append(
                _blocker(
                    "hosted.account_missing", "a seller account reference is required"
                )
            )
        if not config.condition_profile:
            blockers.append(
                _blocker(
                    "hosted.condition_missing", "a seller condition profile is required"
                )
            )
        elif config.condition_profile not in config.condition_profiles:
            blockers.append(
                _blocker(
                    "hosted.condition_unknown",
                    "the seller condition profile is not configured",
                )
            )
    return blockers


def _raw_hosted_client(
    config: StripeSettlementConfig,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> tuple[Any, bool]:
    injected = resources.get("preflight_client")
    if injected is not None:
        return injected, False
    signer = resources.get("marketplace_signer") or resources.get("signer")
    if signer is None or config.authority is None or not config.base_url:
        raise ValueError("hosted client prerequisites are unavailable")
    factory = resources.get("hosted_client_factory", HostedSettlementAsyncClient)
    raw = factory(
        ClientConfig(
            base_url=config.base_url,
            signer=MarketplaceSignerAdapter(signer),
            caller_role="account_owner" if role == "seller" else role,
            authority_id=config.authority_id or "",
            environment=config.environment or "",
            expected_authorities=adapt_expected_authorities(
                config.authority.as_trusted_set()
            ),
            timeout_seconds=config.preflight_timeout_seconds,
            allow_insecure_loopback=config.allow_insecure_loopback,
        )
    )
    return raw, True


async def stripe_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Read signed health/account state without invoking any mutation endpoint."""

    config = StripeSettlementConfig.model_validate(section)
    base_capabilities = tuple(
        sorted(REQUIRED_HOSTED_CAPABILITIES.union(config.required_capabilities))
    )
    if not config.enabled:
        return MechanismReadiness(
            mechanism=MECHANISM,
            configured=True,
            enabled=False,
            ready=False,
            capabilities=base_capabilities,
            contract_version=config.expected_api_version,
            schema_version=str(config.expected_schema_version),
            public_details={},
        )

    blockers = _required_config_blockers(config, resources, role)
    reported_capabilities = base_capabilities
    raw: Any = None
    owned = False
    if not blockers:
        try:
            raw, owned = _raw_hosted_client(config, resources, role)
            preflight_id = uuid.uuid4().hex
            health = await _await_if_needed(
                raw.health(request_id=f"settlement-preflight:health:{preflight_id}")
            )
            reported_capabilities = tuple(
                sorted(str(value) for value in health.capabilities)
            )
            if not health.ready:
                blockers.append(
                    _blocker(
                        "hosted.authority_unready", "the hosted authority is not ready"
                    )
                )
            if health.manifest_digest != config.expected_manifest_digest:
                blockers.append(
                    _blocker(
                        "hosted.manifest_mismatch",
                        "the hosted manifest digest does not match",
                    )
                )
            if health.api_version != config.expected_api_version:
                blockers.append(
                    _blocker(
                        "hosted.api_mismatch", "the hosted API version does not match"
                    )
                )
            if health.schema_version != config.expected_schema_version:
                blockers.append(
                    _blocker(
                        "hosted.schema_mismatch",
                        "the hosted schema version does not match",
                    )
                )
            missing = sorted(set(base_capabilities).difference(health.capabilities))
            if missing:
                blockers.append(
                    _blocker(
                        "hosted.capability_missing",
                        "the hosted authority lacks a required public capability",
                    )
                )
            if role == "seller" and config.account_ref:
                account = await _await_if_needed(
                    raw.account_readiness(
                        config.account_ref,
                        request_id=f"settlement-preflight:account:{preflight_id}",
                    )
                )
                if account.account_ref != config.account_ref or not account.ready:
                    blockers.append(
                        _blocker(
                            "hosted.account_unready",
                            "the hosted seller account is not ready",
                        )
                    )
                elif "transfers" not in account.capabilities:
                    blockers.append(
                        _blocker(
                            "hosted.account_capability_missing",
                            "the hosted seller account cannot receive transfers",
                        )
                    )
        except Exception:
            blockers.append(
                _blocker(
                    "hosted.preflight_failed",
                    "the signed hosted readiness contract could not be verified",
                )
            )
        finally:
            if owned and raw is not None and callable(getattr(raw, "aclose", None)):
                try:
                    await _await_if_needed(raw.aclose())
                except Exception:
                    pass

    details: dict[str, Any] = {}
    if config.environment is not None:
        details["environment"] = config.environment
    if role == "seller":
        details["currency"] = config.currency
    if role == "seller" and config.condition_profile is not None:
        details["condition_profile"] = config.condition_profile
    return MechanismReadiness(
        mechanism=MECHANISM,
        configured=True,
        enabled=True,
        ready=not blockers,
        blockers=tuple(blockers),
        capabilities=reported_capabilities,
        contract_version=config.expected_api_version,
        schema_version=str(config.expected_schema_version),
        public_details=details,
    )


def stripe_client_factory(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> HostedConditionalEscrowClient:
    """Build the exact released hosted client wrapped by the runtime adapter."""

    config = StripeSettlementConfig.model_validate(section)
    injected = resources.get("hosted_client")
    if isinstance(injected, HostedConditionalEscrowClient):
        return injected
    if injected is not None:
        return HostedConditionalEscrowClient(injected)
    signer = resources.get("marketplace_signer") or resources.get("signer")
    if signer is None or config.authority is None or not config.base_url:
        raise ValueError("hosted client construction requires URL, trust, and signer")
    factory = resources.get("hosted_client_factory", HostedSettlementAsyncClient)
    raw = factory(
        ClientConfig(
            base_url=config.base_url,
            signer=MarketplaceSignerAdapter(signer),
            caller_role="storefront" if role == "seller" else role,
            authority_id=config.authority_id or "",
            environment=config.environment or "",
            expected_authorities=adapt_expected_authorities(
                config.authority.as_trusted_set()
            ),
            timeout_seconds=config.request_timeout_seconds,
            allow_insecure_loopback=config.allow_insecure_loopback,
        )
    )
    return HostedConditionalEscrowClient(raw)


def _principal_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("hosted option requires a claimant principal")


def stripe_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build one deterministic hosted SettlementOption wire mapping."""

    if role != "seller":
        raise ValueError("hosted listing options are seller-owned")
    config = StripeSettlementConfig.model_validate(section)
    if not config.enabled or not readiness.ready:
        raise ValueError("hosted settlement is not ready for publication")
    account_ref = resources.get("account_ref") or config.account_ref
    currency = resources.get("currency") or config.currency
    profile_name = resources.get("condition_profile") or config.condition_profile
    condition = config.condition_profiles.get(profile_name or "")
    claimant = resources.get("claimant_principal")
    rate = resources.get("rate_minor_units")
    if not isinstance(account_ref, str) or not account_ref:
        raise ValueError("hosted option requires an account reference")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ValueError("hosted option requires a lowercase ISO 4217 currency")
    if condition is None:
        raise ValueError("hosted option requires a configured condition profile")
    if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
        raise ValueError("hosted option requires a positive integer minor-unit rate")
    rates = [{"field": "amount", "per": "hour", "value": str(rate)}]
    params = {
        "account_ref": account_ref,
        "claimant_principal": _principal_json(claimant),
        "funds_flow": "separate_charges_transfers",
        "payment_method_types": ["card"],
        "condition": condition.model_dump(mode="json"),
    }
    identity_payload = {
        "mechanism": MECHANISM,
        "asset": currency,
        "rates": rates,
        "params": params,
    }
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    option = {
        "option_id": hashlib.sha256(encoded).hexdigest(),
        **identity_payload,
    }
    return {"accepted_escrows": [], "settlement_options": [option]}


def stripe_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    config = StripeSettlementConfig.model_validate(section)
    if not config.enabled or _value(option, "mechanism") != MECHANISM:
        return False
    currency = _value(option, "asset")
    accepted = public_context.get("currencies")
    return (
        not isinstance(accepted, (set, frozenset, tuple, list)) or currency in accepted
    )


def create_stripe_registration() -> MechanismRegistration:
    """Return the explicit common-contract registration for hosted Stripe."""

    return MechanismRegistration(
        mechanism_id=MECHANISM,
        config_key=STRIPE_CONFIG_KEY,
        config_model=StripeSettlementConfig,
        roles=frozenset({"buyer", "seller"}),
        preflight=stripe_preflight,
        client_factory=stripe_client_factory,
        option_builder=stripe_option_builder,
        buyer_compatibility=stripe_buyer_compatibility,
        public_detail_keys=frozenset({"currency", "environment", "condition_profile"}),
    )


__all__ = [
    "REQUIRED_STRIPE_CAPABILITIES",
    "STRIPE_CONFIG_KEY",
    "StripeAuthorityTrust",
    "StripeResolverConfig",
    "StripeSettlementConfig",
    "create_stripe_registration",
    "stripe_buyer_compatibility",
    "stripe_client_factory",
    "stripe_option_builder",
    "stripe_preflight",
]
