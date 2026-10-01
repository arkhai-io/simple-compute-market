"""Bare-metal composition for the stateless Arkhai payments mechanism."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from market_arkhai_payments import (
    Mandate,
    MandatePolicy,
    PaymentsClient,
    PaymentsOptionParams,
    derive_mandate,
    transaction_id,
    verify_receipt,
)
from market_arkhai_payments.models import AccountId
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    QueryValueType,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementPublicationClause,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

ARKHAI_PAYMENTS_MECHANISM = "arkhai.payments.v1"
ARKHAI_PAYMENTS_CONFIG_KEY = "arkhai_payments"
_ACCOUNT_BLOCK = "Arkhai payments requires a configured account UUID"
_CREDENTIAL_BLOCK = "an owner-scoped Arkhai payments credential is required"


class ArkhaiPaymentsConfig(BaseModel):
    """Trusted role policy for payments-service access and receipt verification."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    account_id: str | None = None
    service_url: str | None = None
    service_identity: Identity | None = None
    fee_bps: int = Field(default=250, ge=0, le=10_000)
    dispute_authority: str | None = None

    @field_validator("account_id", "dispute_authority")
    @classmethod
    def validate_account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return AccountId.model_validate(value).root

    @field_validator("service_identity")
    @classmethod
    def require_ed25519_service_identity(cls, value: Identity | None) -> Identity | None:
        if value is not None and value.scheme != IdentityScheme.ED25519:
            raise ValueError("payments service identity must use Ed25519")
        return value

    @field_validator("service_url")
    @classmethod
    def validate_service_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("service_url must be an HTTP(S) origin")
        if parsed.scheme != "https":
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = parsed.hostname.lower() == "localhost"
            if not loopback:
                raise ValueError("payments credentials require HTTPS outside loopback")
        return value.rstrip("/")


class ArkhaiPaymentsPublicationInput(PaymentsOptionParams):
    """Public parameters advertised by one bare-metal payment option."""


def _blocker(code: str, message: str) -> ReadinessBlocker:
    return ReadinessBlocker(code=code, message=message)


async def arkhai_payments_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Check local policy and credentials without contacting the payment service."""

    config = ArkhaiPaymentsConfig.model_validate(section)
    if not config.enabled:
        return MechanismReadiness(
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
            configured=True,
            enabled=False,
            ready=False,
            capabilities=("agreement.v1", "receipt.v1"),
            contract_version=ARKHAI_PAYMENTS_MECHANISM,
            schema_version="1",
        )

    blockers: list[ReadinessBlocker] = []
    if config.account_id is None:
        blockers.append(_blocker("arkhai_payments.account_missing", _ACCOUNT_BLOCK))
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
                "a trusted Ed25519 payments service identity is required",
            )
        )
    if config.dispute_authority is None:
        blockers.append(
            _blocker(
                "arkhai_payments.dispute_authority_missing",
                "the trusted payments dispute authority is required",
            )
        )

    api_key = resources.get("arkhai_payments_api_key")
    development_account = resources.get("arkhai_payments_development_account")
    has_api_key = isinstance(api_key, str) and bool(api_key.strip())
    has_development_account = (
        isinstance(development_account, str) and bool(development_account.strip())
    )
    if has_api_key == has_development_account:
        blockers.append(_blocker("arkhai_payments.credential_missing", _CREDENTIAL_BLOCK))
    if has_development_account and development_account != config.account_id:
        blockers.append(
            _blocker(
                "arkhai_payments.development_account_mismatch",
                "development authentication must use the configured account",
            )
        )

    return MechanismReadiness(
        mechanism=ARKHAI_PAYMENTS_MECHANISM,
        configured=True,
        enabled=True,
        ready=not blockers,
        blockers=tuple(blockers),
        capabilities=("agreement.v1", "receipt.v1"),
        contract_version=ARKHAI_PAYMENTS_MECHANISM,
        schema_version="1",
        public_details={"role": role},
    )


def arkhai_payments_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build one exact public charge-first option from its seller clause."""

    config = ArkhaiPaymentsConfig.model_validate(section)
    if role != "seller" or not config.enabled or not readiness.ready:
        raise ValueError("Arkhai payments is not ready for seller publication")
    raw_clause = SettlementPublicationClause.model_validate(
        resources.get("publication_clause")
    )
    if raw_clause.mechanism != ARKHAI_PAYMENTS_MECHANISM:
        raise ValueError("publication clause does not select Arkhai payments")
    params = ArkhaiPaymentsPublicationInput.model_validate(raw_clause.mechanism_input)
    if params.asset != raw_clause.asset:
        raise ValueError("payment option asset must match the publication clause")
    if params.payee_account != config.account_id:
        raise ValueError("payment option payee must match the configured seller account")

    rates: list[RateValue] = []
    if raw_clause.rate is not None:
        if raw_clause.per != "hour":
            raise ValueError("Arkhai payments supports fixed hourly rates")
        precision = int(params.asset.rsplit("/", 1)[1]) if "/" in params.asset else 0
        scaled = Decimal(raw_clause.rate) * (Decimal(10) ** precision)
        if scaled != scaled.to_integral_value():
            raise ValueError(
                f"payment rate has more than {precision} decimal places for {params.asset}"
            )
        rates.append(RateValue(field="amount", per="hour", value=int(scaled)))

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
    return {"accepted_escrows": [], "settlement_options": [option.model_dump(mode="json")]}


