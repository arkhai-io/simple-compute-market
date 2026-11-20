"""The authority fixture's reservation of a running rate part's further periods.

The payments service's scheduler reserves a started rate part further as time
passes; the engine's reads and commands never do, so a test programs that
decision through ``reserve``. Each case drives the engine itself on an injected
clock.
"""

from __future__ import annotations

from typing import Any

import pytest

from market_arkhai_payments import PaymentsAPIError
from market_arkhai_payments.fixtures import PaymentsAuthority
from market_arkhai_payments.receipts import transaction_id

from payment_terms import BUYER, PAYEE, SERVICE

T0 = 1_800_000_000
HOUR = 3_600
PRICE = 100
#: The Agreement's end: six one-hour periods after the start.
END = T0 + 6 * HOUR


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def rate_part() -> dict[str, Any]:
    """An hourly rate part reserving two hours ahead, ending at ``END``, which
    the payer may stop at once with the started period charged."""
    return {
        "kind": "rate", "asset": "USD/2", "amount": str(PRICE), "period": "PT1H",
        "reserveAhead": "PT2H", "hold": {"for": "P1D"},
        "end": {"at": END, "partialPeriod": "returned"},
        "authorities": {
            "stop": [{"account": BUYER, "notice": "PT0S", "partialPeriod": "charged"}],
            "reverse": [PAYEE], "extend": [], "start": [PAYEE],
        },
        "maxHoldExtension": None,
    }


def once_part() -> dict[str, Any]:
    return {
        "kind": "once", "asset": "USD/2", "amount": "10000", "hold": {"for": "P7D"},
        "authorities": {"stop": [], "reverse": [PAYEE], "extend": []},
        "maxHoldExtension": None,
    }


def approved(part: dict[str, Any], funds: int) -> tuple[PaymentsAuthority, Clock, str]:
    clock = Clock(T0)
    engine = PaymentsAuthority(signer=SERVICE, clock=clock)
    engine.fund(BUYER, "USD/2", funds)
    terms = {"from": BUYER, "to": PAYEE, "parts": [part], "deal": "d" * 64,
             "fee": {"bps": 250}, "nonce": "reservation", "expires": T0 + 86_400}
    engine.approve(terms, account=BUYER)
    return engine, clock, transaction_id(terms)


def started(funds: int) -> tuple[PaymentsAuthority, Clock, str]:
    """A rate part started at ``T0``; its reservation at the start covers three
    periods (two ahead and the slack into the third) when ``funds`` allow."""
    engine, clock, transaction = approved(rate_part(), funds)
    engine.submit(transaction, {"account": PAYEE, "requestId": "start", "event": {"kind": "start"}})
    return engine, clock, transaction


def rate_view(engine: PaymentsAuthority, transaction: str) -> dict[str, Any]:
    snapshot = engine.snapshot(transaction).model_dump(mode="json", by_alias=True, exclude_none=True)
    return snapshot["snapshot"]


def test_a_payer_funded_one_period_beyond_the_first_reservation_is_reserved_one_period_further():
    engine, clock, transaction = started(funds=4 * PRICE)
    first = rate_view(engine, transaction)
    assert first["fundedThrough"] == T0 + 3 * HOUR

    answer = engine.reserve(transaction, END)

    assert answer == [{"part": 0, "reserved_through": T0 + 4 * HOUR, "periods_added": 1}]
    view = rate_view(engine, transaction)
    assert view["fundedThrough"] == T0 + 4 * HOUR
    assert view["parts"][0]["rate"]["reservedThrough"] == T0 + 4 * HOUR
    assert engine.balance(BUYER).available["USD/2"].root == "0"
    # At that boundary the part's funds have run out: a terms stop there.
    clock.now = T0 + 4 * HOUR
    stopped = rate_view(engine, transaction)["parts"][0]
    assert (stopped["stop"]["cause"], stopped["stop"]["effectiveAt"]) == ("terms", T0 + 4 * HOUR)


@pytest.mark.parametrize("through", [END, END + 10 * HOUR])
def test_a_reservation_through_the_parts_end_stops_at_the_end(through):
    engine, _, transaction = started(funds=100 * PRICE)

    answer = engine.reserve(transaction, through)

    assert answer == [{"part": 0, "reserved_through": END, "periods_added": 3}]
    assert rate_view(engine, transaction)["fundedThrough"] == END
    # Nothing further to reserve.
    assert engine.reserve(transaction, through) == [{"part": 0, "reserved_through": END, "periods_added": 0}]


def unstarted() -> tuple[PaymentsAuthority, str]:
    engine, _, transaction = approved(rate_part(), 100 * PRICE)
    return engine, transaction


def once_only() -> tuple[PaymentsAuthority, str]:
    engine, _, transaction = approved(once_part(), 100_000)
    return engine, transaction


def stopped() -> tuple[PaymentsAuthority, str]:
    engine, _, transaction = started(funds=100 * PRICE)
    engine.submit(transaction, {"account": BUYER, "requestId": "stop", "event": {"kind": "stop"}})
    return engine, transaction


@pytest.mark.parametrize("make", [unstarted, once_only, stopped], ids=["unstarted", "once-only", "stopped"])
def test_a_transaction_with_no_running_rate_part_is_refused_with_nothing_changed(make):
    engine, transaction = make()
    before = (rate_view(engine, transaction), engine.balance(BUYER))

    with pytest.raises(PaymentsAPIError) as refused:
        engine.reserve(transaction, END)

    assert (refused.value.status_code, refused.value.code) == (409, "no_running_rate_part")
    assert (rate_view(engine, transaction), engine.balance(BUYER)) == before


def test_an_unknown_transaction_is_not_found():
    engine, _ = unstarted()
    with pytest.raises(PaymentsAPIError) as refused:
        engine.reserve("f" * 64, END)
    assert (refused.value.status_code, refused.value.code) == (404, "transaction_not_found")


def test_without_a_reservation_time_past_the_first_reservation_stops_the_part_there():
    engine, clock, transaction = started(funds=100 * PRICE)
    clock.now = T0 + 5 * HOUR
    part = rate_view(engine, transaction)["parts"][0]
    assert (part["stop"]["cause"], part["stop"]["effectiveAt"]) == ("terms", T0 + 3 * HOUR)
