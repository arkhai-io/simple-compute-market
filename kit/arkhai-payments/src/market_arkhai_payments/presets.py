"""Hosted rate encoding for composition-owned recurring publication and timing."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from market_core.schemas import (
    SettlementOption, SettlementPrice, RateValue, derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import Adjudication, LifecycleTerms, TermContext, encode_terms
from market_settlement_runtime.horizon import RateTermProjections, RateTermTiming
from market_settlement_runtime.presentation import amount_rate_quote
from market_settlement_runtime.rate_publication import (
    RatePresetHelper, RatePresetPricing, RatePresetRefusal, RatePresetRequest,
)

from .mandates import SUPPORTED_PARTIAL_PERIODS, PaymentsOptionParams, duration_seconds
from .models import AccountId
from .settlement_config import (
    ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsPublicationInput, clause_rate_minor_units, payments_billing_basis,
)


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


def payments_rate_wiring(
    authorities: Callable[[], Sequence[DisputeEntry]],
) -> tuple[Mapping[str, RatePresetHelper], RateTermProjections]:
    """The preset helper and timing projection a compute composition installs.

    Both are installed by default and stay dark until the composition declares
    rate servicing: publication, acceptance and materialization each refuse a
    rate option whose treatments the declaration does not list. ``authorities``
    is read at each projection, so a later change to the offered dispute
    authorities is seen without rebuilding the composition.
    """
    return (
        {ARKHAI_PAYMENTS_MECHANISM: PaymentsRatePresetHelper()},
        {ARKHAI_PAYMENTS_MECHANISM: lambda option: rate_term_timing(option, authorities=authorities())},
    )


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
        minor = clause_rate_minor_units(clause.rate, clause.per, params.asset)
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
            delivery_deadline_seconds=params.delivery_deadline_seconds,
        )

    def build(self, request: RatePresetRequest) -> SettlementOption | RatePresetRefusal:
        # derive_rate_preset checked the declaration's treatments and setup flag
        # before calling here, and acceptance and materialization check them
        # again; this encoder checks only that it was handed its own mechanism's.
        if request.servicing.mechanism != ARKHAI_PAYMENTS_MECHANISM:
            return RatePresetRefusal("rate_servicing_undeclared", "servicing declaration names another mechanism")
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
        minor = clause_rate_minor_units(request.clause.rate, request.clause.per, params.asset)
        price = SettlementPrice(asset=params.asset, rates=[
            RateValue(field="amount", per=request.clause.per, value=minor),
        ])
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        )
