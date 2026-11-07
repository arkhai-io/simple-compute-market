"""The payments kit's real client against the double's app, in process.

The tests drive the app through ``PaymentsClient`` over an in-process transport
wherever the client can make the call, so the routes, bodies and error codes are
the ones the kit's client sends and reads. A request the client will not send —
one without a token, an approval whose Agreement is not the mandate's deal, or a
body its models refuse — and the mandate read, for which it has no call, are built
by hand, each with its reason beside it. The clock is injected. The suite claims
only the once-only surface: approval, attachment, receipts, snapshots, the seller's
reverse and the balance.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from market_arkhai_payments import PaymentsAPIError, PaymentsClient
from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.models import ApiError, Mandate
from market_arkhai_payments.receipts import transaction_id, verify_receipt, verify_snapshot

from payments_lane_double.accounts import AccountDirectory, parse_accounts
from payments_lane_double.app import create_app

from conftest import Clock, committed_accounts

T0 = 1_800_000_000
DAY = 86_400
# Loopback, so the client builds its connection without reading proxy settings
# from the environment, which would mount a proxy ahead of the in-process transport.
ORIGIN = "https://127.0.0.1:8443"
# Public development tokens and accounts this suite adds to the committed
# directory; never use them on a public network. The stranger is no party to any
# mandate here; the watcher is named only in a part's authorities.
STRANGER = ("00000000-0000-4000-8000-0000000000e1", "lane-double-suite-stranger-token")
WATCHER = ("00000000-0000-4000-8000-0000000000e2", "lane-double-suite-watcher-token")
# A well-formed account the directory does not hold; a public test value, never
# for a public network.
UNKNOWN = "99999999-9999-4999-8999-999999999999"
AGREEMENT = {"listing": "lane-double-suite", "price": "1000000"}


def suite_directory() -> AccountDirectory:
    document = committed_accounts()
    for role, (account, token) in (("stranger", STRANGER), ("watcher", WATCHER)):
        document["accounts"][role] = {"account": account, "token": token}
    return parse_accounts(document)


class Lane:
    """One app over a fresh engine, and the kit's client for each account."""

    def __init__(self) -> None:
        self.clock = Clock(T0)
        self.directory = suite_directory()
        self.http = TestClient(create_app(self.directory, clock=self.clock), base_url=ORIGIN)

    def transport(self) -> httpx.MockTransport:
        def forward(request: httpx.Request) -> httpx.Response:
            answer = self.http.request(request.method, str(request.url),
                                       headers=request.headers, content=request.content)
            return httpx.Response(answer.status_code, headers=answer.headers,
                                  content=answer.content)
        return httpx.MockTransport(forward)

    def client(self, role: str) -> PaymentsClient:
        token = self.directory.role(role).token
        assert token is not None
        return self.token_client(token)

    def token_client(self, token: str) -> PaymentsClient:
        return PaymentsClient(ORIGIN, api_key=token, transport=self.transport())

    def account(self, role: str) -> str:
        return self.directory.role(role).account

    def funding(self) -> int:
        return self.directory.role("buyer").funding


@pytest.fixture
def lane() -> Iterator[Lane]:
    lane = Lane()
    with lane.http:
        yield lane


def mandate(lane: Lane, *, amount: str = "1000000", nonce: str = "suite-1",
            agreement: dict[str, Any] = AGREEMENT, **changes: Any) -> dict[str, Any]:
    terms: dict[str, Any] = {
        "from": lane.account("buyer"), "to": lane.account("seller"),
        "parts": [{
            "kind": "once", "asset": "USD/6", "amount": amount, "hold": {"for": "P7D"},
            "authorities": {"stop": [], "reverse": [lane.account("seller")],
                            "extend": [lane.account("dispute_authority")]},
            "maxHoldExtension": None,
        }],
        "deal": agreement_hash(agreement), "fee": {"bps": 250}, "nonce": nonce,
        "expires": T0 + DAY,
    }
    terms.update(changes)
    return terms


def refusal(call: Any, *args: Any, **kwargs: Any) -> tuple[int, str]:
    with pytest.raises(PaymentsAPIError) as refused:
        call(*args, **kwargs)
    return refused.value.status_code, refused.value.code


def available(lane: Lane, role: str) -> dict[str, str]:
    balance = lane.client(role).get_balance(lane.account(role))
    return {asset: value.root for asset, value in balance.available.items()}


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


def test_the_dispute_authoritys_account_cannot_authenticate(lane: Lane) -> None:
    authority = lane.account("dispute_authority")

    assert lane.directory.role("dispute_authority").token is None
    assert refusal(lane.token_client(authority).get_balance, authority) == (
        401, "authentication_required")


def _mandate_read(lane: Lane, token: str, transaction: str) -> httpx.Response:
    # The kit's client has no call for the mandate route, so it is read with a
    # request built by hand; the published Mandate model reads its body.
    return lane.http.get(f"/transactions/{transaction}/mandate",
                         headers={"Authorization": f"Bearer {token}"})