def arkhai_payments_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    del public_context
    config = ArkhaiPaymentsConfig.model_validate(section)
    if not config.enabled or config.account_id is None:
        return False
    raw_params = (
        option.get("params", {})
        if isinstance(option, Mapping)
        else getattr(option, "params", {})
    )
    try:
        params = PaymentsOptionParams.model_validate(raw_params)
    except (TypeError, ValueError):
        return False
    asset = option.get("asset") if isinstance(option, Mapping) else getattr(option, "asset", None)
    return params.asset == asset


def _deposit_projection(option: Any) -> bool | None:
    params = (
        option.get("params", {})
        if isinstance(option, Mapping)
        else getattr(option, "params", {})
    )
    if not isinstance(params, Mapping):
        return None
    value = params.get("deposit_agreement")
    return value if isinstance(value, bool) else None


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
    """Register the charge-first option without a conditional-escrow runtime client."""

    operators = frozenset(
        {
            ComparisonOperator.EQUAL,
            ComparisonOperator.NOT_EQUAL,
            ComparisonOperator.IN,
            ComparisonOperator.NOT_IN,
        }
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
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="arkhai_payments.deposit_agreement",
                    value_type=QueryValueType.BOOLEAN,
                    operators=operators,
                    description="whether the seller deposits the Agreement with Arkhai payments",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=_deposit_projection,
            ),
        ),
        publication_input_model=ArkhaiPaymentsPublicationInput,
        publication_input_validator=validate_arkhai_payments_publication_input,
        negotiates_scalar_amount=True,
    )


@dataclass(frozen=True, slots=True)
class BareMetalArkhaiPaymentsStage:
    """Seller-side Agreement mandate derivation and receipt verification."""

    config: ArkhaiPaymentsConfig
    api_key: str | None = field(default=None, repr=False)
    development_account: str | None = field(default=None, repr=False)

    def _client(self) -> PaymentsClient:
        if self.config.service_url is None:
            raise ValueError("Arkhai payments service URL is not configured")
        return PaymentsClient(
            self.config.service_url,
            api_key=self.api_key,
            development_account=self.development_account,
        )

    def mandate_for_agreement(self, agreement: Mapping[str, Any]) -> Mandate:
        selected = agreement.get("settlement")
        if (
            not isinstance(selected, Mapping)
            or selected.get("mechanism") != ARKHAI_PAYMENTS_MECHANISM
        ):
            raise ValueError("Agreement does not select Arkhai payments")
        option = PaymentsOptionParams.model_validate(selected.get("params"))
        if option.payee_account != self.config.account_id:
            raise ValueError("Agreement payee differs from the configured seller account")
        settlement_params = agreement.get("settlement_params")
        payer = (
            settlement_params.get("payer_account")
            if isinstance(settlement_params, Mapping)
            else None
        )
        payer_account = AccountId.model_validate(payer).root
        policy = MandatePolicy(
            buyer_account=payer_account,
            option=option,
            accepted_at=agreement["accepted_at"],
            start_utc=agreement["start_utc"],
            duration_seconds=agreement["duration_seconds"],
            amount=agreement["amount"],
            asset=agreement["asset"],
            fee_bps=self.config.fee_bps,
            dispute_authority=self.config.dispute_authority,
        )
        return derive_mandate(dict(agreement), policy)

    async def verify_receipt(
        self,
        *,
        transaction: str,
        agreement: Mapping[str, Any],
    ) -> Mandate:
        """Require a current signed receipt for this exact accepted Agreement."""

        mandate = self.mandate_for_agreement(agreement)
        expected_transaction = transaction_id(mandate)
        if transaction != expected_transaction:
            raise ValueError("transaction ID does not match the accepted payment mandate")
        if self.config.service_identity is None:
            raise ValueError("payments service identity is not configured")

        def _verify() -> None:
            with self._client() as client:
                snapshot = client.get_transaction(expected_transaction)
                signed_receipt = snapshot.snapshot.receipt
                if not verify_receipt(
                    signed_receipt,
                    self.config.service_identity,
                    mandate=mandate,
                    agreement_json=agreement,
                ):
                    raise ValueError("payments receipt does not match the accepted Agreement")
                option = PaymentsOptionParams.model_validate(
                    agreement["settlement"]["params"]
                )
                if option.deposit_agreement:
                    client.ensure_agreement_attached(
                        expected_transaction,
                        dict(agreement),
                        option,
                    )

        await asyncio.to_thread(_verify)
        return mandate
