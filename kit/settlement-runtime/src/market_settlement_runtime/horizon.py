"""Finite service horizons resolved against one acceptance instant.

Mechanisms project their own approval timing and lifecycle capabilities; callers
supply capacity bounds. Neither option bytes nor accepted leases are rewritten.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import floor

from market_core.schemas import SettlementOption
from market_deal_lifecycle.terms import TermContext, validate_terms


@dataclass(frozen=True)
class RateTermTiming:
    """Timing and enforceable treatments projected by the installed mechanism."""

    period_seconds: int
    approval_window_seconds: int
    context: TermContext

    def __post_init__(self) -> None:
        for value in (self.period_seconds, self.approval_window_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError("rate timing requires positive whole seconds")


RateTermProjections = Mapping[str, Callable[[SettlementOption], RateTermTiming]]


@dataclass(frozen=True)
class ResolvedHorizon:
    start_utc: str
    duration_seconds: int


def parse_utc(value: str | datetime, name: str) -> datetime:
    """Read an aware UTC instant; another offset or a naive value is refused."""
    instant = datetime.fromisoformat(value.strip().replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be aware UTC")
    return instant


def bound_seconds(
    start: datetime, *, max_duration_seconds: int | None,
    available_until_utc: str | datetime | None,
) -> int | None:
    """The longest duration both listing bounds allow from ``start``, or ``None``.

    A nonpositive relative bound states no limit. The absolute bound is floored to
    whole seconds: a whole-second duration never ends after it, and the Agreement's
    duration is whole seconds. A bound already passed yields a nonpositive value.
    """
    limits: list[int] = []
    if max_duration_seconds is not None and max_duration_seconds > 0:
        limits.append(max_duration_seconds)
    if available_until_utc is not None:
        remaining = parse_utc(available_until_utc, "available_until_utc") - start
        # A timedelta normalizes microseconds to be nonnegative, so this floors.
        limits.append(remaining.days * 86400 + remaining.seconds)
    return min(limits) if limits else None


def check_accepted_horizon(
    *, start_utc: str, duration_seconds: int, requested_duration_seconds: int | None,
    max_duration_seconds: int | None, available_until_utc: str | datetime | None,
) -> None:
    """Refuse a signed horizon the buyer did not ask for or the listing did not offer.

    The buyer runs this on the counterparty's signed Agreement before approval, so
    it holds whatever the seller's own resolver did: the duration fits both bounds
    at the Agreement's start, equals an explicit request, and, when the buyer named
    none, equals the default bound the seller was to resolve.
    """
    start = parse_utc(start_utc, "Agreement start_utc")
    if type(duration_seconds) is not int or duration_seconds <= 0:
        raise ValueError("accepted duration_seconds must be positive whole seconds")
    bound = bound_seconds(start, max_duration_seconds=max_duration_seconds,
                          available_until_utc=available_until_utc)
    if bound is not None and duration_seconds > bound:
        raise ValueError(
            f"accepted duration_seconds {duration_seconds} exceeds the listing's bound "
            f"of {bound} at the Agreement's start"
        )
    if requested_duration_seconds is not None:
        if duration_seconds != requested_duration_seconds:
            raise ValueError(
                f"accepted duration_seconds {duration_seconds} differs from the requested "
                f"{requested_duration_seconds}"
            )
    elif bound is None:
        raise ValueError("an omitted horizon needs a finite listing bound to resolve to")
    elif duration_seconds != bound:
        raise ValueError(
            f"accepted duration_seconds {duration_seconds} differs from the default "
            f"horizon {bound} for an omitted request"
        )


def resolve_horizon(
    *, requested_duration_seconds: int | None, requested_start_utc: str | None,
    accepted_at: datetime, max_duration_seconds: int | None,
    available_until_utc: str | datetime | None, option: SettlementOption | None,
    rate_terms: RateTermProjections, min_duration_seconds: int | None = None,
) -> ResolvedHorizon:
    """Resolve without rounding a buyer horizon or the capacity's absolute end."""
    if accepted_at.tzinfo is None:
        raise ValueError("acceptance time must be timezone-aware")
    accepted_at = accepted_at.astimezone(UTC)
    recurring = option is not None and any(
        key in option.settlement for key in ("period", "reserve_ahead_seconds")
    )
    timing = None
    if recurring:
        assert option is not None
        project = rate_terms.get(option.settlement_schema)
        if project is None:
            raise ValueError("recurring timing projection unavailable; refetch supported terms")
        timing = project(option)
        if timing.context.mechanism != option.settlement_schema:
            raise ValueError("timing projection changed the selected mechanism")
        lifecycle = validate_terms(option.lifecycle, replace(
            timing.context, compute=True, has_stoppable_part=True, buyer=False,
        ))
        if lifecycle is None or lifecycle.early_termination is None:
            raise ValueError("recurring option requires lifecycle early-termination terms")
    else:
        lifecycle = None
    implicit_start = requested_start_utc is None or requested_start_utc.strip().lower() in {"", "now"}
    if implicit_start:
        # No buyer-signed instant exists yet. Resolve rate 'now' once at the
        # authority's whole-second precision; explicit instants are never rounded.
        start = accepted_at.replace(microsecond=0) if recurring else accepted_at
    else:
        assert requested_start_utc is not None
        start = datetime.fromisoformat(requested_start_utc.strip().replace("Z", "+00:00"))
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    if recurring and start.microsecond:
        raise ValueError("recurring start_utc must be whole seconds")
    # The default horizon is the bound floored to whole seconds, so a fractional
    # absolute bound yields a default that ends just before it.
    bound = bound_seconds(start, max_duration_seconds=max_duration_seconds,
                          available_until_utc=available_until_utc)
    duration = requested_duration_seconds
    if duration is None:
        if not recurring:
            raise ValueError("reserved duration_seconds is required")
        if bound is None:
            raise ValueError("recurring horizon requires a finite listing bound")
        duration = bound
    if type(duration) is not int or duration <= 0:
        raise ValueError("duration_seconds must be positive whole seconds; horizon may have expired")
    if bound is not None and duration > bound:
        raise ValueError(f"duration_seconds exceeds listing bound: maximum is {bound}")
    if min_duration_seconds is not None and duration < min_duration_seconds:
        raise ValueError(f"duration_seconds below listing minimum: {min_duration_seconds}")
    if timing is not None:
        assert lifecycle is not None
        if duration < timing.period_seconds:
            raise ValueError("recurring horizon must leave at least one whole period")
        expiry = datetime.fromtimestamp(floor(accepted_at.timestamp()), UTC) + timedelta(seconds=timing.approval_window_seconds)
        minimum = max(expiry, start) - start + timedelta(
            seconds=(lifecycle.delivery_deadline_seconds or 0) + timing.period_seconds,
        )
        minimum_seconds = minimum.days * 86400 + minimum.seconds
        if duration < minimum_seconds:
            raise ValueError(f"The horizon leaves no runway: minimum duration_seconds is {minimum_seconds}")
    return ResolvedHorizon(start.isoformat().replace("+00:00", "Z"), duration)
