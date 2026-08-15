"""Typed consumer configuration and registration for hosted Stripe settlement."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from hosted_settlement_client import (
    ClientConfig,
    ConditionDescriptor,
    FundingMode,
    FundingProfile,
    HostedSettlementAsyncClient,
)
from market_identity import Identity, TrustedIdentitySet
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    QueryValueType,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementRole,
    SettlementPublicationClause,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .automation import OffSessionPolicy
from .adapter import (
    MECHANISM,
    REQUIRED_HOSTED_CAPABILITIES,
    HostedConditionalEscrowClient,
    MarketplaceSignerAdapter,
    adapt_expected_authorities,
)

STRIPE_CONFIG_KEY = "stripe"
SUPPORTED_FUNDING_PROFILES = (
    FundingProfile.CARD,
    FundingProfile.US_BANK_TRANSFER,
    FundingProfile.US_ACH_DEBIT,
)
_PROFILE_CAPABILITIES = {
    FundingProfile.CARD: "funding-profile.card.v1",
    FundingProfile.US_BANK_TRANSFER: "funding-profile.us_bank_transfer.v1",
    FundingProfile.US_ACH_DEBIT: "funding-profile.us_ach_debit.v1",
}
_PROFILE_INTERACTIONS = {
    FundingProfile.CARD: (FundingMode.INTERACTIVE, FundingMode.SAVED_INSTRUMENT),
    FundingProfile.US_BANK_TRANSFER: (FundingMode.INTERACTIVE,),
    FundingProfile.US_ACH_DEBIT: (
        FundingMode.INTERACTIVE,
        FundingMode.SAVED_INSTRUMENT,
    ),
}
REQUIRED_STRIPE_CAPABILITIES = tuple(
    sorted(
        REQUIRED_HOSTED_CAPABILITIES.union(
            {
                "conditional-escrow.v2",
                "stripe-connect-separate-charges-transfers.v2",
                "payer-profile.v1",
                "funding-authorization.v1",
                "funding-profile.card.v1",
                "funding-profile.us_bank_transfer.v1",
                "funding-profile.us_ach_debit.v1",
                "normalized-funding-reversal.v1",
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
_CLAUSE_OPERATORS = frozenset(
    {
        ComparisonOperator.EQUAL,
        ComparisonOperator.NOT_EQUAL,
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
)

_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)
_THREE_DECIMAL_CURRENCIES = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})


class StripePublicationInput(BaseModel):
    """Exact provider-neutral funding input for one ordered publication clause."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    interaction: Annotated[FundingMode, Field(strict=False)]
    funds_flow: Literal["separate_charges_transfers"] = "separate_charges_transfers"

    @model_validator(mode="after")
    def validate_profile_interaction(self) -> StripePublicationInput:
        if self.interaction not in _PROFILE_INTERACTIONS[self.funding_profile]:
            raise ValueError(
                f"{self.funding_profile.value} does not support "
                f"{self.interaction.value}"
            )
        return self


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
    expected_api_version: Literal["0.2.1"] = "0.2.1"
    expected_schema_version: Literal[5] = 5
    required_capabilities: tuple[str, ...] = REQUIRED_STRIPE_CAPABILITIES
    account_ref: str | None = Field(
        default=None,
        json_schema_extra={"roles": ["seller"]},
    )
    currency: Literal["usd"] = Field(
        default="usd",
        json_schema_extra={"roles": ["seller"]},
    )
    country: Literal["US"] = Field(
        default="US",
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
    off_session_policy: OffSessionPolicy = Field(
        default_factory=OffSessionPolicy,
        repr=False,
        json_schema_extra={"roles": ["buyer"]},
    )
    authorization_journal_path: str | None = Field(
        default=None,
        repr=False,
        json_schema_extra={"roles": ["buyer"]},
    )

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

    @field_validator("authorization_journal_path")
    @classmethod
    def validate_authorization_journal_path(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            raise ValueError("authorization_journal_path must be absolute")
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

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def accept_toml_capability_lists(cls, values: Any) -> Any:
        return tuple(values) if isinstance(values, list) else values

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("required capabilities must be unique")
        if set(values) != set(REQUIRED_STRIPE_CAPABILITIES):
            raise ValueError(
                "required capabilities must exactly match the released "
                "hosted consumer contract"
            )
        return tuple(sorted(values))

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
        if self.off_session_policy.enabled:
            if self.off_session_policy.authority_id != self.authority_id:
                raise ValueError(
                    "off-session policy authority must match hosted authority"
                )
            if self.off_session_policy.environment != self.environment:
                raise ValueError(
                    "off-session policy environment must match hosted environment"
                )
            if self.off_session_policy.currency != self.currency:
                raise ValueError(
                    "off-session policy currency must match hosted currency"
                )
            if (
                self.off_session_policy.funding_profile
                is FundingProfile.US_BANK_TRANSFER
            ):
                raise ValueError(
                    "off-session policy does not support push bank transfer"
                )
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


def stripe_contract_fingerprint(config: StripeSettlementConfig) -> str:
    """Bind advertised options to the exact consumer release contract."""

    payload = {
        "manifest_digest": config.expected_manifest_digest,
        "api_version": config.expected_api_version,
        "schema_version": config.expected_schema_version,
        "capabilities": list(config.required_capabilities),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _profile_records(source: Any) -> dict[FundingProfile, Any]:
    raw_records = _value(source, "funding_profiles", ())
    if not isinstance(raw_records, (tuple, list)):
        raise ValueError("hosted funding profile readiness must be a sequence")
    records: dict[FundingProfile, Any] = {}
    for item in raw_records:
        try:
            profile = FundingProfile(_value(item, "profile"))
        except (TypeError, ValueError):
            raise ValueError(
                "hosted funding profile readiness contains an invalid profile"
            ) from None
        if profile in records:
            raise ValueError(
                "hosted funding profile readiness contains a duplicate profile"
            )
        records[profile] = item
    return records


def _configured_interactions(
    resources: Mapping[str, Any],
) -> dict[FundingProfile, tuple[FundingMode, ...]]:
    configured: dict[FundingProfile, list[FundingMode]] = {}
    raw_clauses = resources.get("publication_clauses")
    if not isinstance(raw_clauses, Sequence) or isinstance(raw_clauses, (str, bytes)):
        return dict(_PROFILE_INTERACTIONS)
    for raw_clause in raw_clauses:
        clause = SettlementPublicationClause.model_validate(raw_clause)
        if clause.mechanism != MECHANISM:
            continue
        publication = StripePublicationInput.model_validate(clause.mechanism_input)
        interactions = configured.setdefault(publication.funding_profile, [])
        if publication.interaction not in interactions:
            interactions.append(publication.interaction)
    return {
        profile: tuple(interactions)
        for profile, interactions in configured.items()
    }


def _profile_blocker(code: str, message: str) -> dict[str, str]:
    return _blocker(code, message).model_dump(mode="json")


async def stripe_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Read exact signed release and profile readiness without mutation."""

    config = StripeSettlementConfig.model_validate(section)
    base_capabilities = config.required_capabilities
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
    configured = _configured_interactions(resources)
    profile_blockers: dict[FundingProfile, list[dict[str, str]]] = {
        profile: [] for profile in configured
    }
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
            health_profiles = _profile_records(health)
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
            if (
                _value(health, "payer_profile_protocol")
                != "arkhai.payer-profile.v1"
                or _value(health, "funding_authorization_protocol")
                != "arkhai.funding-authorization.v1"
                or _value(health, "funding_profile_protocol")
                != "arkhai.funding-profile.v1"
            ):
                blockers.append(
                    _blocker(
                        "hosted.contract_mismatch",
                        "the hosted payer and funding contract does not match",
                    )
                )
            profile_capabilities = set(_PROFILE_CAPABILITIES.values())
            missing_common = sorted(
                set(base_capabilities)
                .difference(profile_capabilities)
                .difference(health.capabilities)
            )
            if missing_common:
                blockers.append(
                    _blocker(
                        "hosted.capability_missing",
                        "the hosted authority lacks a required public capability",
                    )
                )
            for profile in configured:
                profile_health = health_profiles.get(profile)
                if _PROFILE_CAPABILITIES[profile] not in health.capabilities:
                    profile_blockers[profile].append(
                        _profile_blocker(
                            "hosted.profile_capability_missing",
                            "the hosted authority lacks the exact funding profile capability",
                        )
                    )
                if profile_health is None or not bool(
                    _value(profile_health, "ready", False)
                ):
                    profile_blockers[profile].append(
                        _profile_blocker(
                            "hosted.profile_unready",
                            "the hosted funding profile is not ready",
                        )
                    )
            if role == "seller" and config.account_ref:
                account = await _await_if_needed(
                    raw.account_readiness(
                        config.account_ref,
                        request_id=f"settlement-preflight:account:{preflight_id}",
                    )
                )
                account_profiles = _profile_records(account)
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
                for profile in configured:
                    profile_account = account_profiles.get(profile)
                    if profile_account is None or not bool(
                        _value(profile_account, "ready", False)
                    ):
                        profile_blockers[profile].append(
                            _profile_blocker(
                                "hosted.account_profile_unready",
                                "the seller account is not ready for the funding profile",
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

    profiles: dict[str, Any] = {}
    any_profile_ready = False
    for profile in SUPPORTED_FUNDING_PROFILES:
        if profile not in configured:
            continue
        ready = not blockers and not profile_blockers[profile]
        any_profile_ready = any_profile_ready or ready
        profiles[profile.value] = {
            "ready": ready,
            "blockers": profile_blockers[profile],
            "interactions": sorted(
                interaction.value for interaction in configured[profile]
            ),
            "currency": config.currency,
            "country": config.country,
        }
    if not blockers and not any_profile_ready:
        blockers.append(
            _blocker(
                "hosted.profiles_unready",
                "no configured hosted funding profile is ready",
            )
        )
    details: dict[str, Any] = {
        "contract_fingerprint": stripe_contract_fingerprint(config),
        "profiles": profiles,
    }
    if config.environment is not None:
        details["environment"] = config.environment
    if role == "seller":
        details["currency"] = config.currency
        details["country"] = config.country
    if role == "seller" and config.condition_profile is not None:
        details["condition_profile"] = config.condition_profile
    return MechanismReadiness(
        mechanism=MECHANISM,
        configured=True,
        enabled=True,
        ready=not blockers and any_profile_ready,
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


def _stripe_rate_minor_units(
    clause: SettlementPublicationClause,
    *,
    configured_currency: str | None,
) -> int:
    if clause.asset != configured_currency:
        raise ValueError(
            f"hosted asset {clause.asset!r} does not match configured "
            f"currency {configured_currency!r}"
        )
    if clause.rate is None:
        raise ValueError("hosted publication requires a rate")
    exponent = (
        0
        if clause.asset in _ZERO_DECIMAL_CURRENCIES
        else 3
        if clause.asset in _THREE_DECIMAL_CURRENCIES
        else 2
    )
    try:
        human = Decimal(clause.rate)
    except InvalidOperation as exc:
        raise ValueError(f"invalid hosted rate {clause.rate!r}") from exc
    scaled = human * (Decimal(10) ** exponent)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"hosted rate {clause.rate!r} has more than {exponent} decimal places"
        )
    if scaled <= 0:
        raise ValueError("hosted rate must be positive")
    return int(scaled)


def stripe_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build one deterministic option for one exact ready funding clause."""

    if role != "seller":
        raise ValueError("hosted listing options are seller-owned")
    config = StripeSettlementConfig.model_validate(section)
    if not config.enabled or not readiness.ready:
        return {"accepted_escrows": [], "settlement_options": []}
    raw_clause = resources.get("publication_clause")
    if raw_clause is None:
        raise ValueError("hosted publication requires one ordered exact clause")
    clause = SettlementPublicationClause.model_validate(raw_clause)
    if clause.mechanism != MECHANISM:
        raise ValueError("publication clause does not select hosted settlement")
    publication_input = StripePublicationInput.model_validate(clause.mechanism_input)
    profiles = readiness.public_details.get("profiles")
    profile_status = (
        profiles.get(publication_input.funding_profile.value)
        if isinstance(profiles, Mapping)
        else None
    )
    if not isinstance(profile_status, Mapping) or profile_status.get("ready") is not True:
        return {"accepted_escrows": [], "settlement_options": []}
    expected_fingerprint = stripe_contract_fingerprint(config)
    if readiness.public_details.get("contract_fingerprint") != expected_fingerprint:
        return {"accepted_escrows": [], "settlement_options": []}

    rate = _stripe_rate_minor_units(clause, configured_currency=config.currency)
    account_ref = resources.get("account_ref") or config.account_ref
    condition = config.condition_profiles.get(config.condition_profile or "")
    claimant = resources.get("claimant_principal")
    if not isinstance(account_ref, str) or not account_ref:
        raise ValueError("hosted option requires an account reference")
    if condition is None:
        raise ValueError("hosted option requires a configured condition profile")
    rates = [{"field": "amount", "per": clause.per, "value": str(rate)}]
    params = {
        "authority_id": config.authority_id,
        "account_ref": account_ref,
        "country": config.country,
        "environment": config.environment,
        "claimant_principal": _principal_json(claimant),
        "funds_flow": publication_input.funds_flow,
        "funding_profile": publication_input.funding_profile.value,
        "interaction": publication_input.interaction.value,
        "contract_fingerprint": expected_fingerprint,
        "condition": condition.model_dump(mode="json"),
    }
    identity_payload = {
        "mechanism": MECHANISM,
        "asset": clause.asset,
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


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _contains_exact(values: Any, expected: str) -> bool:
    return (
        isinstance(values, (set, frozenset, tuple, list))
        and expected in {_enum_value(value) for value in values}
    )


def stripe_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    """Admit only exact options owned by the selected active local payer."""

    config = StripeSettlementConfig.model_validate(section)
    if not config.enabled or _value(option, "mechanism") != MECHANISM:
        return False
    params = _value(option, "params", {})
    if not isinstance(params, Mapping):
        return False
    try:
        profile = FundingProfile(_value(params, "funding_profile"))
        interaction = FundingMode(_value(params, "interaction"))
    except (TypeError, ValueError):
        return False
    if (
        _value(params, "authority_id") != config.authority_id
        or _value(params, "environment") != config.environment
        or _value(params, "country") != config.country
    ):
        return False
    if interaction not in _PROFILE_INTERACTIONS[profile]:
        return False
    expected_fingerprint = stripe_contract_fingerprint(config)
    advertised_fingerprint = _value(params, "contract_fingerprint")
    context_fingerprint = public_context.get("contract_fingerprint")
    if advertised_fingerprint != expected_fingerprint or (
        context_fingerprint is not None
        and context_fingerprint != expected_fingerprint
    ):
        return False
    currency = _value(option, "asset")
    if (
        currency != config.currency
        or not _contains_exact(public_context.get("funding_profiles"), profile.value)
        or not _contains_exact(public_context.get("currencies"), config.currency)
        or not _contains_exact(public_context.get("countries"), config.country)
        or not _contains_exact(
            public_context.get("interactions"), interaction.value
        )
    ):
        return False

    binding = public_context.get("selected_payer_binding")
    selected_principal = public_context.get("selected_principal")
    if binding is None or selected_principal is None:
        return False
    if (
        _value(binding, "authority_id") != config.authority_id
        or _value(binding, "environment") != config.environment
        or _enum_value(_value(binding, "state")) != "active"
        or not isinstance(_value(binding, "binding_ref"), str)
    ):
        return False
    try:
        bound = Identity.model_validate(_value(binding, "bound_principal"))
        selected = Identity.model_validate(selected_principal)
    except (TypeError, ValueError):
        return False
    if bound != selected:
        return False

    readiness = public_context.get("profile_readiness")
    profile_readiness = (
        readiness.get(profile.value) if isinstance(readiness, Mapping) else None
    )
    return (
        isinstance(profile_readiness, Mapping)
        and profile_readiness.get(interaction.value) is True
    )


def _stripe_param_projection(option: Any, name: str) -> str | None:
    params = _value(option, "params", {})
    value = _value(params, name) if isinstance(params, Mapping) else None
    return value if isinstance(value, str) and value else None


def stripe_funding_profile_projection(option: Any) -> str | None:
    """Project the exact advertised funding profile."""

    return _stripe_param_projection(option, "funding_profile")


def stripe_currency_projection(option: Any) -> str | None:
    """Project the lowercase advertised currency."""

    value = _value(option, "asset")
    return value if isinstance(value, str) and value else None


def stripe_interaction_projection(option: Any) -> str | None:
    """Project the exact advertised interaction mode."""

    return _stripe_param_projection(option, "interaction")


def stripe_funds_flow_projection(option: Any) -> str | None:
    """Project the fixed provider-neutral funds flow."""

    return _stripe_param_projection(option, "funds_flow")


def validate_stripe_publication_input(
    section: BaseModel,
    value: BaseModel,
    role: SettlementRole,
) -> BaseModel:
    """Validate one exact public clause input without provider access."""

    StripeSettlementConfig.model_validate(section)
    if role != "seller":
        raise ValueError("hosted publication input is seller-owned")
    return StripePublicationInput.model_validate(value)


def create_stripe_registration(*, command_group: Any | None = None) -> MechanismRegistration:
    """Return the explicit common-contract registration for hosted Stripe."""

    return MechanismRegistration(
        mechanism_id=MECHANISM,
        config_key=STRIPE_CONFIG_KEY,
        config_model=StripeSettlementConfig,
        roles=frozenset({"buyer", "seller"}),
        negotiates_scalar_amount=True,
        preflight=stripe_preflight,
        client_factory=stripe_client_factory,
        option_builder=stripe_option_builder,
        buyer_compatibility=stripe_buyer_compatibility,
        command_group=command_group,
        public_detail_keys=frozenset(
            {
                "contract_fingerprint",
                "profiles",
                "currency",
                "country",
                "environment",
                "condition_profile",
            }
        ),
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="stripe.funding_profile",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="exact hosted funding profile",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=stripe_funding_profile_projection,
            ),
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="stripe.currency",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="lowercase hosted settlement currency",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=stripe_currency_projection,
            ),
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="stripe.interaction",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="exact hosted buyer interaction mode",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=stripe_interaction_projection,
            ),
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="stripe.funds_flow",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="fixed hosted separate charges/transfers flow",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=stripe_funds_flow_projection,
            ),
        ),
        publication_input_model=StripePublicationInput,
        publication_input_validator=validate_stripe_publication_input,
    )


__all__ = [
    "REQUIRED_STRIPE_CAPABILITIES",
    "STRIPE_CONFIG_KEY",
    "SUPPORTED_FUNDING_PROFILES",
    "StripeAuthorityTrust",
    "StripeResolverConfig",
    "StripeSettlementConfig",
    "StripePublicationInput",
    "stripe_buyer_compatibility",
    "stripe_client_factory",
    "stripe_contract_fingerprint",
    "stripe_currency_projection",
    "stripe_funding_profile_projection",
    "stripe_funds_flow_projection",
    "stripe_interaction_projection",
    "stripe_option_builder",
    "stripe_preflight",
    "validate_stripe_publication_input",
    "create_stripe_registration",
]
