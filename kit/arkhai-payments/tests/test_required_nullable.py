"""A part's `maxHoldExtension` is required and may be null, and null survives the wire.

The published schema states the property as an intersection that admits no null,
while the service accepts null; ``scripts/generate_models.py`` generates the union the
service validates, and ``schema/SOURCE.md`` records the discrepancy. Every mandate here
is SCM's own synthetic fixture, with obviously synthetic accounts, not a producer
vector. The kit's own derivation never produces null.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import rfc8785
from pydantic import ValidationError

from market_arkhai_payments import (
    Mandate,
    MandatePolicyError,
    PaymentSettlementData,
    PaymentsClient,
    agreement_hash,
    check,
    derive_mandate,
    mandate_policy_for_agreement,
    transaction_id,
    verify_receipt,
)
from market_arkhai_payments.canonical import wire_json
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_arkhai_payments.models import OncePart, Part, RatePart

from payment_terms import BUYER, PAYEE, SERVICE, agreement, config

KIT = Path(__file__).resolve().parents[1]
VENDORED_SCHEMA_SHA256 = "5cf22707c0e5c1c1c3ffd398d0a1710e136e719eee841c39323eba837e0ea848"


def _stop(account: str) -> dict[str, str]:
    return {"account": account, "notice": "P0D", "partialPeriod": "charged"}


def _once(max_hold_extension: str | None) -> dict:
    return {
        "kind": "once",
        "asset": "USD/2",
        "amount": "10000",
        "hold": {"for": "P7D"},
        "authorities": {"stop": [_stop(BUYER)], "reverse": [PAYEE], "extend": []},
        "maxHoldExtension": max_hold_extension,
    }


def _rate(max_hold_extension: str | None) -> dict:
    return {
        "kind": "rate",
        "asset": "USD/2",
        "amount": "100",
        "period": "PT1H",
        "reserveAhead": "PT1H",
        "hold": {"for": "P1D"},
        "authorities": {"stop": [_stop(BUYER)], "reverse": [PAYEE], "extend": [], "start": [BUYER]},
        "maxHoldExtension": max_hold_extension,
    }


def _mandate(*parts: dict, deal: str = "ab" * 32) -> dict:
    return {
        "from": BUYER,
        "to": PAYEE,
        "parts": list(parts),
        "deal": deal,
        "fee": {"bps": 250},
        "nonce": "scm.synthetic.required-null",
        "expires": 1_800_000_000,
    }


@pytest.mark.parametrize("part", [_once(None), _rate(None)], ids=["once", "rate"])
def test_a_null_maximum_hold_extension_is_accepted_and_kept(part):
    parsed = Part.model_validate(part)
    assert parsed.root.maxHoldExtension is None
    assert wire_json(parsed) == part
    assert "end" not in wire_json(parsed)


@pytest.mark.parametrize("model", [OncePart, RatePart])
def test_the_property_stays_required(model):
    assert model.model_fields["maxHoldExtension"].is_required()


@pytest.mark.parametrize("part", [_once(None), _rate(None)], ids=["once", "rate"])
def test_an_omitted_maximum_hold_extension_is_refused(part):
    del part["maxHoldExtension"]
    with pytest.raises(ValidationError):
        Part.model_validate(part)


@pytest.mark.parametrize("part", [_once("P0D"), _rate("P0D")], ids=["once", "rate"])
def test_a_duration_is_unchanged(part):
    mandate = Mandate.model_validate(_mandate(part))
    wire = wire_json(mandate)
    assert wire == _mandate(part)
    # With no required null present, the wire form is exactly the form every mandate
    # took before, so no existing transaction ID moves.
    assert wire == mandate.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_the_transaction_id_is_the_hash_of_the_literal_canonical_json():
    raw = _mandate(_once(None))
    literal = (
        '{"deal":"' + "ab" * 32 + '","expires":1800000000,"fee":{"bps":250},'
        '"from":"11111111-1111-4111-8111-111111111111",'
        '"nonce":"scm.synthetic.required-null",'
        '"parts":[{"amount":"10000","asset":"USD/2","authorities":{"extend":[],'
        '"reverse":["22222222-2222-4222-8222-222222222222"],'
        '"stop":[{"account":"11111111-1111-4111-8111-111111111111","notice":"P0D",'
        '"partialPeriod":"charged"}]},"hold":{"for":"P7D"},"kind":"once",'
        '"maxHoldExtension":null}],'
        '"to":"22222222-2222-4222-8222-222222222222"}'
    ).encode()
    assert rfc8785.dumps(raw) == literal
    expected = hashlib.sha256(literal).hexdigest()
    assert transaction_id(raw) == expected
    assert transaction_id(Mandate.model_validate(raw)) == expected


def test_both_part_kinds_hash_as_their_raw_json():
    raw = _mandate(_once(None), _rate(None))
    assert transaction_id(Mandate.model_validate(raw)) == hashlib.sha256(rfc8785.dumps(raw)).hexdigest()


def test_an_explicit_null_for_an_optional_property_is_normalized_away():
    # `end` is optional. An explicit null validates but is no part of the wire form,
    # so the transaction ID hashes the normalized mandate, and settlement data paired
    # with the hash of the raw JSON, null included, is refused.
    raw = _mandate(dict(_once("P0D"), end=None))
    normalized = _mandate(_once("P0D"))
    parsed = Mandate.model_validate(raw)
    assert parsed.parts[0].root.end is None
    assert wire_json(parsed) == normalized
    assert transaction_id(raw) == hashlib.sha256(rfc8785.dumps(normalized)).hexdigest()
    raw_id = hashlib.sha256(rfc8785.dumps(raw)).hexdigest()
    assert raw_id != transaction_id(raw)
    with pytest.raises(MandatePolicyError):
        PaymentSettlementData.parse({"mandate": raw, "transaction_id": raw_id})
    stored = PaymentSettlementData.parse({"mandate": raw, "transaction_id": transaction_id(raw)})
    assert stored.to_wire()["mandate"] == normalized


def test_the_approval_body_keeps_the_null_and_omits_absent_optionals():
    terms = agreement()
    terms["synthetic_null"] = None
    raw = _mandate(_once(None), deal=agreement_hash(terms))
    sent = []

    def service(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        receipt = build_signed_receipt(signer=SERVICE, mandate=raw)
        return httpx.Response(201, json=wire_json(receipt))

    client = PaymentsClient(
        "http://127.0.0.1:9", development_account=BUYER, transport=httpx.MockTransport(service)
    )
    receipt = client.approve(raw, agreement=terms)

    (body,) = sent
    assert body["mandate"] == raw
    assert body["mandate"]["parts"][0]["maxHoldExtension"] is None
    assert "end" not in body["mandate"]["parts"][0]
    assert body["attachments"] == [{"kind": "deal", "content": terms}]
    assert body["attachments"][0]["content"]["synthetic_null"] is None
    assert transaction_id(body["mandate"]) == transaction_id(raw)
    assert receipt.receipt.transaction.root == transaction_id(raw)


def test_a_receipt_and_snapshot_for_a_null_mandate_verify():
    terms = agreement()
    raw = _mandate(_once(None), deal=agreement_hash(terms))
    receipt = build_signed_receipt(signer=SERVICE, mandate=raw)
    assert receipt.receipt.transaction.root == hashlib.sha256(rfc8785.dumps(raw)).hexdigest()
    assert verify_receipt(receipt, SERVICE.identity, mandate=raw, agreement_json=terms, livemode=False)

    payments = FakePaymentsClient(signer=SERVICE)
    payments.approve(raw)
    snapshot = payments.get_transaction(transaction_id(raw))
    assert snapshot.snapshot.transaction.root == transaction_id(raw)
    embedded = snapshot.snapshot.receipt
    assert verify_receipt(embedded, SERVICE.identity, mandate=raw, agreement_json=terms, livemode=False)


def test_the_kit_never_derives_null_and_refuses_it():
    terms = agreement()
    policy = mandate_policy_for_agreement(terms, config())
    derived = derive_mandate(terms, policy)
    assert [part.root.maxHoldExtension.root for part in derived.parts] == ["P0D"]

    unbounded = wire_json(derived)
    unbounded["parts"][0]["maxHoldExtension"] = None
    Mandate.model_validate(unbounded)
    with pytest.raises(MandatePolicyError):
        check(unbounded, terms, policy)
    stored = PaymentSettlementData.parse(
        {"mandate": unbounded, "transaction_id": transaction_id(unbounded)}
    )
    with pytest.raises(MandatePolicyError):
        stored.require_bound_to(terms)


def _generator():
    spec = importlib.util.spec_from_file_location("generate_models", KIT / "scripts" / "generate_models.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vendored() -> dict:
    data = (KIT / "schema" / "payments.schema.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == VENDORED_SCHEMA_SHA256
    return json.loads(data)


def test_generation_changes_exactly_the_two_published_properties():
    generator = _generator()
    published = _vendored()
    before = copy.deepcopy(published)
    normalized = generator.normalized(published)
    assert published == before

    changed = []
    for name, definition in published["$defs"].items():
        if definition != normalized["$defs"][name]:
            changed.append(name)
            for prop, value in definition["properties"].items():
                if normalized["$defs"][name]["properties"][prop] != value:
                    assert value == generator.PUBLISHED_FORM
                    assert normalized["$defs"][name]["properties"][prop] == generator.VALIDATED_FORM
                    assert prop in definition["required"]
    assert sorted(changed) == ["OncePart", "RatePart"]
    assert {k: v for k, v in published.items() if k != "$defs"} == {
        k: v for k, v in normalized.items() if k != "$defs"
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda schema: schema["$defs"]["OncePart"]["properties"].update(
            maxHoldExtension={"anyOf": [{"$ref": "#/$defs/Duration"}, {"type": "null"}]}
        ),
        lambda schema: schema["$defs"]["RatePart"]["properties"].update(
            maxHoldExtension={"$ref": "#/$defs/Duration"}
        ),
        lambda schema: schema["$defs"]["OncePart"]["required"].remove("maxHoldExtension"),
    ],
    ids=["corrected", "not-nullable", "optional"],
)
def test_generation_refuses_a_publication_that_moved_on(change):
    schema = _vendored()
    change(schema)
    with pytest.raises(SystemExit):
        _generator().normalized(schema)
