"""A delivery authorization's optional refusal code."""

import json

import pytest
from pydantic import ValidationError

from market_deal_lifecycle.delivery import DeliveryAuthorization

ANSWER = {
    "status": "allow", "reason": "validated once commitment",
    "operation_id": "n-1:commit", "evidence_refs": ["tx-1"],
}


def test_an_answer_without_a_code_dumps_exactly_what_it_carried():
    answer = DeliveryAuthorization.model_validate(ANSWER)

    assert answer.code is None
    assert answer.model_dump(mode="json") == ANSWER
    assert json.loads(answer.model_dump_json()) == ANSWER


def test_an_acknowledgement_journaled_without_the_key_reads():
    stored = json.dumps({**ANSWER, "status": "refuse", "reason": "invalid commitment evidence"})

    answer = DeliveryAuthorization.model_validate_json(stored)

    assert answer.status == "refuse" and answer.code is None
    assert answer.model_dump(mode="json") == json.loads(stored)


def test_a_coded_refusal_carries_its_code_through_a_round_trip():
    refusal = DeliveryAuthorization(
        status="refuse", reason="rate servicing is not composed in this storefront",
        operation_id="n-1:commit", evidence_refs=["tx-1"], code="rate_servicing_unavailable",
    )

    dumped = refusal.model_dump(mode="json")

    assert dumped["code"] == "rate_servicing_unavailable"
    assert DeliveryAuthorization.model_validate(dumped) == refusal


def test_an_unknown_code_is_refused():
    with pytest.raises(ValidationError):
        DeliveryAuthorization.model_validate({**ANSWER, "status": "refuse", "code": "unknown_code"})
