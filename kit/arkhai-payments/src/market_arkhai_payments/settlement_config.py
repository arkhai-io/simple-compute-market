"""Typed configuration and option registration for Arkhai payments."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx
from market_core.query_dsl import ComparisonOperator, FieldDescriptor, QueryValueType
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    MechanismReadiness,
    MechanismRegistration,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementPublicationClause,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from market_arkhai_payments.client import PaymentsClient
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.models import AccountId

ARKHAI_PAYMENTS_MECHANISM = "arkhai.payments.v1"
ARKHAI_PAYMENTS_CONFIG_KEY = "arkhai_payments"

_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CAPABILITIES = ("agreement.v1", "receipt.v1")
_CLAUSE_OPERATORS = frozenset(
    {
        ComparisonOperator.EQUAL,
        ComparisonOperator.NOT_EQUAL,
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
)


class ArkhaiPaymentsConfigurationError(RuntimeError):
    """Trusted payments configuration cannot construct an authenticated client."""


class ArkhaiPaymentsConfig(BaseModel):
    """Trusted payments-service policy for one buyer or seller role."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    service_url: str | None = None
    service_identity: Identity | None = None
    fee_bps: int | None = Field(default=None, ge=0, le=10_000)
    dispute_authority: str | None = None
    api_key_env: str | None = None
    development_auth: bool = False
    # Buyer role only: deposit the exact Agreement with the approval. Off by
    # default because the Agreement discloses both parties and provision terms
    # to the payments service, and a deposit cannot be withdrawn.
    attach_agreement: bool = False

    @field_validator("service_url")
    @classmethod
    def validate_service_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = httpx.URL(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.host
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("service_url must be an HTTP(S) origin")
        if parsed.scheme != "https" and not _is_loopback(parsed.host):
            raise ValueError("payments credentials require HTTPS outside loopback")
        return str(parsed).rstrip("/")

    @field_validator("service_identity")
    @classmethod
    def require_ed25519_service_identity(
        cls, value: Identity | None
    ) -> Identity | None:
        if value is not None and value.scheme != IdentityScheme.ED25519:
            raise ValueError("payments receipt identity must use Ed25519")
        return value

    @field_validator("dispute_authority")
    @classmethod
    def validate_dispute_authority(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return AccountId.model_validate(value).root

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_environment_name(cls, value: str | None) -> str | None:
        if value is not None and not _ENVIRONMENT_NAME.fullmatch(value):
            raise ValueError(
                "api_key_env must be an uppercase environment variable name"
            )
        return value

    @model_validator(mode="after")
    def validate_development_auth(self) -> ArkhaiPaymentsConfig:
        if not self.enabled:
            return self
        if self.development_auth:
            if self.api_key_env is not None:
                raise ValueError(
                    "development_auth and api_key_env are mutually exclusive"
                )
            if self.service_url is not None and not _loopback_origin(self.service_url):
                raise ValueError("development_auth requires a loopback service_url")
        return self


class ArkhaiPaymentsPublicationInput(PaymentsOptionParams):
    """Public payment parameters accepted by a seller publication clause."""

    @field_validator("deposit_agreement", mode="before")
    @classmethod
    def parse_deposit_clause(cls, value: Any) -> Any:
        # CLI publication terms arrive as text; wire option validation stays strict.
        if isinstance(value, str) and value in {"true", "false"}:
            return value == "true"
        return value


def payments_client_for_owner(
    config: ArkhaiPaymentsConfig,
    owner_account: str,
    *,
    environment: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> PaymentsClient:
    """Build an authenticated service client without persisting credentials."""
    if not config.enabled:
        raise ArkhaiPaymentsConfigurationError("Arkhai payments is disabled")
    if config.service_url is None:
        raise ArkhaiPaymentsConfigurationError("payments service_url is not configured")
    owner = AccountId.model_validate(owner_account).root
    client_args: dict[str, Any] = {"timeout": timeout, "transport": transport}
    if config.development_auth:
        return PaymentsClient(
            config.service_url,
            development_account=owner,
            **client_args,
        )
    if config.api_key_env is None:
        raise ArkhaiPaymentsConfigurationError("payments api_key_env is not configured")
    source = os.environ if environment is None else environment
    api_key = source.get(config.api_key_env)
    if not isinstance(api_key, str) or not api_key.strip():
        raise ArkhaiPaymentsConfigurationError(
            f"payments API key environment variable {config.api_key_env!r} is unavailable"
        )
    return PaymentsClient(config.service_url, api_key=api_key, **client_args)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _loopback_origin(value: str) -> bool:
    return _is_loopback(httpx.URL(value).host)


def _blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message)


async def arkhai_payments_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Check trusted policy and credentials without contacting the service."""
    del resources
    config = ArkhaiPaymentsConfig.model_validate(section)
    if not config.enabled:
        return MechanismReadiness(
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
            configured=True,
            enabled=False,
            ready=False,
            capabilities=_CAPABILITIES,
            contract_version=ARKHAI_PAYMENTS_MECHANISM,
            schema_version="1",
        )

    blockers: list[ReadinessBlocker] = []
    if role == "seller" and config.attach_agreement:
        blockers.append(
            _blocker(
                "arkhai_payments.attach_agreement_buyer_only",
                "attach_agreement is a buyer setting; sellers deposit through "
                "the option's deposit_agreement",
            )
        )
    if config.service_url is None:
        blockers.append(
            _blocker(
                "arkhai_payments.service_url_missing",
                "a payments service origin is required",
            )
        )
    if config.service_identity is None:
        blockers.append(
            _blocker(
                "arkhai_payments.service_identity_missing",
                "a trusted Ed25519 payments receipt identity is required",
            )
        )
    if config.fee_bps is None:
        blockers.append(
            _blocker(
                "arkhai_payments.fee_policy_missing",
                "a payments fee policy is required",
            )
        )
    if config.dispute_authority is None:
        blockers.append(
            _blocker(
                "arkhai_payments.dispute_authority_missing",
                "the trusted payments dispute authority is required",
            )
        )
    if not config.development_auth:
        if config.api_key_env is None:
            blockers.append(
                _blocker(
                    "arkhai_payments.api_key_env_missing",
                    "an API key environment variable name is required",
                )
            )
        elif not os.environ.get(config.api_key_env, "").strip():
            blockers.append(
                _blocker(
                    "arkhai_payments.credential_missing",
                    "the configured payments API key is unavailable",
                )
            )

    return MechanismReadiness(
        mechanism=ARKHAI_PAYMENTS_MECHANISM,
        configured=True,
        enabled=True,
        ready=not blockers,
        blockers=tuple(blockers),
        capabilities=_CAPABILITIES,
        contract_version=ARKHAI_PAYMENTS_MECHANISM,
        schema_version="1",
    )


def _value(source: Any, name: str, default: Any = None) -> Any:
    return (
        source.get(name, default)
        if isinstance(source, Mapping)
        else getattr(source, name, default)
    )


def _option_params(option: Any) -> PaymentsOptionParams | None:
    raw = _value(option, "params", {})
    if not isinstance(raw, Mapping):
        return None
    try:
        return PaymentsOptionParams.model_validate(raw)
    except (TypeError, ValueError):
        return None


def arkhai_payments_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build one public payment option from its seller publication clause."""
    config = ArkhaiPaymentsConfig.model_validate(section)
    if role != "seller" or not config.enabled or not readiness.ready:
        raise ValueError("Arkhai payments is not ready for seller publication")
    clause = SettlementPublicationClause.model_validate(
        resources.get("publication_clause")
    )
    if clause.mechanism != ARKHAI_PAYMENTS_MECHANISM:
        raise ValueError("publication clause does not select Arkhai payments")
    params = ArkhaiPaymentsPublicationInput.model_validate(clause.mechanism_input)
    if params.asset != clause.asset:
        raise ValueError("payment option asset must match the publication clause")

    rates: list[RateValue] = []
    if clause.rate is not None:
        if clause.per == "hour":
            precision = (
                int(params.asset.rsplit("/", 1)[1]) if "/" in params.asset else 0
            )
            scaled = Decimal(clause.rate) * (Decimal(10) ** precision)
            if scaled != scaled.to_integral_value():
                raise ValueError(
                    f"payment rate has more than {precision} decimal places for {params.asset}"
                )
            value = int(scaled)
        else:
            # Unit prices are already integer base units; asset precision
            # must not scale them a second time. Domains own the unit vocabulary.
            if clause.per is None or not clause.rate.isdigit():
                raise ValueError("payment unit rate must be integer base units")
            value = int(clause.rate)
        rates.append(RateValue(field="amount", per=clause.per, value=value))

    option_params = params.model_dump(mode="json")
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
            asset=params.asset,
            rates=rates,
            params=option_params,
        ),
        mechanism=ARKHAI_PAYMENTS_MECHANISM,
        asset=params.asset,
        rates=rates,
        params=option_params,
    )
    return {
        "accepted_escrows": [],
        "settlement_options": [option.model_dump(mode="json")],
    }


