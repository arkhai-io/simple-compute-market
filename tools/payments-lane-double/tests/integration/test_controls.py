"""The double's controls through the typed control client, against the app in process.

Each control is driven as a lane drives it, through ``ControlClient``, and its
effect is read through the payments kit's real client. The transport faults, which
only a real server can show, are in ``test_faults.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lane_double_controls import ControlError, Rule
from market_arkhai_payments.contracts import get_contract
from market_arkhai_payments.receipts import (
    ReceiptIdentity,
    transaction_id,
    verify_receipt,
    verify_snapshot,
)

from support import AGREEMENT, PAYER, T0, UNKNOWN, Lane, available, mandate, refusal


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


def test_status_reports_the_perceived_now_and_the_installed_contract_hashes(lane: Lane) -> None:
    metadata = get_contract().metadata

    with lane.controls() as controls:
        status = controls.status()

    assert (status.perceived_now, status.offset_seconds) == (T0, 0)
    assert status.contracts == {
        "schema/payments.schema.json": metadata["schema_sha256"],
        "test-vectors/payments.json": metadata["vectors_sha256"],
    }


def test_the_clock_advances_and_resets_to_wall_time(lane: Lane) -> None:
    with lane.controls() as controls:
        assert controls.advance_clock(3_600).perceived_now == T0 + 3_600
        lane.clock.now = T0 + 10
        assert controls.status().perceived_now == T0 + 3_610

        reset = controls.reset_clock()

    assert (reset.perceived_now, reset.offset_seconds) == (T0 + 10, 0)


def test_admission_reads_the_perceived_clock(lane: Lane) -> None:
    terms = mandate(lane)
    with lane.controls() as controls:
        controls.advance_clock(terms["expires"] - T0)

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
