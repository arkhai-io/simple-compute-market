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
from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementPrice,
    derive_settlement_option_id,
    settlement_option_asset,
    settlement_option_params,
    settlement_option_lifecycle,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import (
    Adjudication, LifecycleTerms, TermContext, encode_terms, validate_terms,
)
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    MechanismReadiness,
    MechanismRegistration,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementPublicationClause,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from market_arkhai_payments.client import PaymentsClient
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.models import AccountId, Asset
from market_arkhai_payments.receipts import ReceiptIdentity

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

    # The section may hold its key, so no validation error shows the input.
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True,
    )

    enabled: bool = False
    service_url: str | None = None
    service_identity: Identity | None = None
    receipt_identities: list[ReceiptIdentity] = Field(default_factory=list)
    fee_bps: int | None = Field(default=None, ge=0, le=10_000)
    # The key itself, stated in a service's secret overlay. Marked secret so a
    # values schema generated from this model refuses it in a chart's public
    # configuration.
    api_key: SecretStr | None = Field(default=None, json_schema_extra={"secret": True})
    # The environment variable a buyer's credential provider reads the key from.
    api_key_env: str | None = None
    # A PEM bundle the payments client alone verifies the service against; the
    # process's trust store, and every other client's, is left as it is.
    ca_bundle_path: str | None = None
    development_auth: bool = False
    # The service mode whose receipts this role accepts. Live payments services
    # sign livemode=true; test and development services sign false.
    livemode: bool = False
    # Buyer role only: deposit the exact Agreement with the approval. Off by
    # default because the Agreement discloses both parties and provision terms
    # to the payments service, and a deposit cannot be withdrawn.
    attach_agreement: bool = False

    @property
    def receipt_trust(self) -> tuple[ReceiptIdentity, ...]:
        if self.receipt_identities:
            return tuple(self.receipt_identities)
        return (ReceiptIdentity(identity=self.service_identity),) if self.service_identity else ()

    @model_validator(mode="after")
    def current_receipt_identity(self) -> ArkhaiPaymentsConfig:
        if self.receipt_identities and not any(
            item.identity == self.service_identity and not item.retiring
            for item in self.receipt_identities
        ):
            raise ValueError("receipt_identities must include the current service_identity")
        return self

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

    @model_validator(mode="before")
    @classmethod
    def refuse_retired_dispute_authority(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "dispute_authority" in value:
            raise ValueError(
                "[Settlement.arkhai_payments].dispute_authority is retired; "
                "configure [[Dispute]] preferences or use_registry_dispute_authorities instead"
            )
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_environment_name(cls, value: str | None) -> str | None:
        if value is not None and not _ENVIRONMENT_NAME.fullmatch(value):
            raise ValueError(
                "api_key_env must be an uppercase environment variable name"
            )
        return value

    @field_validator("ca_bundle_path")
    @classmethod
    def validate_ca_bundle_path(cls, value: str | None) -> str | None:
        # An empty path would load no bundle, and the client would then fall
        # back to the default trust store rather than trust the bundle alone.
        if value is not None and not value.strip():
            raise ValueError("ca_bundle_path must name a file")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        # The message never quotes the value: it is a credential.
        if value is not None and not _usable_key(value.get_secret_value()):
            raise ValueError("api_key must be a nonempty single-line key")
        return value

    @model_validator(mode="after")
    def validate_key_forms(self) -> ArkhaiPaymentsConfig:
        # One key resolution serves every caller, so a configuration may state
        # only one way of authenticating, whether or not it publishes new deals.
        if self.api_key is not None and self.api_key_env is not None:
            raise ValueError("api_key and api_key_env are mutually exclusive")
        if self.development_auth:
            for form, value in (("api_key", self.api_key), ("api_key_env", self.api_key_env)):
                if value is not None:
                    raise ValueError(f"development_auth and {form} are mutually exclusive")
        return self

    @model_validator(mode="after")
    def validate_development_auth(self) -> ArkhaiPaymentsConfig:
        if not self.enabled:
            return self
        if self.development_auth:
            if self.service_url is not None and not _loopback_origin(self.service_url):
                raise ValueError("development_auth requires a loopback service_url")
        return self


class ArkhaiPaymentsPublicationInput(PaymentsOptionParams):
    """Public payment parameters accepted by a seller publication clause."""

    asset: str
    dispute_window_seconds: int = Field(ge=0)
    case_hold_max_seconds: int | None = Field(default=None, ge=0)
    delivery_deadline_seconds: int | None = Field(default=None, gt=0)

    @field_validator("dispute_window_seconds", "case_hold_max_seconds", "delivery_deadline_seconds", mode="before")
    @classmethod
    def parse_seconds_clause(cls, value: Any) -> Any:
        return int(value) if isinstance(value, str) and value.isdecimal() else value

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        return Asset.model_validate(value).root

    @field_validator("deposit_agreement", mode="before")
    @classmethod
    def parse_deposit_clause(cls, value: Any) -> Any:
        # CLI publication terms arrive as text; wire option validation stays strict.
        if isinstance(value, str) and value in {"true", "false"}:
            return value == "true"
        return value


def resolve_payments_api_key(
    config: ArkhaiPaymentsConfig,
    *,
    environment: Mapping[str, str] | None = None,
) -> SecretStr:
    """The payments key a role authenticates with, from whichever form it states.

    ``api_key`` when the configuration states it, otherwise the value of the
    variable ``api_key_env`` names in ``environment`` (the process environment
    by default). Client construction, readiness and the access check all resolve
    the key here, so they cannot disagree about which key a role holds. Raises
    ``ArkhaiPaymentsConfigurationError`` naming the form that is missing or
    unavailable, never the key.
    """
    if config.api_key is not None:
        return config.api_key
    if config.api_key_env is None:
        raise ArkhaiPaymentsConfigurationError(
            "payments api_key or api_key_env is not configured"
        )
    source = os.environ if environment is None else environment
    value = source.get(config.api_key_env)
    if not isinstance(value, str) or not _usable_key(value):
        raise ArkhaiPaymentsConfigurationError(
            f"payments API key environment variable {config.api_key_env!r} is unavailable"
        )
    return SecretStr(value)


def payments_client_for_owner(
    config: ArkhaiPaymentsConfig,
    owner_account: str,
    *,
    environment: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> PaymentsClient:
    """Build an authenticated service client without persisting credentials.

    Works whether or not the mechanism is enabled for new deals: accepted deals
    keep being serviced after operators stop publishing payment options. A
    ``ca_bundle_path`` the client cannot load raises ``OSError`` here, before
    any request.
    """
    if config.service_url is None:
        raise ArkhaiPaymentsConfigurationError("payments service_url is not configured")
    owner = AccountId.model_validate(owner_account).root
    client_args: dict[str, Any] = {
        "timeout": timeout,
        "transport": transport,
        "ca_bundle": config.ca_bundle_path,
    }
    if config.development_auth:
        return PaymentsClient(
            config.service_url,
            development_account=owner,
            **client_args,
        )
    api_key = resolve_payments_api_key(config, environment=environment)
    return PaymentsClient(
        config.service_url, api_key=api_key.get_secret_value(), **client_args,
    )


def _usable_key(value: str) -> bool:
    # The key travels as an HTTP header value.
    return bool(value.strip()) and "\r" not in value and "\n" not in value


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _loopback_origin(value: str) -> bool:
    return _is_loopback(httpx.URL(value).host)


def _blocker(code: str, message: str) -> ReadinessBlocker:
    # Readiness never contacts the payments service, so nothing it reports is a
    # reachability blocker.
    return ReadinessBlocker(code=code, message=message, kind="configuration")


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
    if not config.development_auth:
        if config.api_key is None and config.api_key_env is None:
            blockers.append(
                _blocker(
                    "arkhai_payments.api_key_missing",
                    "a payments key is required: api_key in the secret overlay, "
                    "or api_key_env naming the variable that holds it",
                )
            )
        else:
            try:
                resolve_payments_api_key(config)
            except ArkhaiPaymentsConfigurationError:
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


def _option_params(option: Any) -> PaymentsOptionParams | None:
    raw = settlement_option_params(option)
    if not isinstance(raw, Mapping):
        return None
    try:
        Asset.model_validate(settlement_option_asset(option))
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
    raw_clause = resources.get("publication_clause")
    if raw_clause is None:
        # Enabling payments does not select it for every listing. Other
        # mechanisms may publish without a payment price or payee clause.
        return {"accepted_escrows": [], "settlement_options": []}
    clause = SettlementPublicationClause.model_validate(raw_clause)
    if clause.mechanism != ARKHAI_PAYMENTS_MECHANISM:
        raise ValueError("publication clause does not select Arkhai payments")
    params = ArkhaiPaymentsPublicationInput.model_validate(clause.mechanism_input)
    if params.asset != clause.asset:
        raise ValueError("payment option asset must match the publication clause")

    authorities = tuple(DisputeEntry.model_validate(item) for item in resources.get("dispute_authorities", ()))
    if not authorities:
        return {"accepted_escrows": [], "settlement_options": []}
    entry = next((item for item in authorities
                  if ARKHAI_PAYMENTS_MECHANISM in item.advertisement.mechanisms), None)
    if entry is None:
        raise ValueError("no offered dispute authority advertises arkhai.payments.v1")
    AccountId.model_validate(entry.account)
    lifecycle = LifecycleTerms.model_validate({
        "adjudication": Adjudication(
            version=1, dispute=entry.authority,
            dispute_window_seconds=params.dispute_window_seconds,
            case_hold_max_seconds=params.case_hold_max_seconds,
        ),
        **({"delivery_deadline_seconds": params.delivery_deadline_seconds}
           if params.delivery_deadline_seconds is not None else {}),
    })
    validate_terms(encode_terms(lifecycle), TermContext(
        mechanism=ARKHAI_PAYMENTS_MECHANISM, has_adapter=True,
        dispute_interfaces=frozenset(resources.get("dispute_interfaces", ())),
        authority=entry.requirements, compute=bool(resources.get("compute", False)),
    ))
    if resources.get("compute") and lifecycle.delivery_deadline_seconds is None:
        raise ValueError("compute option requires delivery_deadline_seconds")

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

    option_params = params.model_dump(mode="json", exclude={
        "asset", "dispute_window_seconds", "case_hold_max_seconds", "delivery_deadline_seconds",
    })
    price = SettlementPrice(asset=params.asset, rates=rates)
    settlement = {"schema": ARKHAI_PAYMENTS_MECHANISM, **option_params}
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            price=price, settlement=settlement, lifecycle=encode_terms(lifecycle),
        ),
        price=price,
        settlement=settlement,
        lifecycle=encode_terms(lifecycle),
    )
    return {
        "accepted_escrows": [],
        "settlement_options": [option.model_dump(mode="json")],
    }


