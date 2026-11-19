"""The double's controls through the typed control client, against the app in process.

Each control is driven as a lane drives it, through ``ControlClient``, and its
effect is read through the payments kit's real client. The transport faults, which
only a real server can show, are in ``test_faults.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from injected_time import WallTime

from lane_double_controls import ControlError, Rule, TimeView
from market_arkhai_payments.contracts import get_contract
from market_arkhai_payments.receipts import (
    ReceiptIdentity,
    transaction_id,
    verify_receipt,
    verify_snapshot,
)

from support import AGREEMENT, HOUR, PAYER, T0, UNKNOWN, Lane, available, mandate, refusal
from test_double import event, once_terms, rate_terms, snapshot, started, stopper


@pytest.fixture
def lane() -> Iterator[Lane]:
    lane = Lane()
    with lane.http:
        yield lane


def refused(call: object, *args: object) -> tuple[int, str]:
    with pytest.raises(ControlError) as error:
        call(*args)  # type: ignore[operator]
    return error.value.status, error.value.code


def test_a_refusal_rule_answers_the_kit_client_with_its_published_code(lane: Lane) -> None:
    with lane.controls() as controls:
        controls.install_rule(Rule.model_validate({
            "rule_id": "no-approvals", "match": {"route": "transactions"},
            "refusal": {"status": 409, "code": "insufficient_funds"}}))

        assert refusal(lane.client("buyer").approve, mandate(lane)) == (
            409, "insufficient_funds")
        [view] = controls.rules().rules
        assert (view.rule.rule_id, view.matched, view.waiting) == ("no-approvals", 1, 0)
    assert available(lane, "buyer") == {"USD/6": str(lane.funding())}


def test_a_rule_scoped_to_one_transaction_leaves_another_alone(lane: Lane) -> None:
    first, second = mandate(lane, nonce="first"), mandate(lane, nonce="second")
    with lane.controls() as controls:
        controls.install_rule(Rule.model_validate({
            "rule_id": "first-only", "match": {"transaction": transaction_id(first)},
            "refusal": {"status": 409, "code": "insufficient_funds"}}))

    assert refusal(lane.client("buyer").approve, first) == (409, "insufficient_funds")
    lane.client("buyer").approve(second)


def test_funding_is_visible_through_the_balance_read(lane: Lane) -> None:
    with lane.controls() as controls:
        funded = controls.fund(PAYER[0], 2500)

        assert (funded.account, funded.amount) == (PAYER[0], "2500")
        assert lane.token_client(PAYER[1]).get_balance(PAYER[0]).available[
            "USD/6"].root == "2500"
        assert refused(controls.fund, UNKNOWN, 1) == (404, "account_not_found")


def test_signer_rotation_signs_later_receipts_and_snapshots_with_the_second_key(
        lane: Lane) -> None:
    terms = mandate(lane)
    receipt = lane.client("buyer").approve(terms, agreement=AGREEMENT)
    rotated = lane.directory.rotated_signer().identity

    with lane.controls() as controls:
        identity = controls.rotate_signer()

    assert (identity.scheme, identity.identifier) == (rotated.scheme.value, rotated.identifier)
    snapshot = lane.client("seller").get_transaction(transaction_id(terms))
    assert snapshot.snapshot.issuer.identifier == rotated.identifier
    # A caller across a rotation trusts both keys: the snapshot is signed with the
    # second, and the receipt it embeds keeps the first's signature.
    both = [ReceiptIdentity(identity=lane.directory.receipt_identity),
            ReceiptIdentity(identity=rotated)]
    assert verify_snapshot(snapshot, both, mandate=terms, agreement_json=AGREEMENT,
                           livemode=False)
    assert not verify_snapshot(snapshot, lane.directory.receipt_identity, mandate=terms,
                               agreement_json=AGREEMENT, livemode=False)
    # The receipt signed before the rotation still verifies under the first key;
    # one approved after it, under the second alone.
    assert verify_receipt(receipt, lane.directory.receipt_identity, mandate=terms,
                          agreement_json=AGREEMENT, livemode=False)
    later = mandate(lane, nonce="after-rotation")
    later_receipt = lane.client("buyer").approve(later, agreement=AGREEMENT)
    assert verify_receipt(later_receipt, rotated, mandate=later, agreement_json=AGREEMENT,
                          livemode=False)
    assert not verify_receipt(later_receipt, lane.directory.receipt_identity, mandate=later,
                              agreement_json=AGREEMENT, livemode=False)


# --- the reservation control ------------------------------------------------------
#
# The rate part of ``test_double``: 1000 minor units an hour, reserving two hours
# ahead, so an approval at T0 reserves two periods and a start one more from a
# funded payer. Here it ends at ``END``, six periods after the start.

END = T0 + 6 * HOUR


def ending_rate(lane: Lane, *, payer: str, nonce: str,
                stop: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return rate_terms(lane, payer=payer, nonce=nonce, stop=stop,
                      end={"at": END, "partialPeriod": "returned"})


def test_a_rate_part_is_reserved_one_period_further_to_the_signed_funded_boundary(
        lane: Lane) -> None:
    with lane.controls() as controls:
        # The approval's two periods, the start's one, and one period beyond.
        controls.fund(PAYER[0], 4 * 1000)
        transaction = started(lane, ending_rate(lane, payer="payer", nonce="reserve-one"),
                              payer=PAYER)
        assert snapshot(lane, transaction)["fundedThrough"] == T0 + 3 * HOUR

        reserved = controls.reserve(transaction, END)

        assert (reserved.transaction, [part.model_dump() for part in reserved.parts]) == (
            transaction, [{"part": 0, "reserved_through": T0 + 4 * HOUR, "periods_added": 1}])
        signed = lane.client("seller").get_transaction(transaction)
        terms = ending_rate(lane, payer="payer", nonce="reserve-one")
        assert verify_snapshot(signed, lane.directory.receipt_identity, mandate=terms,
                               agreement_json=AGREEMENT, livemode=False)
        assert signed.snapshot.fundedThrough == T0 + 4 * HOUR
        # Once injected time reaches the boundary the payer's funds have run out.
        controls.set_time(T0 + 4 * HOUR)
    [part] = snapshot(lane, transaction)["parts"]
    assert (part["stop"]["cause"], part["stop"]["effectiveAt"]) == ("terms", T0 + 4 * HOUR)


def unstarted(lane: Lane) -> str:
    terms = ending_rate(lane, payer="buyer", nonce="reserve-unstarted")
    lane.client("buyer").approve(terms)
    return transaction_id(terms)


def once_only(lane: Lane) -> str:
    terms = once_terms(lane, nonce="reserve-once")
    lane.client("buyer").approve(terms)
    return transaction_id(terms)


def stopped(lane: Lane) -> str:
    transaction = started(lane, ending_rate(
        lane, payer="buyer", nonce="reserve-stopped", stop=[stopper(lane.account("buyer"), "PT0S")]))
    event(lane, "buyer", transaction, {"kind": "stop"}, "payer-stop")
    return transaction


@pytest.mark.parametrize("make", [unstarted, once_only, stopped],
                         ids=["unstarted", "once-only", "stopped"])
def test_a_reservation_is_refused_when_no_rate_part_runs(lane: Lane, make: Any) -> None:
    transaction = make(lane)
    before = snapshot(lane, transaction)

    with lane.controls() as controls:
        assert refused(controls.reserve, transaction, END) == (409, "no_running_rate_part")

    assert snapshot(lane, transaction) == before


def test_a_reservation_of_an_unknown_transaction_is_not_found(lane: Lane) -> None:
    with lane.controls() as controls:
        assert refused(controls.reserve, "f" * 64, END) == (404, "transaction_not_found")


@pytest.mark.parametrize(("transaction", "body"), [
    ("not-a-transaction", {"through": END}),
    (None, {"through": "soon"}),
], ids=["malformed-transaction", "malformed-body"])
def test_a_malformed_reservation_is_refused_with_nothing_changed(
        lane: Lane, transaction: str | None, body: dict[str, object]) -> None:
    started_transaction = started(lane, ending_rate(lane, payer="buyer", nonce="reserve-malformed"))
    before = snapshot(lane, started_transaction)
    # Rejection path: the typed client cannot build these requests, so each is
    # sent by hand; only the status and code are read.
    answer = lane.http.post(
        f"/test/transactions/{transaction or started_transaction}/reserve", json=body,
        headers={"Authorization": f"Bearer {lane.directory.control_token}"})

    assert (answer.status_code, answer.json()["code"]) == (422, "invalid_request")
    assert snapshot(lane, started_transaction) == before


def test_a_rate_part_is_not_reserved_unasked(lane: Lane) -> None:
    # The shared buyer's balance funds far more than the first reservation.
    transaction = started(lane, ending_rate(lane, payer="buyer", nonce="reserve-unasked"))
    with lane.controls() as controls:
        controls.set_time(T0 + 5 * HOUR)

    [part] = snapshot(lane, transaction)["parts"]
    assert (part["stop"]["cause"], part["stop"]["effectiveAt"]) == ("terms", T0 + 3 * HOUR)


def test_status_reports_the_injected_now_and_the_installed_contract_hashes(lane: Lane) -> None:
    metadata = get_contract().metadata

    with lane.controls() as controls:
        status = controls.status()

    assert status.time == TimeView(source="injected", now=T0)
    assert status.contracts == {
        "schema/payments.schema.json": metadata["schema_sha256"],
        "test-vectors/payments.json": metadata["vectors_sha256"],
    }


def test_the_time_is_set_forward_and_held_there(lane: Lane) -> None:
    with lane.controls() as controls:
        assert controls.set_time(T0 + 3_600) == TimeView(source="injected", now=T0 + 3_600)
        assert controls.status().time.now == T0 + 3_600
        # Setting the instant already held succeeds and changes nothing.
        assert controls.set_time(T0 + 3_600).now == T0 + 3_600

    assert lane.time.now() == T0 + 3_600


@pytest.mark.parametrize(("now", "expected"), [
    (T0 - 1, (409, "time_moves_forward")),
    (True, (422, "invalid_time")),
])
def test_a_refused_setting_changes_nothing(lane: Lane, now: int,
                                           expected: tuple[int, str]) -> None:
    with lane.controls() as controls:
        assert refused(controls.set_time, now) == expected
        assert controls.status().time.now == T0


def test_a_wall_time_double_serves_no_time_route() -> None:
    lane = Lane(source=WallTime(wall=lambda: T0))
    with lane.http, lane.controls() as controls:
        assert controls.status().time == TimeView(source="wall")
        assert refused(controls.set_time, T0 + 60) == (404, "invalid_request")


def test_admission_reads_the_injected_time(lane: Lane) -> None:
    terms = mandate(lane)
    with lane.controls() as controls:
        controls.set_time(terms["expires"])

    assert refusal(lane.client("buyer").approve, terms) == (409, "mandate_expired")


def test_a_control_call_with_a_wrong_token_is_refused(lane: Lane) -> None:
    # A public test value no fixture issues; never for a public network.
    with lane.controls("not-the-control-token") as controls:
        assert refused(controls.status) == (401, "authentication_required")


def test_a_control_call_without_a_token_is_refused(lane: Lane) -> None:
    # Rejection path: the typed client always sends its token, so the call
    # without one is sent by hand; only the status is read.
    assert lane.http.get("/test/status").status_code == 401


def test_an_account_token_is_not_a_control_token(lane: Lane) -> None:
    token = lane.directory.role("buyer").token
    assert token is not None

    with lane.controls(token) as controls:
        assert refused(controls.rules) == (401, "authentication_required")


def test_a_rule_is_refused_twice_and_deleted_once(lane: Lane) -> None:
    drop = Rule.model_validate({"rule_id": "drop-events", "match": {"route": "events"},
                                "drop_response_after_commit": True})
    with lane.controls() as controls:
        controls.install_rule(drop)

        assert refused(controls.install_rule, drop) == (409, "rule_exists")
        controls.delete_rule("drop-events")
        assert controls.rules().rules == []
        assert refused(controls.delete_rule, "drop-events") == (404, "rule_not_found")


@pytest.mark.parametrize("body", [
    {"rule_id": "unscoped", "unavailable": True},
    {"rule_id": "partial-outage", "match": {"route": "events"}, "unavailable": True},
], ids=["without-match", "scoped-unavailable"])
def test_a_rule_the_contract_refuses_installs_nothing(lane: Lane, body: dict[str, object]
                                                      ) -> None:
    # Rejection path: the typed client cannot build these rules, so each body is
    # sent by hand; only the status is read.
    answer = lane.http.post("/test/rules", json=body,
                            headers={"Authorization": f"Bearer {lane.directory.control_token}"})

    assert answer.status_code == 422
    with lane.controls() as controls:
        assert controls.rules().rules == []
