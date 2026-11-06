"""The authority fixture's balance view and the fake client serving it."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from market_arkhai_payments import PaymentsTransportError
from market_arkhai_payments.fixtures import (
    FakePaymentsClient,
    PaymentsAuthority,
    build_signed_receipt,
    sign_receipt,
)
from market_arkhai_payments.receipts import transaction_id

from payment_terms import BUYER, DISPUTE, PAYEE, SERVICE

T0 = 1_800_000_000
HOUR = 3_600
DAY = 86_400
# A public deterministic test account no fixture ever funds or names in a
# mandate; never use it on a public network.
STRANGER = "55555555-5555-4555-8555-555555555555"


class Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def once_part(*, hold: dict[str, str] | None = None, stop: bool = False) -> dict[str, Any]:
    return {
        "kind": "once", "asset": "USD/2", "amount": "10000", "hold": hold or {"for": "P7D"},
        "authorities": {
            "stop": [{"account": PAYEE, "notice": "PT0S", "partialPeriod": "charged"}] if stop else [],
            "reverse": [PAYEE], "extend": [DISPUTE],
        },
        "maxHoldExtension": None,
    }


def rate_part() -> dict[str, Any]:
    return {
        "kind": "rate", "asset": "USD/2", "amount": "100", "period": "PT1H",
        "reserveAhead": "PT2H", "hold": {"for": "P1D"},
        "authorities": {"stop": [], "reverse": [PAYEE], "extend": [], "start": [PAYEE]},
        "maxHoldExtension": None,
    }


def mandate(part: dict[str, Any]) -> dict[str, Any]:
    return {"from": BUYER, "to": PAYEE, "parts": [part], "deal": "d" * 64,
            "fee": {"bps": 250}, "nonce": "balance-view", "expires": T0 + DAY}


def approved(part: dict[str, Any]) -> tuple[PaymentsAuthority, Clock, str]:
    clock = Clock(T0)
    engine = PaymentsAuthority(signer=SERVICE, clock=clock)
    engine.fund(BUYER, "USD/2", 50_000)
    terms = mandate(part)
    engine.approve(terms, account=BUYER)
    return engine, clock, transaction_id(terms)


def wire(engine: PaymentsAuthority, account: str) -> dict[str, Any]:
    return engine.balance(account).model_dump(mode="json", by_alias=True, exclude_none=True)


def iso(instant: int) -> str:
    return datetime.fromtimestamp(instant, timezone.utc).isoformat().replace("+00:00", "Z")


def test_a_payer_after_approval_has_the_gross_out_of_available_and_nothing_held():
    engine, _, _ = approved(once_part())
    assert wire(engine, BUYER) == {"available": {"USD/2": "40000"}, "held": []}


def test_a_payee_with_a_held_once_part_lists_it_once_timed_by_its_maturity():
    engine, _, transaction = approved(once_part())
    due = T0 + 7 * DAY
    assert wire(engine, PAYEE) == {"available": {}, "held": [{
        "address": f"hold:{transaction}:0:{due}", "transaction": transaction, "part": 0,
        "from": BUYER, "to": PAYEE, "asset": "USD/2", "balance": "10000",
        "fee": {"bps": 250}, "releaseAt": iso(due),
    }]}


def test_a_once_hold_maturing_between_two_reads_moves_into_available_net_of_fee():
    engine, clock, _ = approved(once_part())
    due = T0 + 7 * DAY
    clock.now = due - 1
    before = wire(engine, PAYEE)
    clock.now = due + 1
    after = wire(engine, PAYEE)
    assert [entry["balance"] for entry in before["held"]] == ["10000"]
    assert before["available"] == {}
    assert after == {"available": {"USD/2": "9750"}, "held": []}


def test_a_rate_part_lists_each_earned_periods_maturity_on_its_own():
    engine, clock, transaction = approved(rate_part())
    engine.submit(transaction, {"account": PAYEE, "requestId": "start", "event": {"kind": "start"}})
    clock.now = T0 + 2 * HOUR + 1
    held = wire(engine, PAYEE)["held"]
    dues = [T0 + HOUR + DAY, T0 + 2 * HOUR + DAY]
    assert [(entry["address"], entry["balance"], entry["releaseAt"]) for entry in held] == [
        (f"hold:{transaction}:0:{due}", "100", iso(due)) for due in dues
    ]


def test_an_after_stop_hold_before_its_stop_is_held_until_stop():
    engine, _, transaction = approved(once_part(hold={"afterStop": "P7D"}, stop=True))
    [entry] = wire(engine, PAYEE)["held"]
    assert (entry["address"], entry["balance"], entry["until"]) == (
        f"hold:{transaction}:0:until", "10000", "stop")
    assert "releaseAt" not in entry


def test_an_open_extension_with_no_end_holds_until_lift():
    engine, _, transaction = approved(once_part())
    engine.submit(transaction, {"account": DISPUTE, "requestId": "extend",
                                "event": {"kind": "extend", "part": 0}})
    [entry] = wire(engine, PAYEE)["held"]
    assert (entry["address"], entry["until"]) == (f"hold:{transaction}:0:until", "lift")


def test_an_after_stop_hold_awaiting_its_stop_stays_until_stop_under_an_open_extension():
    engine, _, transaction = approved(once_part(hold={"afterStop": "P7D"}, stop=True))
    engine.submit(transaction, {"account": DISPUTE, "requestId": "extend",
                                "event": {"kind": "extend", "part": 0}})
    [entry] = wire(engine, PAYEE)["held"]
    assert entry["until"] == "stop"


def test_an_account_the_engine_has_never_seen_has_an_empty_balance():
    engine, _, _ = approved(once_part())
    assert wire(engine, STRANGER) == {"available": {}, "held": []}


def test_a_part_seeded_with_a_zero_gross_receipt_lists_no_empty_hold():
    engine = PaymentsAuthority(signer=SERVICE, clock=Clock(T0))
    terms = mandate(once_part())
    body = build_signed_receipt(signer=SERVICE, mandate=terms, approved_at=T0).receipt.model_dump(
        mode="json", by_alias=True, exclude_none=True)
    body["parts"][0] |= {"gross": "0", "fee": "0", "net": "0"}
    engine.load(terms, sign_receipt(SERVICE, body))
    assert wire(engine, PAYEE) == {"available": {}, "held": []}


def test_the_fake_serves_the_engines_balance_view_and_records_the_read():
    fake = FakePaymentsClient(signer=SERVICE)
    fake.approve(mandate(once_part()))
    balance = fake.get_balance(PAYEE)
    assert balance == fake.engine.balance(PAYEE)
    assert [entry.root.balance.root for entry in balance.held] == ["10000"]
    assert fake.calls[-1] == ("get_balance", PAYEE)


def test_an_unavailable_fake_refuses_the_balance_read_as_a_transport_error():
    fake = FakePaymentsClient(signer=SERVICE)
    fake.unavailable = True
    with pytest.raises(PaymentsTransportError):
        fake.get_balance(PAYEE)
