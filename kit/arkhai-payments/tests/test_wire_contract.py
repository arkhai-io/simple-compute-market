"""The mandate the kit sends, held to the payments service's current published wire.

``_current_request`` is written from the published schema and the accepted lifecycle
terms of the fixture Agreement, not from the kit's derivation, so the derivation is
checked against the contract rather than against itself: a once part owed from
approval and maturing at the Agreement's end, returned if stopped, held for the
dispute window after a stop, reversible by the payee and the dispute authority,
extendable only by the dispute authority, and stoppable by nobody; an uncapped case
hold is the required null. It is an independent synthetic fixture checked alongside
the published producer vectors.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from market_arkhai_payments import (
    ApprovalRequest,
    Mandate,
    MandatePolicyError,
    PaymentSettlementData,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredEvent,
    agreement_hash,
    check,
    derive_mandate,
    mandate_policy_for_agreement,
    transaction_id,
    verify_receipt,
)
from market_arkhai_payments.canonical import wire_json
from market_arkhai_payments.models import Balance, HttpUrl, PartEnd, PartSnapshot
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt

from payment_terms import BUYER, DISPUTE, PAYEE, SERVICE, agreement, config

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "test-vectors" / "historical-payments.json").read_text()
)
# payment_terms.agreement() is accepted at 2026-10-07T12:00:00.25Z and starts at
# 12:00:10.5Z for one hour; whole-second part ends round up.
ACCEPTED = 1_791_374_400
TERM_END = 1_791_378_011


def _immediate_stop(account: str) -> dict[str, str]:
    return {"account": account, "notice": "P0D", "partialPeriod": "charged"}


def _current_request(terms: dict) -> dict:
    return {
        "mandate": {
            "from": BUYER,
            "to": PAYEE,
            "parts": [
                {
                    "kind": "once",
                    "asset": "USD/2",
                    "amount": "10000",
                    "hold": {"afterStop": "P7D"},
                    "authorities": {
                        "stop": [],
                        "reverse": [PAYEE, DISPUTE],
                        "extend": [DISPUTE],
                    },
                    "maxHoldExtension": None,
                    "end": {"at": TERM_END, "partialPeriod": "returned"},
                }
            ],
            "deal": agreement_hash(terms),
            "fee": {"bps": 250},
            "nonce": "arkhai.payments.v1",
            "expires": ACCEPTED + 7 * 86_400,
        }
    }


def _derived():
    terms = agreement()
    policy = mandate_policy_for_agreement(terms, config())
    return terms, policy, derive_mandate(terms, policy)


def _wire(model: BaseModel) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_the_derived_mandate_is_the_current_published_approval_request():
    terms, _, mandate = _derived()
    expected = _current_request(terms)
    assert ApprovalRequest.model_validate(expected)
    assert wire_json(ApprovalRequest(mandate=mandate)) == expected
    assert "authorities" not in _wire(mandate)


def test_the_previous_wire_is_refused():
    for vector in (*VECTORS["mandates"], *(a["request"]["mandate"] for a in VECTORS["approvals"])):
        with pytest.raises(ValidationError):
            Mandate.model_validate(vector["mandate"] if "mandate" in vector else vector)
    with pytest.raises(ValidationError):
        SignedReceipt.model_validate(VECTORS["receipt"]["signed"])

    terms, _, mandate = _derived()
    global_authorities = _wire(mandate) | {
        "authorities": {"start": [BUYER, PAYEE], "stop": [BUYER, PAYEE], "reverse": [PAYEE, DISPUTE]}
    }
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate({"mandate": global_authorities})
    for missing in ("authorities", "maxHoldExtension"):
        part_without = copy.deepcopy(_wire(mandate))
        del part_without["parts"][0][missing]
        with pytest.raises(ValidationError):
            ApprovalRequest.model_validate({"mandate": part_without})


def test_seller_and_buyer_agree_on_one_transaction():
    terms, policy, mandate = _derived()
    stored = PaymentSettlementData.for_agreement(terms, config())
    assert stored.mandate == mandate
    assert check(stored.to_wire()["mandate"], terms, policy) == mandate
    assert stored.transaction_id == transaction_id(_current_request(terms)["mandate"])
    stored.require_bound_to(terms)


@pytest.mark.parametrize(
    "change",
    [
        lambda part: part["authorities"]["extend"].append(BUYER),
        lambda part: part["authorities"]["extend"].append(PAYEE),
        lambda part: part.update(maxHoldExtension="P1D"),
        lambda part: part["authorities"]["stop"].append(_immediate_stop(PAYEE)),
        lambda part: part["authorities"]["stop"].append(_immediate_stop(BUYER)),
        lambda part: part["authorities"]["extend"].clear(),
        lambda part: part["authorities"]["reverse"].remove(DISPUTE),
        lambda part: part["authorities"]["reverse"].append(BUYER),
        lambda part: part["hold"].update(afterStop="P1D"),
        lambda part: part["end"].update(partialPeriod="charged"),
    ],
)
def test_the_buyer_refuses_any_other_lifecycle_right(change):
    terms, policy, mandate = _derived()
    tampered = _wire(mandate)
    change(tampered["parts"][0])
    with pytest.raises(MandatePolicyError):
        check(tampered, terms, policy)


def test_a_once_part_carries_no_start_authority():
    terms, policy, mandate = _derived()
    tampered = _wire(mandate)
    tampered["parts"][0]["authorities"]["start"] = [BUYER, PAYEE]
    with pytest.raises(MandatePolicyError):
        check(tampered, terms, policy)


def test_stored_settlement_data_in_the_previous_wire_is_refused_not_upgraded():
    terms, _, mandate = _derived()
    previous = _wire(mandate)
    for part in previous["parts"]:
        del part["authorities"], part["maxHoldExtension"]
    previous["authorities"] = {"start": [BUYER, PAYEE], "stop": [BUYER, PAYEE], "reverse": [PAYEE, DISPUTE]}
    stored = {"mandate": previous, "transaction_id": transaction_id(_wire(mandate))}
    with pytest.raises(MandatePolicyError):
        PaymentSettlementData.parse(stored)
    assert "authorities" in stored["mandate"]


def test_a_receipt_snapshot_and_reversal_for_the_derived_mandate_hold():
    terms, _, mandate = _derived()
    receipt = build_signed_receipt(signer=SERVICE, mandate=mandate)
    assert verify_receipt(receipt, SERVICE.identity, mandate=mandate, agreement_json=terms, livemode=False)

    payments = FakePaymentsClient(signer=SERVICE)
    payments.approve(mandate)
    txid = transaction_id(mandate)
    snapshot = payments.get_transaction(txid)
    assert SignedTransactionSnapshot.model_validate(_wire(snapshot)) == snapshot
    assert [part.extensions for part in snapshot.snapshot.parts] == [[]]
    assert StoredEvent.model_validate(_wire(payments.reverse(txid))).event.kind.value == "reverse"


CURRENT_VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "test-vectors" / "payments.json").read_text()
)


@pytest.mark.parametrize("vector", CURRENT_VECTORS["snapshots"], ids=lambda v: v["name"])
def test_current_producer_snapshots_round_trip(vector):
    parsed = SignedTransactionSnapshot.model_validate(vector["signed"])
    assert wire_json(parsed) == vector["signed"]
    assert transaction_id(vector["mandate"]) == parsed.snapshot.transaction.root


@pytest.mark.parametrize("gross", ["0", "1", "9" * 38])
def test_snapshot_gross_accepts_nonnegative_minor_units(gross):
    part = copy.deepcopy(CURRENT_VECTORS["snapshots"][0]["signed"]["snapshot"]["parts"][0])
    part["gross"] = gross
    assert PartSnapshot.model_validate(part).gross.root == gross


@pytest.mark.parametrize("gross", ["-1", "00", "01", "9" * 39])
def test_snapshot_gross_refuses_invalid_minor_units(gross):
    part = copy.deepcopy(CURRENT_VECTORS["snapshots"][0]["signed"]["snapshot"]["parts"][0])
    part["gross"] = gross
    with pytest.raises(ValidationError):
        PartSnapshot.model_validate(part)


def test_effective_end_is_optional_and_unknown_snapshot_fields_are_refused():
    part = copy.deepcopy(CURRENT_VECTORS["snapshots"][0]["signed"]["snapshot"]["parts"][0])
    part["end"] = {"at": 1_800_000_000, "partialPeriod": "charged"}
    assert wire_json(PartSnapshot.model_validate(part)) == part
    del part["end"]
    assert "end" not in wire_json(PartSnapshot.model_validate(part))
    part["unknown"] = True
    with pytest.raises(ValidationError):
        PartSnapshot.model_validate(part)


@pytest.mark.parametrize("at", [-1, 9_007_199_254_740_992])
def test_effective_end_refuses_timestamps_outside_safe_integer_bounds(at):
    with pytest.raises(ValidationError):
        PartEnd.model_validate({"at": at, "partialPeriod": "charged"})


def test_http_url_publication_accepts_http_and_https_and_refuses_other_schemes():
    for url in ("http://example.com/", "https://example.com/return"):
        assert HttpUrl.model_validate(url).root == url
    for url in ("ftp://example.com/", "https://example.com/with space", "example.com"):
        with pytest.raises(ValidationError):
            HttpUrl.model_validate(url)


def test_balance_asset_keys_remain_hashable_and_round_trip():
    body = {"available": {"USD/2": "100", "EUR/6": "-25"}, "held": []}
    assert wire_json(Balance.model_validate(body)) == body


@pytest.mark.parametrize("asset", ["usd/2", "INVALID SPACE", "USD/1234567"])
def test_balance_refuses_invalid_asset_keys(asset):
    with pytest.raises(ValidationError):
        Balance.model_validate({"available": {asset: "100"}, "held": []})
