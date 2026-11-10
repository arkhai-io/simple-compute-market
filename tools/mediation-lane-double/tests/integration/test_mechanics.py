"""The authority's mechanics, as the mediation kit's real client meets them.

Each case files, appends and reads through ``MediationClient`` against the app in
process, with the payments kit's engine as the payments peer (``support``). No
rule is installed here, so nothing is ever ruled.
"""

from __future__ import annotations

import pytest

from market_arkhai_mediation.claims import sign_claim
from market_arkhai_mediation.client import MediationAPIError
from market_arkhai_mediation.contract import wire
from market_arkhai_mediation.models import (
    Append,
    DeliveryEndClaim,
    ReadAfter,
    RespondentAfter,
)
from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.errors import PaymentsAPIError, PaymentsTransportError
from market_identity import Ed25519Signer

from support import AGREEMENT, DAY, T0, Failing, Lane, filing, run

# The seller's marketplace signer of this suite's concurrence: a public test seed,
# never for a public network.
SELLER_SIGNER = Ed25519Signer(bytes([9]) * 32)


def _answer(lane: Lane, role: str, transaction: str, key: str = "filing-1",
            **claim: object) -> dict:
    async def file() -> dict:
        async with lane.client(role) as client:
            return wire(await client.file(filing(transaction, **claim), idempotency_key=key))
    return run(file())


def test_a_filing_with_no_rule_extends_each_part_and_stays_open() -> None:
    lane = Lane()
    transaction = lane.approve(parts=2)

    answer = _answer(lane, "seller", transaction)

    assert answer["status"] == "accepted"
    case = answer["case"]
    assert case["state"] == "open"
    assert [(part["part"], part["status"]) for part in case["parts"]] == [
        (0, "held"), (1, "held")]
    extends = lane.events(transaction, "extend")
    assert [event["sequence"] for event in extends] == [
        part["extension_ref"] for part in case["parts"]]
    assert all(event["account"] == lane.authority.account for event in extends)
    assert lane.part(transaction)["extensions"]


def test_a_refusal_other_than_nothing_held_answers_protection_incomplete() -> None:
    lane = Lane()
    # The authority holds no extend authority on this transaction, so payments
    # refuses it as unauthorized: no part may be reported not held.
    transaction = lane.approve(extend=[lane.account("seller")])

    answer = _answer(lane, "seller", transaction)

    assert answer == {"status": "error", "code": "protection_incomplete",
                      "message": answer["message"]}
    assert lane.events(transaction, "extend") == []


@pytest.mark.parametrize("error", [
    PaymentsTransportError("payments service request failed"),
    PaymentsAPIError(503, "ledger_unavailable"),
], ids=["transport", "refusal"])
def test_a_filing_stopped_after_one_extend_is_completed_by_a_retry_under_its_key(
    error: Exception,
) -> None:
    # The second part's extend fails once, after the first part's committed.
    lane = Lane(lambda peer: Failing(
        peer, lambda call, key: error if key.endswith(":1") else None))
    transaction = lane.approve(parts=2)
    first = _answer(lane, "seller", transaction)

    retried = _answer(lane, "seller", transaction)

    assert (first["status"], first["code"]) == ("error", "protection_incomplete")
    assert retried["status"] == "accepted"
    assert [part["status"] for part in retried["case"]["parts"]] == ["held", "held"]
    # The first part's extend was resent under its key and answered with the
    # event payments stored, not taken twice, both under the reserved case.
    extends = lane.events(transaction, "extend")
    assert sorted(event["event"]["part"] for event in extends) == [0, 1]
    assert {event["event"]["payload"]["case_ref"] for event in extends} == {
        retried["case"]["case_ref"]}


def test_a_failed_snapshot_read_after_a_nothing_held_refusal_is_completed_on_retry() -> None:
    # The double's second read of the transaction, for the not-held reason, fails once.
    lane = Lane(lambda peer: Failing(peer, lambda call, number: PaymentsTransportError(
        "payments service request failed") if (call, number) == ("get_transaction", "2")
        else None))
    transaction = lane.approve(parts=2)
    lane.payments.submit(transaction, {"account": lane.account("seller"), "requestId": "refund",
                                       "event": {"kind": "reverse", "part": 1}})
    first = _answer(lane, "seller", transaction)

    retried = _answer(lane, "seller", transaction)

    assert (first["status"], first["code"]) == ("error", "protection_incomplete")
    assert retried["case"]["parts"][1] == {"part": 1, "status": "not_held", "reason": "reversed"}
    [extend] = lane.events(transaction, "extend")
    assert (extend["event"]["part"], extend["event"]["payload"]["case_ref"]) == (
        0, retried["case"]["case_ref"])


def test_a_key_an_incomplete_filing_reserved_stays_that_filings() -> None:
    lane = Lane(lambda peer: Failing(peer, lambda call, key: PaymentsTransportError(
        "payments service request failed") if call == "submit_event" else None))
    transaction = lane.approve()
    _answer(lane, "seller", transaction)

    changed = _answer(lane, "seller", transaction, delivered=True)

    assert (changed["status"], changed["code"]) == ("error", "idempotency_conflict")