def validate_payment_lifecycle(
    option: Any, *, authorities: tuple[DisputeEntry, ...],
    dispute_interfaces: frozenset[str], compute: bool = False,
) -> LifecycleTerms:
    """Admit only an exact accepted authority with compatible advertised minima."""
    terms = LifecycleTerms.model_validate(settlement_option_lifecycle(option))
    entry = next((item for item in authorities if item.authority == terms.adjudication.dispute), None)
    validate_terms(encode_terms(terms), TermContext(
        mechanism=ARKHAI_PAYMENTS_MECHANISM, has_adapter=True,
        dispute_interfaces=dispute_interfaces, authority=entry.requirements if entry else None,
        buyer=True, accepted_authorities=tuple(item.authority for item in authorities),
        compute=compute,
    ))
    AccountId.model_validate(terms.adjudication.dispute.account)
    return terms


def arkhai_payments_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    del public_context
    config = ArkhaiPaymentsConfig.model_validate(section)
    if not config.enabled:
        return False
    try:
        terms = LifecycleTerms.model_validate(settlement_option_lifecycle(option))
        AccountId.model_validate(terms.adjudication.dispute.account)
    except ValueError:
        return False
    return _option_params(option) is not None


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
    "resolve_payments_api_key",
    "validate_arkhai_payments_publication_input",
]
