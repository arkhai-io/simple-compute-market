"""The payments kit's real client against the double's app, in process.

The tests drive the app through ``PaymentsClient`` over an in-process transport
wherever the client can make the call, so the routes, bodies and error codes are
the ones the kit's client sends and reads. A request the client will not send —
one without a token, an approval whose Agreement is not the mandate's deal, or a
body its models refuse — and the mandate read, for which it has no call, are built
by hand, each with its reason beside it. The wall clock is injected; the rate
and hold cases move time through the double's clock control, as a lane moves it.

The suite claims the surface the engine serves: approval, attachment, receipts,
snapshots, the balance, and the rate and hold surface — rate parts and payee-only
``start``, ``stop`` with notice and the earliest pending stop, per-part ``end``,
funding exhaustion, ``afterStop`` holds, partial ``reverse`` before and after a
stop, and ``extend`` and ``lift`` with their published refusals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.models import ApiError, Mandate
from market_arkhai_payments.receipts import transaction_id, verify_receipt, verify_snapshot

from support import (
    AGREEMENT,
    AUTHORITY,
    DAY,
    HOUR,
    PAYER,
    STRANGER,
    T0,
    UNKNOWN,
    WATCHER,
    Lane,
    available,
    mandate,
    refusal,
)


@pytest.fixture
def lane() -> Iterator[Lane]:
    lane = Lane()
    with lane.http:
        yield lane


# --- the once-only journey ------------------------------------------------------


def test_a_once_payment_is_approved_attached_read_and_reversed(lane: Lane) -> None:
    buyer, seller = lane.client("buyer"), lane.client("seller")
    terms = mandate(lane)
    transaction = transaction_id(terms)
    assert available(lane, "buyer") == {"USD/6": str(lane.funding())}

    receipt = buyer.approve(terms)
    assert verify_receipt(receipt, lane.directory.receipt_identity, mandate=terms,
                          agreement_json=AGREEMENT, livemode=False)
    assert available(lane, "buyer") == {"USD/6": str(lane.funding() - 1_000_000)}
    assert [hold.root.balance.root for hold in
            seller.get_balance(lane.account("seller")).held] == ["1000000"]

    stored = seller.attach_agreement(transaction, AGREEMENT)
    assert stored.sha256.root == terms["deal"]
    for client in (buyer, seller):
        snapshot = client.get_transaction(transaction)
        assert verify_snapshot(snapshot, lane.directory.receipt_identity, mandate=terms,
                               agreement_json=AGREEMENT, livemode=False)
        assert [attachment.sha256.root for attachment in snapshot.snapshot.attachments] == [
            terms["deal"]]

    reversed_once = seller.reverse(transaction)
    assert seller.reverse(transaction) == reversed_once
    assert available(lane, "buyer") == {"USD/6": str(lane.funding())}
    assert seller.get_balance(lane.account("seller")).held == []


def test_an_approval_with_its_agreement_stores_the_attachment(lane: Lane) -> None:
    terms = mandate(lane)

    lane.client("buyer").approve(terms, agreement=AGREEMENT)

    snapshot = lane.client("seller").get_transaction(transaction_id(terms))
    assert [attachment.sha256.root for attachment in snapshot.snapshot.attachments] == [
        terms["deal"]]


# --- retries ----------------------------------------------------------------------


def test_a_retry_after_the_mandate_expires_returns_the_original_receipt(lane: Lane) -> None:
    buyer = lane.client("buyer")
    terms = mandate(lane)
    original = buyer.approve(terms)

    lane.clock.now = terms["expires"] + 1

    assert buyer.approve(terms) == original


def test_a_retry_the_buyers_balance_no_longer_covers_returns_the_original_receipt(
        lane: Lane) -> None:
    buyer = lane.client("buyer")
    half = lane.funding() // 2
    terms = mandate(lane, amount=str(half))
    original = buyer.approve(terms)
    buyer.approve(mandate(lane, amount=str(lane.funding() - half), nonce="suite-drain"))
    assert available(lane, "buyer") == {"USD/6": "0"}

    assert buyer.approve(terms) == original


# --- refusals ---------------------------------------------------------------------


def test_a_request_without_a_token_is_refused_as_unauthenticated(lane: Lane) -> None:
    # Rejection path: the kit's client always sends its token, so the request
    # without one is built by hand. Its error code is read beside its status,
    # here and in the other rejection paths, because the code is the contract
    # the double mirrors; it is read through the published ApiError model.
    answer = lane.http.get(f"/balances/{lane.account('buyer')}")

    assert answer.status_code == 401
    assert ApiError.model_validate(answer.json()).error.value == "authentication_required"


def test_a_wrong_token_is_refused_as_unauthenticated(lane: Lane) -> None:
    # A public test value no fixture issues; never for a public network.
    client = lane.token_client("not-a-token-the-double-issued")

    assert refusal(client.get_balance, lane.account("buyer")) == (
        401, "authentication_required")


def test_only_the_payer_may_approve(lane: Lane) -> None:
    assert refusal(lane.client("seller").approve, mandate(lane)) == (
        403, "caller_not_authorized")


def test_a_stranger_may_not_read_a_transaction_or_its_mandate(lane: Lane) -> None:
    terms = mandate(lane)
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    assert refusal(lane.token_client(STRANGER[1]).get_transaction, transaction) == (
        403, "caller_not_authorized")
    assert _mandate_read(lane, STRANGER[1], transaction).status_code == 403


def test_an_account_named_only_in_an_authority_may_read_the_transaction(lane: Lane) -> None:
    terms = mandate(lane)
    terms["parts"][0]["authorities"]["extend"].append(WATCHER[0])
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    snapshot = lane.token_client(WATCHER[1]).get_transaction(transaction)

    assert snapshot.snapshot.transaction.root == transaction
    read = _mandate_read(lane, WATCHER[1], transaction)
    assert read.status_code == 200
    assert transaction_id(Mandate.model_validate(read.json())) == transaction


def test_an_account_may_read_only_its_own_balance(lane: Lane) -> None:
    assert refusal(lane.client("buyer").get_balance, lane.account("seller")) == (
        403, "caller_not_authorized")


@pytest.mark.parametrize(("changes", "expected"), [
    ({"expires": T0}, (409, "mandate_expired")),
    ({"parts": [{"kind": "once", "asset": "USD/2", "amount": "100", "hold": {"for": "P7D"},
                 "authorities": {"stop": [], "reverse": [], "extend": []},
                 "maxHoldExtension": None}]}, (422, "unsupported_asset")),
    ({"fee": {"bps": 100}}, (422, "fee_mismatch")),
    ({"to": UNKNOWN}, (404, "account_not_found")),
])
def test_a_new_approval_the_service_would_not_admit_is_refused(
        lane: Lane, changes: dict[str, Any], expected: tuple[int, str]) -> None:
    assert refusal(lane.client("buyer").approve, mandate(lane, **changes)) == expected
    assert available(lane, "buyer") == {"USD/6": str(lane.funding())}


def test_an_approval_the_buyers_balance_does_not_cover_is_refused(lane: Lane) -> None:
    terms = mandate(lane, amount=str(lane.funding() + 1))

    assert refusal(lane.client("buyer").approve, terms) == (409, "insufficient_funds")


def test_an_agreement_that_is_not_the_deal_is_refused(lane: Lane) -> None:
    terms = mandate(lane)
    lane.client("buyer").approve(terms)

    other = {"listing": "another-deal"}
    assert refusal(lane.client("seller").attach_agreement, transaction_id(terms), other) == (
        409, "deal_mismatch")


def test_an_approval_attaching_another_agreement_is_refused_after_the_funds_check(
        lane: Lane) -> None:
    # Rejection path: the kit's client refuses to send an Agreement that is not
    # the mandate's deal, so the approval carrying one is built by hand.
    token = lane.directory.role("buyer").token
    funded = {"mandate": mandate(lane),
              "attachments": [{"kind": "deal", "content": {"listing": "another-deal"}}]}
    unfunded = {"mandate": mandate(lane, amount=str(lane.funding() + 1)),
                "attachments": funded["attachments"]}

    for body, expected in ((funded, (409, "deal_mismatch")),
                           (unfunded, (409, "insufficient_funds"))):
        answer = lane.http.post("/transactions", json=body,
                                headers={"Authorization": f"Bearer {token}"})
        assert (answer.status_code, ApiError.model_validate(answer.json()).error.value) == (
            expected)


def test_a_malformed_body_is_an_invalid_request(lane: Lane) -> None:
    # Rejection path: the kit's client cannot send a body its models refuse.
    token = lane.directory.role("buyer").token
    answer = lane.http.post("/transactions", content=b"{\"mandate\": {}}",
                            headers={"Authorization": f"Bearer {token}"})

    assert answer.status_code == 400
    assert ApiError.model_validate(answer.json()).error.value == "invalid_request"


def test_the_dispute_authoritys_token_authenticates_as_its_account(lane: Lane) -> None:
    # The mediation double acts as this account, extending, reversing and lifting
    # under the token the fixture gives it.
    authority = lane.account("dispute_authority")

    assert lane.client("dispute_authority").get_balance(authority).held == []
    assert refusal(lane.client("dispute_authority").get_balance, lane.account("buyer")) == (
        403, "caller_not_authorized")


def _mandate_read(lane: Lane, token: str, transaction: str) -> httpx.Response:
    # The kit's client has no call for the mandate route, so it is read with a
    # request built by hand; the published Mandate model reads its body.
    return lane.http.get(f"/transactions/{transaction}/mandate",
                         headers={"Authorization": f"Bearer {token}"})


# --- the rate and hold surface --------------------------------------------------
#
# A rate part here earns 1000 minor units an hour and reserves two hours ahead, so
# an approval at T0 reserves two periods; a start refills one period more from a
# funded payer. Time moves only through the clock control.


def rate_terms(lane: Lane, *, payer: str = "buyer", nonce: str,
               stop: list[dict[str, Any]] | None = None, **part: Any) -> dict[str, Any]:
    seller = lane.account("seller")
    terms = {
        "kind": "rate", "asset": "USD/6", "amount": "1000", "period": "PT1H",
        "reserveAhead": "PT2H", "hold": {"for": "P1D"},
        "authorities": {"stop": stop or [], "reverse": [seller], "extend": [AUTHORITY[0]],
                        "start": [seller]},
        "maxHoldExtension": None,
    } | part
    return mandate(lane, nonce=nonce, parts=[terms], **{"from": lane.account(payer)})


def once_terms(lane: Lane, *, nonce: str, **part: Any) -> dict[str, Any]:
    seller = lane.account("seller")
    terms = {
        "kind": "once", "asset": "USD/6", "amount": "1000000", "hold": {"for": "P1D"},
        "authorities": {"stop": [], "reverse": [seller], "extend": [AUTHORITY[0]]},
        "maxHoldExtension": None,
    } | part
    return mandate(lane, nonce=nonce, parts=[terms])


def stopper(account: str, notice: str) -> dict[str, str]:
    return {"account": account, "notice": notice, "partialPeriod": "charged"}


def snapshot(lane: Lane, transaction: str) -> dict[str, Any]:
    signed = lane.client("seller").get_transaction(transaction)
    body: dict[str, Any] = signed.snapshot.model_dump(mode="json", by_alias=True,
                                                      exclude_none=True)
    return body


def event(lane: Lane, role: str | tuple[str, str], transaction: str, body: dict[str, Any],
          request_id: str) -> Any:
    client = lane.token_client(role[1]) if isinstance(role, tuple) else lane.client(role)
    return client.submit_event(transaction, body, request_id=request_id)


def advance(lane: Lane, seconds: int) -> None:
    with lane.controls() as controls:
        controls.advance_clock(seconds)


def started(lane: Lane, terms: dict[str, Any], payer: str | tuple[str, str] = "buyer") -> str:
    client = lane.token_client(payer[1]) if isinstance(payer, tuple) else lane.client(payer)
    client.approve(terms)
    transaction = transaction_id(terms)
    event(lane, "seller", transaction, {"kind": "start"}, "start")
    return transaction


def test_only_the_payee_starts_a_rate_part_and_it_earns_as_the_clock_moves(lane: Lane) -> None:
    terms = rate_terms(lane, nonce="rate-earn")
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    assert refusal(lane.client("buyer").submit_event, transaction, {"kind": "start"},
                   request_id="buyer-start") == (403, "caller_not_authorized")
    event(lane, "seller", transaction, {"kind": "start"}, "start")
    assert snapshot(lane, transaction)["fundedThrough"] == T0 + 3 * HOUR

    advance(lane, 2 * HOUR)

    [part] = snapshot(lane, transaction)["parts"]
    assert part["started"] == T0
    assert part["rate"]["periodsEarned"] == "2" and part["rate"]["grossEarned"] == "2000"
    assert part["held"] == "2000"


def test_the_earliest_pending_stop_takes_effect_when_the_clock_reaches_it(lane: Lane) -> None:
    terms = rate_terms(lane, nonce="rate-stop", stop=[
        stopper(lane.account("buyer"), "PT2H"), stopper(lane.account("seller"), "PT1H")])
    transaction = started(lane, terms)

    event(lane, "buyer", transaction, {"kind": "stop"}, "payer-stop")
    assert snapshot(lane, transaction)["parts"][0]["pendingStop"]["at"] == T0 + 2 * HOUR
    event(lane, "seller", transaction, {"kind": "stop"}, "payee-stop")
    pending = snapshot(lane, transaction)["parts"][0]["pendingStop"]
    assert (pending["at"], pending["cause"]) == (T0 + HOUR, "payee")

    advance(lane, HOUR)

    [part] = snapshot(lane, transaction)["parts"]
    assert (part["stop"]["effectiveAt"], part["stop"]["cause"]) == (T0 + HOUR, "payee")
    assert "pendingStop" not in part
    assert part["rate"]["periodsEarned"] == "1"


def test_a_parts_end_stops_it_at_its_instant(lane: Lane) -> None:
    terms = rate_terms(lane, nonce="rate-end",
                       end={"at": T0 + 2 * HOUR, "partialPeriod": "charged"})
    transaction = started(lane, terms)

    advance(lane, 2 * HOUR)

    body = snapshot(lane, transaction)
    [part] = body["parts"]
    assert (part["stop"]["effectiveAt"], part["stop"]["cause"]) == (T0 + 2 * HOUR, "terms")
    # The end's stop names its part; an exhaustion stop names none.
    assert body["events"][-1]["event"] == {"kind": "stop", "part": 0}


def test_a_payer_whose_funding_runs_out_is_stopped_at_its_funded_through(lane: Lane) -> None:
    with lane.controls() as controls:
        controls.fund(PAYER[0], 2000)
    terms = rate_terms(lane, payer="payer", nonce="rate-exhaust")
    transaction = started(lane, terms, payer=PAYER)
    assert snapshot(lane, transaction)["fundedThrough"] == T0 + 2 * HOUR

    advance(lane, 2 * HOUR)

    body = snapshot(lane, transaction)
    [part] = body["parts"]
    assert (part["stop"]["effectiveAt"], part["stop"]["cause"]) == (T0 + 2 * HOUR, "terms")
    assert body["events"][-1]["event"] == {"kind": "stop"}
    assert "fundedThrough" not in body


def test_an_after_stop_hold_releases_once_the_clock_passes_it(lane: Lane) -> None:
    terms = once_terms(lane, nonce="after-stop", hold={"afterStop": "PT1H"}, authorities={
        "stop": [stopper(lane.account("seller"), "PT0S")],
        "reverse": [lane.account("seller")], "extend": [AUTHORITY[0]]})
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    event(lane, "seller", transaction, {"kind": "stop"}, "stop")
    assert snapshot(lane, transaction)["parts"][0]["status"] == "held"
    advance(lane, HOUR - 1)
    assert snapshot(lane, transaction)["parts"][0]["status"] == "held"

    advance(lane, 1)

    [part] = snapshot(lane, transaction)["parts"]
    assert (part["status"], part["held"], part["released"]) == ("released", "0", "1000000")
    assert available(lane, "seller") == {"USD/6": "975000"}


def test_a_partial_reverse_lands_before_and_after_a_stop(lane: Lane) -> None:
    terms = rate_terms(lane, nonce="rate-reverse",
                       stop=[stopper(lane.account("seller"), "PT0S")])
    transaction = started(lane, terms)
    advance(lane, 2 * HOUR)

    event(lane, "seller", transaction, {"kind": "reverse", "part": 0, "amount": "500"},
          "reverse-before")
    assert snapshot(lane, transaction)["parts"][0]["held"] == "1500"
    event(lane, "seller", transaction, {"kind": "stop"}, "stop")
    event(lane, "seller", transaction, {"kind": "reverse", "part": 0, "amount": "500"},
          "reverse-after")

    [part] = snapshot(lane, transaction)["parts"]
    assert part["stop"]["effectiveAt"] == T0 + 2 * HOUR
    assert (part["held"], part["reversed"]) == ("1000", "1000")
    assert refusal(lane.client("seller").submit_event, transaction,
                   {"kind": "reverse", "part": 0, "amount": "5000"},
                   request_id="reverse-too-much") == (409, "insufficient_held_funds")


def test_an_extension_is_lifted_once_and_refused_after(lane: Lane) -> None:
    terms = once_terms(lane, nonce="extend-lift")
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    extended = event(lane, AUTHORITY, transaction, {"kind": "extend", "part": 0}, "extend")
    assert snapshot(lane, transaction)["parts"][0]["extensions"] == [{"ref": extended.sequence}]
    event(lane, AUTHORITY, transaction, {"kind": "lift", "part": 0, "ref": extended.sequence},
          "lift")

    assert snapshot(lane, transaction)["parts"][0]["extensions"] == []
    assert refusal(lane.token_client(AUTHORITY[1]).submit_event, transaction,
                   {"kind": "lift", "part": 0, "ref": extended.sequence},
                   request_id="lift-again") == (409, "extension_closed")
    assert refusal(lane.token_client(AUTHORITY[1]).submit_event, transaction,
                   {"kind": "lift", "part": 0, "ref": 99},
                   request_id="lift-unknown") == (404, "extension_not_found")


def test_a_released_once_part_cannot_be_extended(lane: Lane) -> None:
    terms = once_terms(lane, nonce="extend-late")
    lane.client("buyer").approve(terms)
    transaction = transaction_id(terms)

    advance(lane, DAY)

    assert snapshot(lane, transaction)["parts"][0]["status"] == "released"
    assert refusal(lane.token_client(AUTHORITY[1]).submit_event, transaction,
                   {"kind": "extend", "part": 0},
                   request_id="extend-late") == (409, "hold_not_extendable")
