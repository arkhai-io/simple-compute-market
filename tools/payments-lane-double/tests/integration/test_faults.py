"""The double's transport faults, as the payments kit's client meets them over a real server.

The app runs under uvicorn on loopback, so a fault reaches the kit's
``PaymentsClient`` as it would in a lane: a connection closed mid-response, which
the client raises as ``PaymentsTransportError``, never an HTTP status. Rules are
installed and removed through the typed control client against the same server.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from lane_double_controls import ControlClient, Rule
from market_arkhai_payments import PaymentsClient, PaymentsTransportError
from market_arkhai_payments.receipts import transaction_id

from payments_lane_double.app import create_app

from conftest import Clock
from loopback import serving
from support import T0, mandate, suite_directory


@dataclass
class Served:
    clock: Clock
    buyer: PaymentsClient
    controls: ControlClient
    funding: int
    buyer_account: str


@pytest.fixture
def served() -> Iterator[Served]:
    directory = suite_directory()
    buyer = directory.role("buyer")
    assert buyer.token is not None
    clock = Clock(T0)
    with serving(create_app(directory, clock=clock)) as origin:
        with PaymentsClient(origin, api_key=buyer.token) as client, ControlClient(
                origin, token=directory.control_token) as controls:
            yield Served(clock, client, controls, buyer.funding, buyer.account)


class _Accounts:
    """The account lookups ``support.mandate`` makes, without an in-process lane."""

    def __init__(self) -> None:
        self.directory = suite_directory()

    def account(self, role: str) -> str:
        return self.directory.role(role).account


def _available(served: Served) -> str:
    return served.buyer.get_balance(served.buyer_account).available["USD/6"].root


def test_an_approval_whose_response_is_dropped_is_retried_to_its_original_receipt(
        served: Served) -> None:
    terms = mandate(_Accounts())  # type: ignore[arg-type]
    served.controls.install_rule(Rule.model_validate({
        "rule_id": "lose-approval", "match": {"route": "transactions"},
        "drop_response_after_commit": True}))

    with pytest.raises(PaymentsTransportError):
        served.buyer.approve(terms)
    [view] = served.controls.rules().rules
    assert view.matched == 1
    served.controls.delete_rule("lose-approval")
    # The lost approval committed: the buyer is already debited and its snapshot
    # exists before any retry.
    assert _available(served) == str(served.funding - 1_000_000)
    committed = served.buyer.get_transaction(transaction_id(terms)).snapshot.receipt

    served.clock.now = T0 + 60
    retried = served.buyer.approve(terms)

    # The retry, a minute later, returns the receipt approved at T0, with no
    # second debit.
    assert retried == committed
    assert retried.receipt.approvedAt == T0
    assert _available(served) == str(served.funding - 1_000_000)


def test_unavailable_abandons_every_api_response_while_the_controls_answer(
        served: Served) -> None:
    served.controls.install_rule(Rule.model_validate({
        "rule_id": "down", "match": {}, "unavailable": True}))

    with pytest.raises(PaymentsTransportError):
        served.buyer.get_balance(served.buyer_account)
    with pytest.raises(PaymentsTransportError):
        served.buyer.approve(mandate(_Accounts()))  # type: ignore[arg-type]
    assert served.controls.status().offset_seconds == 0
    [view] = served.controls.rules().rules
    assert (view.rule.rule_id, view.matched) == ("down", 2)

    served.controls.delete_rule("down")

    assert _available(served) == str(served.funding)