def test_an_exact_retry_returns_the_original_and_a_changed_one_conflicts() -> None:
    lane = Lane()
    transaction = lane.approve()
    original = _answer(lane, "seller", transaction)

    again = _answer(lane, "seller", transaction)
    changed = _answer(lane, "seller", transaction, delivered=True)

    assert again == original
    assert (changed["status"], changed["code"]) == ("error", "idempotency_conflict")
    assert len(lane.events(transaction, "extend")) == 1


def test_an_append_retried_under_its_key_returns_its_record_and_a_changed_one_conflicts(
) -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _answer(lane, "seller", transaction)["case"]["case_ref"]
    item = {"kind": "note", "producer": "buyer", "at": T0,
            "sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            "bytes": "Zm9v"}

    async def appends() -> tuple[dict, dict, dict]:
        async with lane.client("buyer") as buyer:
            answers = []
            for items in ([item], [item], [item, item]):
                answers.append(wire(await buyer.append(
                    Append.model_validate({"case_ref": case_ref, "items": items}),
                    idempotency_key="evidence", agreement=_agreement(),
                    transaction=transaction)))
            return answers[0], answers[1], answers[2]

    first, again, changed = run(appends())

    assert again == first
    assert (changed["status"], changed["code"]) == ("error", "idempotency_conflict")
    assert [entry["entry"]["kind"] for entry in _record(lane, "buyer", transaction)[
        "entries"]] == ["filed", "appended"]


def test_a_filer_who_is_no_party_is_refused() -> None:
    lane = Lane()
    transaction = lane.approve()

    answer = _answer(lane, "stranger", transaction)

    assert (answer["status"], answer["reason"]) == ("rejected", "filer_not_party")


def test_a_filing_whose_agreement_is_not_the_payments_is_rejected_before_any_effect() -> None:
    lane = Lane()
    transaction = lane.approve()
    # One field differs from the Agreement whose hash the receipt's `deal` commits to.
    other = {**AGREEMENT, "price": "1001"}

    refused = _answer(lane, "seller", transaction, key="mismatched", agreement=other)
    again = _answer(lane, "seller", transaction, key="mismatched", agreement=other)

    assert (refused["status"], refused["reason"]) == ("rejected", "agreement_hash_mismatch")
    assert again == refused
    assert lane.events(transaction, "extend") == []
    assert lane.controls().cases(transaction).cases == []

    async def read_other() -> dict:
        async with lane.client("buyer") as client:
            return wire(await client.read_record(
                ReadAfter.model_validate({"agreement": agreement_hash(other), "after": 0}),
                transaction=transaction))

    with pytest.raises(MediationAPIError) as unknown:
        run(read_other())
    assert (unknown.value.status, unknown.value.code) == (404, "invalid_request")

    honest = _answer(lane, "seller", transaction, key="honest")

    assert honest["status"] == "accepted"
    assert [part["status"] for part in honest["case"]["parts"]] == ["held"]
    # Case references count from one in each process: the refused filing reserved none.
    assert honest["case"]["case_ref"].endswith("-1")
    assert [case.case_ref for case in lane.controls().cases(transaction).cases] == [
        honest["case"]["case_ref"]]


def test_a_case_with_nothing_held_is_dismissed() -> None:
    lane = Lane()
    transaction = lane.approve()
    # The payee refunds the whole part before anyone files.
    lane.payments.submit(transaction, {"account": lane.account("seller"), "requestId": "refund",
                                       "event": {"kind": "reverse", "part": 0}})

    answer = _answer(lane, "buyer", transaction, cause="payer")

    assert answer["case"]["state"] == "closed"
    assert answer["case"]["parts"] == [{"part": 0, "status": "not_held", "reason": "reversed"}]
    page = _record(lane, "buyer", transaction)
    assert [entry["entry"]["kind"] for entry in page["entries"]] == ["filed", "closed"]
    closed = page["entries"][1]["entry"]
    assert (closed["reason"], closed["dismissal_reason"]) == ("dismissed", "nothing_held")


def test_a_clock_advance_past_a_once_hold_reports_the_part_paid_out() -> None:
    lane = Lane()
    transaction = lane.approve()
    controls = lane.controls()
    controls.advance_clock(8 * DAY)

    answer = _answer(lane, "buyer", transaction, cause="payer")

    assert lane.part(transaction)["status"] in {"released", "settled"}
    assert answer["case"]["parts"] == [{"part": 0, "status": "not_held", "reason": "paid_out"}]
    assert answer["case"]["state"] == "closed"


def _record(lane: Lane, role: str, transaction: str, after: int = 0,
            limit: int | None = None) -> dict:
    async def read() -> dict:
        async with lane.client(role) as client:
            request = {"agreement": _agreement(), "after": after}
            if limit is not None:
                request["limit"] = limit
            return wire(await client.read_record(ReadAfter.model_validate(request),
                                                 transaction=transaction))
    return run(read())


def _agreement() -> str:
    return agreement_hash(AGREEMENT)


def test_appends_follow_the_contract() -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _answer(lane, "seller", transaction)["case"]["case_ref"]
    claim = DeliveryEndClaim.model_validate(
        {"kind": "delivery_end", "ended_at": T0, "delivered": False, "cause": "payee"})
    concurrence = sign_claim(agreement=_agreement(), claim=claim, signer=SELLER_SIGNER)
    item = {"kind": "note", "producer": "buyer", "at": T0,
            "sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            "bytes": "Zm9v"}

    async def appends() -> tuple[dict, dict, dict]:
        async with lane.client("buyer") as buyer, lane.client("seller") as seller:
            evidence = await buyer.append(
                Append.model_validate({"case_ref": case_ref, "items": [item]}),
                idempotency_key="evidence", agreement=_agreement(), transaction=transaction)
            payer_concurs = await buyer.append(
                Append.model_validate({"case_ref": case_ref, "concurrence": wire(concurrence)}),
                idempotency_key="payer-concurs", agreement=_agreement(), transaction=transaction)
            payee_concurs = await seller.append(
                Append.model_validate({"case_ref": case_ref, "concurrence": wire(concurrence)}),
                idempotency_key="payee-concurs", agreement=_agreement(), transaction=transaction)
            return wire(evidence), wire(payer_concurs), wire(payee_concurs)

    evidence, payer_concurs, payee_concurs = run(appends())

    assert evidence["status"] == "accepted"
    assert evidence["record"]["entry"]["actor"] == lane.account("buyer")
    assert evidence["record"]["entry"]["items"] == [item]
    assert (payer_concurs["status"], payer_concurs["reason"]) == ("rejected", "actor_not_party")
    assert payee_concurs["status"] == "accepted"

    lane.controls().close_case(case_ref)

    async def late() -> dict:
        async with lane.client("buyer") as buyer:
            return wire(await buyer.append(
                Append.model_validate({"case_ref": case_ref, "items": [item]}),
                idempotency_key="late", agreement=_agreement(), transaction=transaction))

    late_answer = run(late())
    assert (late_answer["status"], late_answer["reason"]) == ("rejected", "case_closed")


def test_the_record_pages_from_a_cursor_and_refuses_unknown_readers() -> None:
    lane = Lane()
    transaction = lane.approve()
    _answer(lane, "seller", transaction, key="first")
    _answer(lane, "seller", transaction, key="second", delivered=True)

    first = _record(lane, "buyer", transaction, limit=1)
    rest = _record(lane, "buyer", transaction, after=first["next_after"])

    assert ([e["entry"]["sequence"] for e in first["entries"]], first["has_more"]) == ([1], True)
    assert ([e["entry"]["sequence"] for e in rest["entries"]], rest["has_more"]) == ([2], False)
    with pytest.raises(MediationAPIError) as stranger:
        _record(lane, "stranger", transaction)
    assert (stranger.value.status, stranger.value.code) == (404, "invalid_request")


def test_an_agreement_nobody_filed_for_is_refused_as_unknown() -> None:
    lane = Lane()
    transaction = lane.approve()

    with pytest.raises(MediationAPIError) as unknown:
        _record(lane, "seller", transaction)

    assert (unknown.value.status, unknown.value.code) == (404, "invalid_request")


def test_a_known_agreement_with_no_case_reads_as_an_empty_page() -> None:
    lane = Lane()
    # A filing whose protection could not complete makes the Agreement known
    # without opening a case.
    transaction = lane.approve(extend=[lane.account("seller")])
    _answer(lane, "seller", transaction)

    page = _record(lane, "buyer", transaction)

    assert (page["entries"], page["next_after"], page["has_more"]) == ([], 0, False)


def test_the_respondent_listing_clears_once_the_respondent_appends() -> None:
    lane = Lane()
    transaction = lane.approve()
    answer = _answer(lane, "seller", transaction)

    async def respond() -> tuple[dict, dict, dict]:
        async with lane.client("buyer") as buyer, lane.client("seller") as seller:
            listed = wire(await buyer.respondent(RespondentAfter(after="")))
            filer_sees = wire(await seller.respondent(RespondentAfter(after="")))
            await buyer.append(
                Append.model_validate({"case_ref": answer["case"]["case_ref"], "items": [{
                    "kind": "note", "producer": "buyer", "at": T0,
                    "sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
                    "bytes": "Zm9v"}]}),
                idempotency_key="answer", agreement=_agreement(), transaction=transaction)
            answered = wire(await buyer.respondent(RespondentAfter(after="")))
            return listed, filer_sees, answered

    listed, filer_sees, answered = run(respond())

    assert [case["case_ref"] for case in listed["cases"]] == [answer["case"]["case_ref"]]
    assert listed["cases"][0]["filer"] == "payee"
    assert filer_sees["cases"] == []
    assert answered["cases"] == []


def test_a_party_reads_its_case() -> None:
    lane = Lane()
    transaction = lane.approve()
    answer = _answer(lane, "seller", transaction)

    async def read() -> dict:
        async with lane.client("buyer") as buyer:
            return wire(await buyer.case(answer["case"]["case_ref"], agreement=_agreement(),
                                         transaction=transaction))

    assert run(read()) == answer
