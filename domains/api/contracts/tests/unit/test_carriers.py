"""Every carrier binds to any kind literal with one validation, and refuses another kind."""

import pytest
from market_identity import Ed25519Signer
from pydantic import BaseModel, ValidationError

from arkhai_api_contracts.carriers import (
    materialization_model,
    message_model,
    receipt_model,
    result_model,
    terms_model,
)

KINDS = ("api_credits.v1", "inference.v1")
# A deterministic development key for this test only; never used on any network.
PRINCIPAL = Ed25519Signer(bytes(range(32))).identity.model_dump(mode="json")
SELECTION = {"mechanism": "alkahest.v1", "option_id": "a" * 64}
OBLIGATION_REF = "b" * 64


class _Resource(BaseModel):
    service_name: str


def _payload(**key):
    return {"quantity": 3, "key": key or {"mode": "new"}}


@pytest.mark.parametrize("kind", KINDS)
def test_message_and_terms_bind_the_purchase_shape(kind):
    message = message_model(kind)(kind=kind, payload=_payload())
    assert (message.kind, message.quantity, message.key_mode) == (kind, 3, "new")
    terms = terms_model(kind)(kind=kind, payload=_payload(), listing_ref="listing-1")
    assert terms.listing_ref == "listing-1"
    assert issubclass(terms_model(kind), message_model(kind))
    assert message_model(kind) is message_model(kind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": 0},
        {"quantity": 1, "key": {"mode": "existing"}},
        {"quantity": 1, "key": {"mode": "rotate"}},
    ],
)
def test_message_refuses_an_invalid_purchase(kind, payload):
    with pytest.raises(ValidationError):
        message_model(kind)(kind=kind, payload=payload)


def test_message_records_selection_and_principals_together():
    kind = KINDS[0]
    complete = message_model(kind)(
        kind=kind,
        payload=_payload(),
        settlement_selection=SELECTION,
        buyer_principal=PRINCIPAL,
        seller_principal=PRINCIPAL,
    )
    assert complete.settlement_selection.mechanism == "alkahest.v1"
    with pytest.raises(ValidationError, match="recorded together"):
        message_model(kind)(kind=kind, payload=_payload(), settlement_selection=SELECTION)


_VALID = {
    "message": (message_model, {"payload": {"quantity": 1}}),
    "terms": (terms_model, {"payload": {"quantity": 1}, "listing_ref": "L-1"}),
    "receipt": (receipt_model, {"status": "ready", "escrow_uid": "0x1"}),
    "result": (result_model, {"action": "issue"}),
    "materialization": (
        lambda kind: materialization_model(kind, _Resource),
        {"quantity": 1, "escrow_uid": "0x1"},
    ),
}


@pytest.mark.parametrize("carrier", sorted(_VALID))
@pytest.mark.parametrize("kind", KINDS)
def test_a_bound_carrier_accepts_its_own_kind_and_refuses_the_other(carrier, kind):
    factory, fields = _VALID[carrier]
    other = next(candidate for candidate in KINDS if candidate != kind)
    bound = factory(kind)

    assert bound.model_validate({"kind": kind, **fields}).kind == kind
    assert bound.model_validate(fields).kind == kind
    with pytest.raises(ValidationError):
        bound.model_validate({"kind": other, **fields})


def test_materialization_carries_the_domain_resource_model():
    model = materialization_model(KINDS[1], _Resource)
    handoff = model(
        quantity=2,
        obligation_ref=OBLIGATION_REF,
        mechanism="arkhai.payments.v1",
        fulfillment_id="f-1",
        listing_resource={"service_name": "chat"},
    )
    assert isinstance(handoff.listing_resource, _Resource)
    with pytest.raises(ValidationError):
        model(quantity=2, obligation_ref=OBLIGATION_REF, mechanism="m", fulfillment_id="f", listing_resource={})
    with pytest.raises(ValidationError, match="requires mechanism and fulfillment_id"):
        model(quantity=2, obligation_ref=OBLIGATION_REF)
    with pytest.raises(ValidationError, match="escrow_uid or obligation_ref"):
        model(quantity=2)


def test_receipt_and_result_refuse_blank_status_and_action():
    kind = KINDS[0]
    with pytest.raises(ValidationError, match="escrow_uid or obligation_ref"):
        receipt_model(kind)(status="ready")
    with pytest.raises(ValidationError, match="status must be non-empty"):
        receipt_model(kind)(status=" ", escrow_uid="0x1")
    with pytest.raises(ValidationError, match="action must be non-empty"):
        result_model(kind)(action=" ")
    assert result_model(kind)(action="issue").status == "success"
