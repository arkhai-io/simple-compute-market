"""The mandate the kit sends, held to the payments service's current published wire.

``CURRENT_REQUEST`` is written from the published schema and the service's documented
normalization of mandate-level authorities, not from the kit's derivation, so the
derivation is checked against the contract rather than against itself. It is SCM's
own synthetic fixture: current-wire producer vectors were not supplied with this
schema snapshot.
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
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt

from payment_terms import BUYER, DISPUTE, PAYEE, SERVICE, agreement, config

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "test-vectors" / "payments.json").read_text()
)
# payment_terms.agreement() is accepted at 2026-10-07T12:00:00.25Z.
ACCEPTED = 1_791_374_400


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
                    "hold": {"for": "P7DT1H11S"},
                    "authorities": {
                        "stop": [_immediate_stop(BUYER), _immediate_stop(PAYEE)],
                        "reverse": [PAYEE, DISPUTE],
                        "extend": [],
                    },
                    "maxHoldExtension": "P0D",
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
    assert _wire(ApprovalRequest(mandate=mandate)) == expected
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
        lambda part: part["authorities"]["stop"][1].update(notice="PT1H"),
        lambda part: part["authorities"]["stop"][0].update(partialPeriod="prorated"),
        lambda part: part["authorities"]["stop"].pop(),
        lambda part: part["authorities"]["reverse"].append(BUYER),
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
