"""Mechanism-neutral recurring publication inputs and preset derivation.

The installed helper owns price/period interpretation and mechanism encoding.
The caller owns capacity bounds, effective delivery promises and recommendations.
No runtime helper or service readiness is inferred from a readable preset.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from market_core.schemas import AgreedPrice, SettlementOption
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import (
    Adjudication, EarlyTermination, Entitlement, LifecycleTerms, SettlesThrough,
    TermContext, encode_terms, validate_terms,
)
from pydantic import BaseModel, ConfigDict, Field

from .rate_servicing import RateServicing, RateServicingDeclaration, RateServicingUnavailable

Amount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$")]
Seconds = Annotated[int, Field(strict=True, ge=0)]


class RecurringPublicationPreset(BaseModel):
    """One priced entitlement combination, not a stored product class."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    period: str = Field(min_length=1)
    reserve_ahead_seconds: Annotated[int, Field(strict=True, gt=0)]
    setup_amount: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")] | None = None
    payer_notice_seconds: Seconds = 0
    payee_notice_seconds: Seconds | None = None
    payee_settles_through: SettlesThrough = "last_boundary"
    settles_through: SettlesThrough = "last_boundary"
    premature_stop_penalty: Amount | None = None


@dataclass(frozen=True)
class RatePresetPricing:
    """Mechanism-owned pricing and enforcement facts for a proposed preset."""

    quote: AgreedPrice
    approval_window_seconds: int
    adjudication: Adjudication
    context: TermContext
    supports_setup_delivery_end: bool = False

    def __post_init__(self) -> None:
        if self.quote.unit != "per_period":
            raise ValueError("recurring preset requires a per-period quote")
        if type(self.approval_window_seconds) is not int or self.approval_window_seconds <= 0:
            raise ValueError("approval window must be positive whole seconds")


@dataclass(frozen=True)
class RatePresetRequest:
    """Resolved inputs to an installed encoder; bounds never enter the option."""

    clause: Any
    preset: RecurringPublicationPreset
    quote: AgreedPrice
    lifecycle: LifecycleTerms
    max_duration_seconds: int | None
    available_until_utc: datetime | None
    default_horizon_seconds: int
    servicing: RateServicingDeclaration


@dataclass(frozen=True)
class RatePresetRefusal:
    code: str
    detail: str


class RatePresetHelper(Protocol):
    def pricing(self, clause: Any, authorities: Sequence[DisputeEntry]) -> RatePresetPricing: ...
    def build(self, request: RatePresetRequest) -> SettlementOption | RatePresetRefusal: ...


def effective_delivery_deadline(value: Any) -> int | None:
    """Refuse malformed pool-port facts rather than advertise a guessed promise."""
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("effective delivery_deadline_seconds must be a positive integer")
    return value


def default_buyer_refusals(
    lifecycle: LifecycleTerms | None, *, has_adapter: bool,
) -> tuple[str, ...]:
    """The conservative rights a default buyer needs, independent of schema."""
    if not has_adapter:
        return ()
    reasons = []
    if lifecycle is None or lifecycle.delivery_deadline_seconds is None:
        reasons.append("no delivery deadline")
    early = lifecycle.early_termination if lifecycle else None
    if early is not None:
        if "payee" not in early.entitlements and early.penalty <= 0:
            reasons.append("on-demand has no positive premature-stop penalty")
        if "payee" in early.entitlements and early.entitlements["payee"].settles_through != "last_boundary":
            reasons.append("payee stop does not return the final partial period")
        if early.settles_through != "last_boundary":
            reasons.append("term end does not return the final partial period")
    return tuple(f"a default buyer refuses this option: {reason}" for reason in reasons)


