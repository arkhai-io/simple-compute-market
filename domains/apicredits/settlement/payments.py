"""API-credit configuration and registration for Arkhai payments."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Self

from market_arkhai_payments import (
    MandatePolicy,
    PaymentsClient,
    PaymentsOptionParams,
)
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    MechanismReadiness,
    MechanismRegistration,
    SettlementPublicationClause,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

MECHANISM_ID = "arkhai.payments.v1"
CONFIG_KEY = "arkhai_payments"
_ACCOUNT_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ApiCreditsArkhaiPaymentsConfig(BaseModel):
    """Role-local credentials and trusted service policy for API-credit payments."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    account_id: str | None = None
    service_url: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    development_account: str | None = None
    fee_bps: int | None = Field(default=None, ge=0, le=10_000)
    dispute_authority: str | None = None
    service_identity: Identity | None = None

    @model_validator(mode="after")
    def validate_enabled_config(self) -> Self:
        if not self.enabled:
            return self
        if not isinstance(self.account_id, str) or not _ACCOUNT_ID.fullmatch(
            self.account_id
        ):
            raise ValueError(
                "enabled Arkhai payments requires a lowercase UUID account_id"
            )
        if not isinstance(self.service_url, str) or not self.service_url.strip():
            raise ValueError("enabled Arkhai payments requires service_url")
        if (self.api_key is None) == (self.development_account is None):
            raise ValueError(
                "configure exactly one Arkhai payments authentication mode"
            )
        if self.api_key is not None and not self.api_key.strip():
            raise ValueError("api_key must not be empty")
        if self.development_account is not None:
            if not _ACCOUNT_ID.fullmatch(self.development_account):
                raise ValueError("development_account must be a lowercase UUID")
            if self.development_account != self.account_id:
                raise ValueError("development_account must match account_id")
        if self.fee_bps is None:
            raise ValueError("enabled Arkhai payments requires fee_bps")
        if not isinstance(self.dispute_authority, str) or not _ACCOUNT_ID.fullmatch(
            self.dispute_authority
        ):
            raise ValueError(
                "enabled Arkhai payments requires a lowercase UUID dispute_authority"
            )
        if (
            self.service_identity is None
            or self.service_identity.scheme != IdentityScheme.ED25519
        ):
            raise ValueError(
                "enabled Arkhai payments requires an Ed25519 service_identity"
            )
        return self


