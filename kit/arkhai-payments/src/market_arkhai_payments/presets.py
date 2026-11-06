"""Hosted rate encoding for composition-owned recurring publication and timing."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from market_core.schemas import (
    SettlementOption, SettlementPrice, RateValue, derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import Adjudication, LifecycleTerms, TermContext, encode_terms
from market_settlement_runtime.horizon import RateTermTiming
from market_settlement_runtime.presentation import amount_rate_quote
from market_settlement_runtime.rate_publication import RatePresetPricing, RatePresetRequest, RatePresetRefusal

from .contracts import get_contract
from .mandates import PaymentsOptionParams, duration_seconds
from .models import AccountId
from .settlement_config import ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsPublicationInput, payments_billing_basis

SUPPORTED_PARTIAL_PERIODS = frozenset({"charged", "returned", "prorated", "chosen"})


def rate_contract_revision() -> str:
    """The exact installed schema identity a servicing declaration must select."""
    return str(get_contract().metadata["schema_sha256"])


def rate_context(authorities: Sequence[DisputeEntry], lifecycle: LifecycleTerms) -> TermContext:
    entry = next((item for item in authorities if item.authority == lifecycle.adjudication.dispute), None)
    return TermContext(
        mechanism=ARKHAI_PAYMENTS_MECHANISM, has_adapter=True, has_stoppable_part=True,
        supported_partial_periods=SUPPORTED_PARTIAL_PERIODS,
        dispute_interfaces=frozenset(item.interface for item in authorities),
        authority=entry.requirements if entry else None,
    )


def rate_term_timing(option: SettlementOption, *, authorities: Sequence[DisputeEntry]) -> RateTermTiming:
    basis = payments_billing_basis(option)
    if basis.unit != "per_period" or basis.period_seconds is None:
        raise ValueError("rate timing requires a recurring payment option")
    params = PaymentsOptionParams.model_validate(option.settlement_params)
    lifecycle = LifecycleTerms.model_validate(option.lifecycle)
    return RateTermTiming(basis.period_seconds, params.approval_seconds, rate_context(authorities, lifecycle))


class PaymentsRatePresetHelper:
    """Encode resolved terms; no domain defaults, horizon choices or servicing switch."""

    def pricing(self, clause: Any, authorities: Sequence[DisputeEntry]) -> RatePresetPricing:
        if clause.mechanism != ARKHAI_PAYMENTS_MECHANISM or clause.recurring is None:
            raise ValueError("hosted recurring payment clause required")
        params = ArkhaiPaymentsPublicationInput.model_validate(clause.mechanism_input)
        if clause.asset != params.asset or clause.rate is None or clause.per is None:
            raise ValueError("rate publication requires matching asset and an explicit price")
        entry = next((item for item in authorities if ARKHAI_PAYMENTS_MECHANISM in item.advertisement.mechanisms), None)
        if entry is None:
            raise ValueError("no offered dispute authority advertises payments")
        AccountId.model_validate(entry.account)
        preset = clause.recurring
        settlement = {"schema": ARKHAI_PAYMENTS_MECHANISM,
                      "payee_account": params.payee_account, "period": preset.period,
                      "reserve_ahead_seconds": preset.reserve_ahead_seconds}
        # Hourly clause prices are major units; other unit prices are already
        # base units, as in the once publication encoder.
        if clause.per == "hour":
            precision = int(params.asset.rsplit("/", 1)[1]) if "/" in params.asset else 0
            value = Decimal(clause.rate) * (Decimal(10) ** precision)
            if value != value.to_integral_value():
                raise ValueError("payment rate exceeds asset precision")
            minor = int(value)
        else:
            if not clause.rate.isdecimal():
                raise ValueError("payment unit rate must be integer base units")
            minor = int(clause.rate)
        price = SettlementPrice(asset=params.asset, rates=[RateValue(field="amount", per=clause.per, value=minor)])
        candidate = SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement),
            price=price, settlement=settlement,
        )
        quote = amount_rate_quote(candidate, None, payments_billing_basis(candidate))
        if quote.amount <= 0:
            raise ValueError("rate must charge a positive minor-unit amount per period")
        adjudication = Adjudication(
            version=1, dispute=entry.authority, dispute_window_seconds=params.dispute_window_seconds,
            case_hold_max_seconds=params.case_hold_max_seconds,
        )
        return RatePresetPricing(
            quote, params.approval_seconds, adjudication,
            rate_context(authorities, LifecycleTerms(adjudication=adjudication)),
            supports_setup_delivery_end=True,
        )

    def build(self, request: RatePresetRequest) -> SettlementOption | RatePresetRefusal:
        if request.servicing.mechanism != ARKHAI_PAYMENTS_MECHANISM or request.servicing.contract_revision != rate_contract_revision():
            return RatePresetRefusal("rate_contract_unavailable", "servicing declaration differs from the installed payments contract")
        params = ArkhaiPaymentsPublicationInput.model_validate(request.clause.mechanism_input)
        preset = request.preset
        encoded = PaymentsOptionParams(
            payee_account=params.payee_account, approval_window=params.approval_window or params.window,
            deposit_agreement=params.deposit_agreement, period=preset.period,
            reserve_ahead_seconds=preset.reserve_ahead_seconds, setup_amount=preset.setup_amount,
        )
        settlement = {"schema": ARKHAI_PAYMENTS_MECHANISM,
                      **encoded.model_dump(mode="json", exclude_none=True, exclude={"window"})}
        # Retain the clause's advertised rate, not a finite-horizon total. The
        # accepted monetary quote is pinned separately by signed acceptance.
        precision = int(params.asset.rsplit("/", 1)[1]) if "/" in params.asset else 0
        minor = (int(Decimal(request.clause.rate) * (Decimal(10) ** precision))
                 if request.clause.per == "hour" else int(request.clause.rate))
        price = SettlementPrice(asset=params.asset, rates=[
            RateValue(field="amount", per=request.clause.per, value=minor),
        ])
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        )