def derive_rate_preset(
    clause: Any,
    *,
    helper: RatePresetHelper | None,
    servicing: RateServicing,
    authorities: Sequence[DisputeEntry],
    max_duration_seconds: int | None,
    available_until_utc: datetime | str | None,
    delivery_deadline_seconds: int | None,
    now: datetime,
    default_penalty_periods: int,
) -> SettlementOption | RatePresetRefusal:
    """Derive one candidate without suppressing any independently priced peer."""
    preset = clause.recurring
    if preset is None:
        raise ValueError("a recurring publication clause is required")
    try:
        declaration = servicing.select(clause.mechanism)
    except RateServicingUnavailable as exc:
        return RatePresetRefusal("rate_servicing_undeclared", str(exc))
    if helper is None:
        return RatePresetRefusal("rate_helper_missing", "no hosted recurring preset helper")
    deadline = effective_delivery_deadline(delivery_deadline_seconds)
    try:
        pricing = helper.pricing(clause, authorities)
        selected_authority = next((entry for entry in authorities if entry.authority == pricing.adjudication.dispute), None)
        if selected_authority is None or selected_authority.requirements != pricing.context.authority:
            raise ValueError("preset helper selected an unoffered dispute authority or different advertisement")
        quote: AgreedPrice = pricing.quote
        if quote.asset != clause.asset or quote.period != preset.period:
            raise ValueError("helper quote differs from the requested asset or period")
        if pricing.context.mechanism != clause.mechanism:
            raise ValueError("helper lifecycle context differs from the requested mechanism")
        period = quote.period_seconds
        assert period is not None
        if preset.setup_amount is not None and int(preset.setup_amount) > 0 and not pricing.supports_setup_delivery_end:
            return RatePresetRefusal("setup_delivery_end_unsupported", "setup requires the vendored delivery_end revision and vectors")
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("publication time must be aware UTC")
        # Use one whole-second resolved start for the approval expiry and bound.
        start = now.replace(microsecond=0)
        limits = []
        if max_duration_seconds is not None and max_duration_seconds > 0:
            limits.append(max_duration_seconds)
        if isinstance(available_until_utc, str):
            available_until_utc = datetime.fromisoformat(available_until_utc.replace("Z", "+00:00"))
        if available_until_utc is not None:
            if not isinstance(available_until_utc, datetime):
                raise ValueError("available_until_utc must be an aware UTC timestamp")
            if available_until_utc.tzinfo is None or available_until_utc.utcoffset() != UTC.utcoffset(available_until_utc):
                raise ValueError("available_until_utc must be aware UTC")
            # Do not round a fractional capacity end to a different promise.
            remaining = available_until_utc - start
            if remaining.microseconds:
                raise ValueError("recurring default horizon must be whole seconds")
            limits.append(remaining.days * 86400 + remaining.seconds)
        if not limits:
            return RatePresetRefusal("recurring_horizon_unbounded", "recurring publication requires a finite capacity bound")
        horizon = min(limits)
        if horizon < period:
            return RatePresetRefusal("recurring_horizon_too_short", "default horizon leaves less than one whole period")
        minimum = pricing.approval_window_seconds + (deadline or 0) + period
        if horizon < minimum:
            return RatePresetRefusal("recurring_horizon_no_runway", f"The horizon leaves no runway: minimum duration_seconds is {minimum}")
        entitlements: dict[Literal["payer", "payee"], Entitlement] = {"payer": Entitlement(notice_seconds=preset.payer_notice_seconds, settles_through="started_period")}
        if preset.payee_notice_seconds is not None:
            entitlements["payee"] = Entitlement(notice_seconds=preset.payee_notice_seconds, settles_through=preset.payee_settles_through)
        penalty = preset.premature_stop_penalty
        if penalty is None and "payee" not in entitlements:
            penalty = str(quote.amount * default_penalty_periods)
        lifecycle = LifecycleTerms.model_validate({
            "adjudication": pricing.adjudication,
            "early_termination": EarlyTermination(
                version=1, entitlements=entitlements, settles_through=preset.settles_through,
                **({"premature_stop_penalty": penalty} if penalty is not None else {}),
            ),
            **({"delivery_deadline_seconds": deadline} if deadline is not None else {}),
        })
        authority = pricing.context.authority
        if authority is not None and lifecycle.adjudication.dispute_window_seconds < (deadline or 0) + authority.minimum_dispute_window_seconds:
            return RatePresetRefusal("dispute_window_before_delivery_deadline", "the dispute window ends before the delivery deadline can be filed on")
        validate_terms(encode_terms(lifecycle), replace(
            pricing.context, has_stoppable_part=True, compute=True, buyer=False,
        ))
        request = RatePresetRequest(
            clause, preset, quote, lifecycle, max_duration_seconds,
            available_until_utc, horizon, declaration,
        )
        result = helper.build(request)
        if isinstance(result, RatePresetRefusal):
            return result
        option = SettlementOption.model_validate(result)
        if option.settlement_schema != clause.mechanism or option.price_asset != quote.asset:
            raise ValueError("preset encoder changed the selected mechanism or asset")
        if option.lifecycle != encode_terms(lifecycle):
            raise ValueError("preset encoder changed the resolved lifecycle")
        if option.settlement.get("period") != preset.period or option.settlement.get("reserve_ahead_seconds") != preset.reserve_ahead_seconds:
            raise ValueError("preset encoder changed the period or reserve")
        return option
    except ValueError as exc:
        return RatePresetRefusal("recurring_preset_unusable", str(exc))
