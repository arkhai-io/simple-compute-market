"""The seller's horizon resolution and the buyer's check of a signed horizon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_core.schemas import (
    RateValue, SettlementOption, SettlementPrice, derive_settlement_option_id,
)
from market_deal_lifecycle.terms import (
    Adjudication, AuthorityRequirements, DisputeAuthority, EarlyTermination,
    Entitlement, LifecycleTerms, TermContext, encode_terms,
)
from market_settlement_runtime.horizon import (
    RateTermTiming, bound_seconds, check_accepted_horizon, resolve_horizon,
)

MECHANISM = "fixture.rate.v1"
# A fictional authority: the origin is a reserved name that resolves nowhere.
AUTHORITY = DisputeAuthority(
    interface="fixture.mediation.v1", origin="https://mediation.invalid",
    account="fixture-account", record_key="fixture-record", params={},
)
ACCEPTED_AT = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(microseconds=900000)
START = "2030-01-01T00:00:00Z"


def _option(*, deadline: int | None = 1200) -> SettlementOption:
    lifecycle = encode_terms(LifecycleTerms(
        adjudication=Adjudication(version=1, dispute=AUTHORITY, dispute_window_seconds=604800,
                                  case_hold_max_seconds=None),
        early_termination=EarlyTermination(
            version=1, settles_through="last_boundary", premature_stop_penalty="1000",
            entitlements={"payer": Entitlement(notice_seconds=0, settles_through="started_period")},
        ),
        **({"delivery_deadline_seconds": deadline} if deadline is not None else {}),
    ))
    price = SettlementPrice(asset="USD/6", rates=[RateValue(field="amount", per="hour", value=2500000)])
    settlement = {"schema": MECHANISM, "period": "PT15M", "reserve_ahead_seconds": 1800}
    return SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
        price=price, settlement=settlement, lifecycle=lifecycle,
    )


def _timing(_option: SettlementOption) -> RateTermTiming:
    return RateTermTiming(900, 900, TermContext(
        mechanism=MECHANISM, has_adapter=True, dispute_interfaces=frozenset({AUTHORITY.interface}),
        authority=AuthorityRequirements(AUTHORITY, frozenset({MECHANISM}), 60, None),
        supported_partial_periods=frozenset({"charged", "returned"}),
    ))


def _resolve(**changes):
    arguments = dict(
        requested_duration_seconds=None, requested_start_utc=None, accepted_at=ACCEPTED_AT,
        max_duration_seconds=7201, available_until_utc=None, option=_option(),
        rate_terms={MECHANISM: _timing},
    )
    return resolve_horizon(**{**arguments, **changes})


def test_an_omitted_recurring_horizon_binds_the_earliest_bound_at_a_whole_second_start():
    resolved = _resolve()
    assert (resolved.start_utc, resolved.duration_seconds) == (START, 7201)
    assert _resolve(available_until_utc="2030-01-01T01:00:01Z").duration_seconds == 3601


def test_a_fractional_limiting_absolute_bound_is_floored_rather_than_refused():
    # 72000.4 seconds after the resolved start.
    resolved = _resolve(max_duration_seconds=None, available_until_utc="2030-01-01T20:00:00.4Z")
    assert resolved.duration_seconds == 72000


def test_an_explicit_shorter_horizon_binds_unchanged_without_rounding_to_periods():
    assert _resolve(requested_duration_seconds=3001).duration_seconds == 3001


def test_the_horizon_leaves_no_runway():
    # A 15-minute period and approval window and a 1200-second deadline need 50 minutes.
    with pytest.raises(ValueError, match="The horizon leaves no runway: minimum duration_seconds is 3000"):
        _resolve(requested_duration_seconds=900)
    assert _resolve(requested_duration_seconds=3000).duration_seconds == 3000


@pytest.mark.parametrize(("changes", "message"), [
    ({"requested_duration_seconds": 899}, "one whole period"),
    ({"requested_duration_seconds": 7202}, "exceeds listing bound: maximum is 7201"),
    ({"requested_start_utc": "2030-01-01T00:00:00.1Z"}, "whole seconds"),
    ({"available_until_utc": "2029-01-01T00:00:00Z"}, "expired"),
    ({"max_duration_seconds": None}, "finite listing bound"),
    ({"option": None}, "reserved duration_seconds is required"),
    ({"rate_terms": {}}, "projection unavailable"),
    ({"available_until_utc": "2031-01-01T00:00:00+01:00"}, "aware UTC"),
])
def test_unacceptable_horizons_are_refused(changes, message):
    with pytest.raises(ValueError, match=message):
        _resolve(**changes)


def test_a_reserved_duration_must_fit_both_bounds_and_keeps_its_fractional_start():
    reserved = _resolve(option=None, requested_duration_seconds=3600)
    assert reserved.start_utc == "2030-01-01T00:00:00.900000Z"
    with pytest.raises(ValueError, match="exceeds listing bound"):
        _resolve(option=None, requested_duration_seconds=3600, available_until_utc="2030-01-01T00:30:00Z")


def test_a_nonpositive_relative_bound_states_no_limit():
    start = datetime(2030, 1, 1, tzinfo=UTC)
    assert bound_seconds(start, max_duration_seconds=0, available_until_utc=None) is None
    assert bound_seconds(start, max_duration_seconds=-1, available_until_utc="2030-01-01T00:00:10.9Z") == 10


def _check(**changes):
    arguments = dict(
        start_utc=START, duration_seconds=72000, requested_duration_seconds=None,
        max_duration_seconds=72000, available_until_utc=None,
    )
    check_accepted_horizon(**{**arguments, **changes})


def test_the_buyer_accepts_the_default_bound_for_an_omitted_horizon():
    _check()
    _check(max_duration_seconds=None, available_until_utc="2030-01-01T20:00:00.4Z")


def test_the_buyer_accepts_its_own_shorter_horizon():
    _check(duration_seconds=36000, requested_duration_seconds=36000)


def test_the_buyer_refuses_a_horizon_above_the_advertised_bound():
    # A signed 21-hour duration under a 20-hour bound.
    with pytest.raises(ValueError, match="exceeds the listing's bound of 72000"):
        _check(duration_seconds=75600, requested_duration_seconds=75600)


def test_the_buyer_refuses_a_horizon_ending_after_absolute_availability():
    with pytest.raises(ValueError, match="exceeds the listing's bound of 3600"):
        _check(duration_seconds=7200, requested_duration_seconds=7200, max_duration_seconds=None,
               available_until_utc="2030-01-01T01:00:00Z")


@pytest.mark.parametrize(("changes", "message"), [
    ({"duration_seconds": 36000, "requested_duration_seconds": 30000}, "differs from the requested"),
    ({"duration_seconds": 36000}, "differs from the default horizon 72000"),
    ({"max_duration_seconds": None}, "needs a finite listing bound"),
    ({"duration_seconds": 0}, "positive whole seconds"),
    ({"start_utc": "2030-01-01T00:00:00"}, "aware UTC"),
])
def test_the_buyer_refuses_a_horizon_it_did_not_ask_for(changes, message):
    with pytest.raises(ValueError, match=message):
        _check(**changes)