class ApiCreditsPaymentsPublicationInput(BaseModel):
    """Public, seller-owned fields for one API-credit payment option."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    window: str = "P7D"
    deposit_agreement: bool = False


def payments_client_options(
    config: ApiCreditsArkhaiPaymentsConfig,
) -> tuple[str, dict[str, str]]:
    """Return validated client constructor inputs without exposing credentials."""
    if not config.enabled or config.service_url is None:
        raise ValueError("Arkhai payments is not enabled")
    if config.api_key is not None:
        return config.service_url, {"api_key": config.api_key}
    if config.development_account is not None:
        return config.service_url, {"development_account": config.development_account}
    raise ValueError("Arkhai payments authentication is not configured")


def validate_payer_account(value: Any) -> str:
    if not isinstance(value, str) or not _ACCOUNT_ID.fullmatch(value):
        raise ValueError("payer account must be a lowercase UUID")
    return value


def mandate_policy_from_agreement(
    agreement: Mapping[str, Any],
    *,
    fee_bps: int,
    dispute_authority: str,
    expected_buyer_account: str | None = None,
) -> MandatePolicy:
    """Build exact payment policy from an accepted API-credit Agreement."""
    if not isinstance(agreement, Mapping):
        raise ValueError("accepted Agreement must be an object")
    settlement = agreement.get("settlement")
    if (
        not isinstance(settlement, Mapping)
        or settlement.get("mechanism") != MECHANISM_ID
    ):
        raise ValueError("Agreement does not select arkhai.payments.v1")
    settlement_params = agreement.get("settlement_params")
    payer_account = (
        settlement_params.get("payer_account")
        if isinstance(settlement_params, Mapping)
        else None
    )
    payer_account = validate_payer_account(payer_account)
    if expected_buyer_account is not None and payer_account != expected_buyer_account:
        raise ValueError(
            "Agreement payer account differs from the configured buyer account"
        )
    option = PaymentsOptionParams.model_validate(settlement.get("params"))
    return MandatePolicy(
        buyer_account=payer_account,
        option=option,
        accepted_at=agreement["accepted_at"],
        start_utc=agreement["start_utc"],
        duration_seconds=agreement["duration_seconds"],
        amount=agreement["amount"],
        asset=agreement["asset"],
        fee_bps=fee_bps,
        dispute_authority=dispute_authority,
    )


def create_api_credits_payments_registration() -> MechanismRegistration:
    """Register API-credit payment options beside Alkahest in role compositions."""

    def preflight(
        section: BaseModel,
        _resources: Mapping[str, Any],
        _role: SettlementRole,
    ) -> MechanismReadiness:
        config = ApiCreditsArkhaiPaymentsConfig.model_validate(section)
        return MechanismReadiness(
            mechanism=MECHANISM_ID,
            configured=True,
            enabled=config.enabled,
            ready=config.enabled,
            capabilities=("mandate-approval.v1", "signed-receipt.v1"),
            contract_version="arkhai.payments.v1",
            schema_version="1",
        )

    def client_factory(
        section: BaseModel,
        _resources: Mapping[str, Any],
        _role: SettlementRole,
    ) -> PaymentsClient:
        url, auth = payments_client_options(
            ApiCreditsArkhaiPaymentsConfig.model_validate(section)
        )
        return PaymentsClient(url, **auth)

    def option_builder(
        section: BaseModel,
        readiness: MechanismReadiness,
        resources: Mapping[str, Any],
        role: SettlementRole,
    ) -> dict[str, list[dict[str, Any]]]:
        del role
        config = ApiCreditsArkhaiPaymentsConfig.model_validate(section)
        if not config.enabled or not readiness.ready or config.account_id is None:
            raise ValueError("Arkhai payments is not ready for publication")
        raw_clause = resources.get("publication_clause")
        if raw_clause is None:
            raise ValueError(
                "API-credit payment publication requires an explicit rate clause"
            )
        clause = SettlementPublicationClause.model_validate(raw_clause)
        if (
            clause.mechanism != MECHANISM_ID
            or clause.rate is None
            or clause.per is None
        ):
            raise ValueError(
                "API-credit payment publication requires mechanism, rate, and unit"
            )
        if not clause.rate.isdigit() or clause.per not in {
            "credit",
            "token",
            "request",
        }:
            raise ValueError(
                "API-credit payment rate must be integer base units per credit"
            )
        publication = ApiCreditsPaymentsPublicationInput.model_validate(
            clause.mechanism_input
        )
        params = PaymentsOptionParams(
            payee_account=config.account_id,
            asset=clause.asset,
            window=publication.window,
            deposit_agreement=publication.deposit_agreement,
        ).model_dump(mode="json")
        rates = [RateValue(field="amount", per=clause.per, value=int(clause.rate))]
        option = SettlementOption(
            option_id=derive_settlement_option_id(
                mechanism=MECHANISM_ID,
                asset=clause.asset,
                rates=rates,
                params=params,
            ),
            mechanism=MECHANISM_ID,
            asset=clause.asset,
            rates=rates,
            params=params,
        )
        return {"settlement_options": [option.model_dump(mode="json")]}

    def validate_publication_input(
        section: BaseModel,
        value: BaseModel,
        role: SettlementRole,
    ) -> BaseModel:
        config = ApiCreditsArkhaiPaymentsConfig.model_validate(section)
        if role != "seller" or not config.enabled or config.account_id is None:
            raise ValueError(
                "API-credit payment publication is seller-owned and must be enabled"
            )
        return ApiCreditsPaymentsPublicationInput.model_validate(value)

    def buyer_compatibility(
        section: BaseModel,
        option: Any,
        _public_context: Mapping[str, Any],
    ) -> bool:
        config = ApiCreditsArkhaiPaymentsConfig.model_validate(section)
        if not config.enabled or getattr(option, "mechanism", None) != MECHANISM_ID:
            return False
        try:
            params = PaymentsOptionParams.model_validate(getattr(option, "params", {}))
        except (TypeError, ValueError):
            return False
        return getattr(option, "asset", None) == params.asset

    return MechanismRegistration(
        mechanism_id=MECHANISM_ID,
        config_key=CONFIG_KEY,
        config_model=ApiCreditsArkhaiPaymentsConfig,
        roles=frozenset({"buyer", "seller"}),
        preflight=preflight,
        client_factory=client_factory,
        option_builder=option_builder,
        buyer_compatibility=buyer_compatibility,
        clause_fields=(),
        publication_input_model=ApiCreditsPaymentsPublicationInput,
        publication_input_validator=validate_publication_input,
        negotiates_scalar_amount=True,
    )


__all__ = [
    "ApiCreditsArkhaiPaymentsConfig",
    "ApiCreditsPaymentsPublicationInput",
    "validate_payer_account",
    "CONFIG_KEY",
    "MECHANISM_ID",
    "create_api_credits_payments_registration",
    "mandate_policy_from_agreement",
    "payments_client_options",
]
