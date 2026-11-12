"""Mechanism-neutral recurring publication inputs and preset derivation.

The installed helper owns price/period interpretation and mechanism encoding.
The caller owns capacity bounds, effective delivery promises and recommendations.
No runtime helper or service readiness is inferred from a readable preset.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from market_core.schemas import (
    AgreedPrice, SettlementOption, settlement_option_lifecycle, settlement_option_schema,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import (
    PARTIAL_PERIOD, Adjudication, EarlyTermination, Entitlement, LifecycleTerms,
    SettlesThrough, TermContext, encode_terms, validate_terms,
)
from pydantic import BaseModel, ConfigDict, Field

from .configuration import MechanismReadiness, SettlementConfig, SettlementConfigurationRegistry
from .horizon import bound_seconds, parse_utc
from .rate_servicing import RateServicing, RateServicingDeclaration, RateServicingUnavailable

Amount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$")]
Seconds = Annotated[int, Field(strict=True, ge=0)]

#: How many of its periods' price an on-demand option's premature-stop penalty
#: is when its clause states none, unless the storefront configures another.
DEFAULT_PREMATURE_STOP_PENALTY_PERIODS = 24

#: A storefront's configured default penalty multiple: a whole number of periods,
#: at least one, since a default of none is stated per clause as ``"0"``.
PenaltyPeriods = Annotated[int, Field(strict=True, gt=0)]


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
    """Mechanism-owned pricing and enforcement facts for a proposed preset.

    ``delivery_deadline_seconds`` is the deadline the clause itself configures,
    read by the mechanism that owns the clause's input; the pool's effective
    deadline, when the composition supplies one, takes precedence over it.
    """

    quote: AgreedPrice
    approval_window_seconds: int
    adjudication: Adjudication
    context: TermContext
    supports_setup_delivery_end: bool = False
    delivery_deadline_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.quote.unit != "per_period":
            raise ValueError("recurring preset requires a per-period quote")
        if type(self.approval_window_seconds) is not int or self.approval_window_seconds <= 0:
            raise ValueError("approval window must be positive whole seconds")
        effective_delivery_deadline(self.delivery_deadline_seconds)


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
    """Refuse a malformed deadline, the pool's or a clause's, rather than
    advertise a guessed promise."""
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("delivery_deadline_seconds must be a positive integer")
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
    # The payer's stop always charges its started period; the payee's stop and
    # the term end are the preset's. Each must be a treatment the composition
    # has qualified, as must a setup charge.
    named = ["started_period", preset.settles_through]
    if preset.payee_notice_seconds is not None:
        named.append(preset.payee_settles_through)
    try:
        declaration = servicing.require(
            clause.mechanism, (PARTIAL_PERIOD[value] for value in named),
            setup=preset.setup_amount is not None,
        )
    except RateServicingUnavailable as exc:
        return RatePresetRefusal("rate_servicing_undeclared", str(exc))
    if helper is None:
        return RatePresetRefusal("rate_helper_missing", "no hosted recurring preset helper")
    deadline = effective_delivery_deadline(delivery_deadline_seconds)
    try:
        pricing = helper.pricing(clause, authorities)
        # The pool's effective deadline, when supplied, wins over the clause's
        # own, so the published term never disagrees with what the site enforces.
        if deadline is None:
            deadline = pricing.delivery_deadline_seconds
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
        # Use one whole-second resolved start for the approval expiry and bound;
        # the default horizon is floored to whole seconds as acceptance floors it.
        start = now.replace(microsecond=0)
        if available_until_utc is not None:
            available_until_utc = parse_utc(available_until_utc, "available_until_utc")
        bound = bound_seconds(start, max_duration_seconds=max_duration_seconds,
                              available_until_utc=available_until_utc)
        if bound is None:
            return RatePresetRefusal("recurring_horizon_unbounded", "recurring publication requires a finite capacity bound")
        horizon = bound
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


@dataclass(frozen=True)
class ClauseArtifacts:
    """What one clause publishes: its accepted escrows and settlement options."""

    accepted_escrows: tuple[dict[str, Any], ...] = ()
    settlement_options: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ClausePublication:
    """The per-clause publication step the VM and bare-metal storefronts compose.

    It holds what is fixed for a composition — the installed registry and its
    configuration, the servicing declaration, the preset helpers, the dispute
    authorities offered, whether the options are compute options, and the
    default penalty multiple — and names no market family: a domain differs
    only in the resources and bounds it passes per candidate.
    """

    registry: SettlementConfigurationRegistry
    config: SettlementConfig
    servicing: RateServicing
    helpers: Mapping[str, RatePresetHelper]
    authorities: Sequence[DisputeEntry]
    dispute_interfaces: frozenset[str]
    compute: bool
    default_penalty_periods: int = DEFAULT_PREMATURE_STOP_PENALTY_PERIODS
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def publish(
        self,
        status: MechanismReadiness,
        clause: Any | None,
        *,
        resources: Mapping[str, Any],
        delivery_deadline: Callable[[], Any],
        max_duration_seconds: int | None,
        available_until_utc: datetime | str | None,
        diagnose: Callable[[dict[str, Any]], None],
    ) -> ClauseArtifacts:
        """Publish one ready mechanism's clause, or its configured option.

        ``clause`` is the compiled publication clause, or ``None`` where the
        candidate states no clauses and the mechanism builds from its section.
        A recurring clause is derived through its mechanism's preset helper; any
        other through the registry's option builder. Each option either path
        builds is then admitted against the servicing declaration and judged
        against the default buyer's policy, every refusal reported through
        ``diagnose`` while the clause's other options and the candidate's other
        clauses publish. ``delivery_deadline`` looks up the pool's effective
        deadline the composition supplies for the candidate, or ``None``. A
        supplied value takes precedence over the deadline a clause configures,
        which only the clause's mechanism reads from the clause's input: the
        option builder receives the pool's value as its
        ``delivery_deadline_seconds`` resource and falls back to its clause's
        own, and a preset helper returns its clause's own through
        ``RatePresetPricing``.
        """
        deadline = effective_delivery_deadline(delivery_deadline())
        if clause is not None and clause.recurring is not None:
            result = derive_rate_preset(
                clause, helper=self.helpers.get(clause.mechanism),
                servicing=self.servicing, authorities=self.authorities,
                max_duration_seconds=max_duration_seconds,
                available_until_utc=available_until_utc,
                delivery_deadline_seconds=deadline, now=self.clock(),
                default_penalty_periods=self.default_penalty_periods,
            )
            if isinstance(result, RatePresetRefusal):
                diagnose({"code": result.code, "detail": result.detail, "mechanism": clause.mechanism})
                return ClauseArtifacts()
            envelope: Any = {"settlement_options": [result.model_dump(mode="json")]}
        else:
            envelope = self.registry.build_option(
                status, self.config, role="seller",
                resources={
                    **resources,
                    "dispute_authorities": self.authorities,
                    "dispute_interfaces": self.dispute_interfaces,
                    "compute": self.compute,
                    "delivery_deadline_seconds": deadline,
                    **({"publication_clause": clause} if clause is not None else {}),
                },
            )
        if not isinstance(envelope, Mapping):
            raise ValueError(f"settlement option builder {status.mechanism} returned no envelope")
        built_escrows = envelope.get("accepted_escrows", ())
        built_options = envelope.get("settlement_options", ())
        if not isinstance(built_escrows, (list, tuple)) or not isinstance(built_options, (list, tuple)):
            raise ValueError("settlement option builder returned invalid carriers")
        options: list[dict[str, Any]] = []
        for item in built_options:
            # The declaration's check validates the option whole, so a builder
            # cannot publish a malformed one; what publishes is the option as
            # built, its bytes the ones its ID was derived from.
            try:
                self.servicing.require_option(item)
            except RateServicingUnavailable as exc:
                diagnose({"code": "rate_servicing_undeclared", "detail": str(exc), "mechanism": settlement_option_schema(item)})
                continue
            lifecycle = settlement_option_lifecycle(item)
            terms = LifecycleTerms.model_validate(lifecycle) if lifecycle is not None else None
            for detail in default_buyer_refusals(terms, has_adapter=terms is not None):
                diagnose({"code": "default_buyer_refusal", "detail": detail, "mechanism": settlement_option_schema(item), "option_id": item["option_id"]})
            options.append(dict(item))
        return ClauseArtifacts(
            accepted_escrows=tuple(dict(item) for item in built_escrows),
            settlement_options=tuple(options),
        )
