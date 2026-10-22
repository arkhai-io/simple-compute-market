"""An outstanding payment purchase is refunded and released, and only that."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from core_buyer.negotiation_client import AuthenticatedHTTPError
from storefront_client import StorefrontClientError

from tests.e2e.roles.helpers.payment_compensation import (
    Purchase,
    PurchaseCompensation,
    UnresolvedPayment,
    fulfillment_or_none,
    purchase_from_run_logs,
    refund_may_clear,
)


class Refused(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"refund refused with {status_code}")
        self.status_code = status_code


class Seller:
    """The storefront and payments boundary, answering as each case sets it."""

    def __init__(self, *, delivered: dict[str, Any] | None = None,
                 refusals: list[int] | None = None,
                 status_failures: int = 0) -> None:
        self.delivered = delivered
        self.refusals = list(refusals or [])
        self.status_failures = status_failures
        self.calls: list[tuple[str, str]] = []
        self.now = 0.0

    def status(self, negotiation_id: str) -> dict[str, Any] | None:
        self.calls.append(("status", negotiation_id))
        if self.status_failures:
            self.status_failures -= 1
            raise ConnectionError("storefront unreachable")
        return self.delivered

    def refund(self, negotiation_id: str) -> None:
        self.calls.append(("refund", negotiation_id))
        if self.refusals:
            raise Refused(self.refusals.pop(0))

    def release(self, negotiation_id: str, status: dict[str, Any]) -> None:
        self.calls.append(("release", status["fulfillment_id"]))

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def compensation(self, run_dir: Path) -> PurchaseCompensation:
        return PurchaseCompensation(
            run_dir=run_dir,
            status=self.status,
            refund=self.refund,
            release=self.release,
            retryable=lambda error: getattr(error, "status_code", None) in (409, 503),
            refund_window=10.0,
            retry_interval=2.0,
            clock=lambda: self.now,
            sleep=self.sleep,
        )


def _run_log(run_dir: Path, *events: dict[str, Any], tail: str = "") -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event) for event in events]
    (run_dir / "run.jsonl").write_text("\n".join(lines) + "\n" + tail, encoding="utf-8")
    return run_dir


_ACCEPTED = {"event": "agreement_accepted", "negotiation_id": "negotiation-1"}
_APPROVED = {"event": "payment_approved", "transaction_id": "transaction-1"}


def _run(steps) -> None:
    for _, step in steps:
        step()


def test_a_run_log_written_until_a_crash_still_names_the_purchase(tmp_path: Path):
    run_dir = _run_log(tmp_path, {"event": "run_started"}, _ACCEPTED, _APPROVED,
                       tail='{"event": "run_en')

    assert purchase_from_run_logs(run_dir) == Purchase("negotiation-1", "transaction-1")
    assert purchase_from_run_logs(tmp_path / "absent") == Purchase()


def test_no_purchase_and_no_approved_payment_are_left_alone(tmp_path: Path):
    for run_dir in (tmp_path / "no-run", _run_log(tmp_path / "unpaid", _ACCEPTED)):
        seller = Seller(delivered={"fulfillment_id": "f-1", "state": "active"})

        _run(seller.compensation(run_dir).steps(settled=False))

        assert seller.calls == []


def test_an_undelivered_purchase_is_refunded_and_nothing_is_released(tmp_path: Path):
    seller = Seller(delivered=None)

    _run(seller.compensation(_run_log(tmp_path, _ACCEPTED, _APPROVED)).steps(settled=False))

    assert seller.calls == [("status", "negotiation-1"), ("refund", "negotiation-1")]


def test_a_delivered_purchase_is_refunded_then_its_host_released(tmp_path: Path):
    seller = Seller(delivered={"fulfillment_id": "f-1", "state": "active"})

    _run(seller.compensation(_run_log(tmp_path, _ACCEPTED, _APPROVED)).steps(settled=False))

    assert seller.calls == [
        ("status", "negotiation-1"), ("refund", "negotiation-1"), ("release", "f-1"),
    ]


def test_a_fulfillment_unread_before_the_refund_is_read_again_to_release(tmp_path: Path):
    seller = Seller(delivered={"fulfillment_id": "f-1", "state": "active"}, status_failures=1)
    find, refund, release = seller.compensation(
        _run_log(tmp_path, _ACCEPTED, _APPROVED)
    ).steps(settled=False)

    with pytest.raises(ConnectionError):
        find[1]()
    refund[1]()
    release[1]()

    assert seller.calls == [
        ("status", "negotiation-1"), ("refund", "negotiation-1"),
        ("status", "negotiation-1"), ("release", "f-1"),
    ]


def test_an_already_released_host_is_not_released_again(tmp_path: Path):
    seller = Seller(delivered={"fulfillment_id": "f-1", "state": "released"})

    _run(seller.compensation(_run_log(tmp_path, _ACCEPTED, _APPROVED)).steps(settled=False))

    assert ("release", "f-1") not in seller.calls


def test_a_deal_the_scenario_settled_has_no_compensation(tmp_path: Path):
    seller = Seller(delivered={"fulfillment_id": "f-1", "state": "active"})

    assert seller.compensation(_run_log(tmp_path, _ACCEPTED, _APPROVED)).steps(settled=True) == []


def test_a_refund_refused_but_able_to_clear_is_retried_until_it_does(tmp_path: Path):
    seller = Seller(delivered=None, refusals=[409, 503])

    _run(seller.compensation(_run_log(tmp_path, _ACCEPTED, _APPROVED)).steps(settled=False))

    assert seller.calls.count(("refund", "negotiation-1")) == 3
    assert seller.now == 4.0


def test_a_refund_still_refused_after_its_window_names_the_unresolved_payment(tmp_path: Path):
    seller = Seller(delivered=None, refusals=[409] * 20)
    find, refund, _ = seller.compensation(
        _run_log(tmp_path, _ACCEPTED, _APPROVED)
    ).steps(settled=False)
    find[1]()

    with pytest.raises(UnresolvedPayment) as unresolved:
        refund[1]()

    assert "transaction-1" in str(unresolved.value)
    assert "negotiation-1" in str(unresolved.value)
    # Attempts at 0, 2, ... 10 seconds; no sleep follows the last one.
    assert seller.calls.count(("refund", "negotiation-1")) == 6
    assert seller.now == 10.0


def test_a_refund_failure_that_cannot_clear_still_names_the_payment(tmp_path: Path):
    seller = Seller(delivered=None, refusals=[403])
    find, refund, _ = seller.compensation(
        _run_log(tmp_path, _ACCEPTED, _APPROVED)
    ).steps(settled=False)
    find[1]()

    with pytest.raises(UnresolvedPayment) as unresolved:
        refund[1]()

    assert "transaction-1" in str(unresolved.value)
    assert isinstance(unresolved.value.__cause__, Refused)
    assert seller.calls.count(("refund", "negotiation-1")) == 1


def _answering(status_code: int, detail: str = "refused"):
    def read(_negotiation_id: str):
        raise AuthenticatedHTTPError(
            "refused", status_code=status_code, body={"detail": detail},
        )
    return read


def test_no_fulfillment_and_an_unverified_payment_read_as_no_host():
    unverified = "bare-metal settlement is not authoritatively verified"

    assert fulfillment_or_none(_answering(404), "negotiation-1") is None
    assert fulfillment_or_none(_answering(409, unverified), "negotiation-1") is None
    assert fulfillment_or_none(lambda _n: {"state": "active"}, "negotiation-1") == {"state": "active"}


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (409, "bare-metal fulfillment has not begun"),
        (409, "physical lifecycle conflicts with verified evidence"),
        (403, "negotiation buyer mismatch"),
    ],
)
def test_a_host_the_route_cannot_read_is_not_taken_for_no_host(status_code: int, detail: str):
    with pytest.raises(AuthenticatedHTTPError):
        fulfillment_or_none(_answering(status_code, detail), "negotiation-1")


@pytest.mark.parametrize(
    ("error", "may_clear"),
    [
        (StorefrontClientError("not verified", status_code=409), True),
        (StorefrontClientError("payments unavailable", status_code=503), True),
        (httpx.ConnectError("unreachable"), True),
        (StorefrontClientError("forbidden", status_code=403), False),
        (StorefrontClientError("operator action", status_code=500), False),
        (ValueError("broken contract"), False),
    ],
)
def test_only_a_refusal_that_may_clear_is_retried(error: Exception, may_clear: bool):
    assert refund_may_clear(error) is may_clear
