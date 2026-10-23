import pytest
from pydantic import ValidationError

from arkhai_api.purchase import (
    ProvisionTerms,
    provision_key_id,
    provision_key_mode,
    provision_quantity,
    provision_terms_model,
)

FIRST = provision_terms_model("api_credits.v1")
SECOND = provision_terms_model("inference.v1")
PAYLOAD = {"quantity": 3, "key": {"mode": "new"}}


def test_two_kinds_validate_the_payload_through_one_definition():
    first, second = FIRST(payload=PAYLOAD), SECOND(payload=PAYLOAD)
    assert first.payload == second.payload == {"quantity": 3, "key": {"mode": "new"}}
    assert first.model_dump() == {"kind": "api_credits.v1", "version": 1, "payload": first.payload}
    assert second.model_dump() == {"kind": "inference.v1", "version": 1, "payload": first.payload}
    assert issubclass(FIRST, ProvisionTerms) and issubclass(SECOND, ProvisionTerms)
    assert provision_terms_model("api_credits.v1") is FIRST


def test_a_binding_refuses_the_other_kind():
    with pytest.raises(ValidationError):
        FIRST.model_validate(SECOND(payload=PAYLOAD).model_dump())
    with pytest.raises(ValidationError):
        FIRST(payload=PAYLOAD, version=2)


@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": 0, "key": {"mode": "new"}},
        {"quantity": 1, "key": {"mode": "existing"}},
        {"quantity": 1, "key": {"mode": "revoked"}},
        {"quantity": 1, "key": {"mode": "new"}, "extra": True},
        {"key": {"mode": "new"}},
    ],
)
def test_payload_refusals_are_the_same_under_every_kind(payload):
    for model in (FIRST, SECOND):
        with pytest.raises(ValidationError):
            model(payload=payload)


def test_a_purchase_states_its_key_disposition_without_null_fields():
    new = FIRST.purchase(quantity=5)
    assert new.payload == {"quantity": 5, "key": {"mode": "new"}}
    assert (new.quantity, new.key_mode, new.key_id) == (5, "new", None)
    existing = SECOND.purchase(quantity=2, key_mode="existing", key_id="ak_abc")
    assert existing.payload == {"quantity": 2, "key": {"mode": "existing", "key_id": "ak_abc"}}
    assert (existing.quantity, existing.key_mode, existing.key_id) == (2, "existing", "ak_abc")


def test_the_accessors_read_any_carrier():
    terms = FIRST.purchase(quantity=5, key_mode="existing", key_id="ak_abc")
    for carrier in (terms, terms.model_dump()):
        assert provision_quantity(carrier) == 5
        assert provision_key_mode(carrier) == "existing"
        assert provision_key_id(carrier) == "ak_abc"
    assert provision_quantity({}) is None
    assert provision_key_mode({}) == "new"
    assert provision_key_id({"payload": {"key": {"mode": "new"}}}) is None
    assert provision_quantity({"payload": {"quantity": "many"}}) is None