def arkhai_payments_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    del public_context
    config = ArkhaiPaymentsConfig.model_validate(section)
    if not config.enabled:
        return False
    params = _option_params(option)
    return params is not None and params.asset == _value(option, "asset")


def _payee_projection(option: Any) -> str | None:
    params = _option_params(option)
    return params.payee_account if params is not None else None


def _window_projection(option: Any) -> str | None:
    params = _option_params(option)
    return params.window if params is not None else None


def _deposit_projection(option: Any) -> bool | None:
    params = _option_params(option)
    return params.deposit_agreement if params is not None else None


def validate_arkhai_payments_publication_input(
    section: BaseModel,
    value: BaseModel,
    role: SettlementRole,
) -> BaseModel:
    ArkhaiPaymentsConfig.model_validate(section)
    if role != "seller":
        raise ValueError("Arkhai payments publication input is seller-owned")
    return ArkhaiPaymentsPublicationInput.model_validate(value)


def create_arkhai_payments_registration() -> MechanismRegistration:
    """Register public option construction without escrow servicing hooks."""
    fields = (
        SettlementClauseField(
            descriptor=FieldDescriptor(
                name="arkhai_payments.payee_account",
                value_type=QueryValueType.STRING,
                operators=_CLAUSE_OPERATORS,
                description="the seller's Arkhai payment account",
            ),
            roles=frozenset({"buyer", "seller"}),
            projector=_payee_projection,
        ),
        SettlementClauseField(
            descriptor=FieldDescriptor(
                name="arkhai_payments.window",
                value_type=QueryValueType.STRING,
                operators=_CLAUSE_OPERATORS,
                description="the payment mandate's authorization window",
            ),
            roles=frozenset({"buyer", "seller"}),
            projector=_window_projection,
        ),
        SettlementClauseField(
            descriptor=FieldDescriptor(
                name="arkhai_payments.deposit_agreement",
                value_type=QueryValueType.BOOLEAN,
                operators=_CLAUSE_OPERATORS,
                description="whether the seller deposits the Agreement with the service",
            ),
            roles=frozenset({"buyer", "seller"}),
            projector=_deposit_projection,
        ),
    )
    return MechanismRegistration(
        mechanism_id=ARKHAI_PAYMENTS_MECHANISM,
        config_key=ARKHAI_PAYMENTS_CONFIG_KEY,
        config_model=ArkhaiPaymentsConfig,
        roles=frozenset({"buyer", "seller"}),
        preflight=arkhai_payments_preflight,
        client_factory=None,
        option_builder=arkhai_payments_option_builder,
        buyer_compatibility=arkhai_payments_buyer_compatibility,
        clause_fields=fields,
        publication_input_model=ArkhaiPaymentsPublicationInput,
        publication_input_validator=validate_arkhai_payments_publication_input,
        negotiates_scalar_amount=True,
    )


__all__ = [
    "ARKHAI_PAYMENTS_CONFIG_KEY",
    "ARKHAI_PAYMENTS_MECHANISM",
    "ArkhaiPaymentsConfig",
    "ArkhaiPaymentsConfigurationError",
    "ArkhaiPaymentsPublicationInput",
    "arkhai_payments_buyer_compatibility",
    "arkhai_payments_option_builder",
    "arkhai_payments_preflight",
    "create_arkhai_payments_registration",
    "payments_client_for_owner",
    "validate_arkhai_payments_publication_input",
]
