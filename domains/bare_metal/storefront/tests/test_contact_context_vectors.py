"""Typed domain vectors and byte-identical acceptance provenance replay."""

import copy
import hashlib
import json
from importlib.resources import files

import pytest
from arkhai_bare_metal import BareMetalListing, BareMetalMessage
from arkhai_bare_metal.contact_contract import (
    MAX_DECLARATION_FILE_BYTES,
    MAX_DECLARATION_OFFERS,
    AcceptedContactContext,
    ContactDeclaration,
    ContactDeclarationOffers,
    parse_contact_declaration_offers,
)
from arkhai_bare_metal_storefront.contact_context import (
    ContactDeclarationSource,
    ContactPublicationIntent, capture_contact_context, validate_accepted_contact_context,
)
from core_storefront.domain_registry import StorefrontDomainBinding, StorefrontListingBinding
from market_contact_exchange import ContactSettlementConfig, contact_accepted_obligation_builder
from market_core.schemas import SettlementOption, SettlementPlan
from market_identity import canonical_json

VECTORS = json.loads(files("market_contact_exchange.fixtures").joinpath("contact_source_v1.json").read_text())
MODELS = {
    "declaration": ContactDeclaration, "publication_intent": ContactPublicationIntent,
    "accepted_context": AcceptedContactContext, "listing": BareMetalListing,
    "declaration_source": ContactDeclarationSource,
    "declaration_offers": ContactDeclarationOffers,
}


@pytest.mark.parametrize("case", [case for case in VECTORS["cases"] if case["carrier"] in MODELS], ids=lambda case: case["id"])
def test_contact_context_vectors(case):
    model = MODELS[case["carrier"]]
    if not case["accepted"]:
        with pytest.raises(ValueError):
            model.model_validate(case["input"])
        with pytest.raises(ValueError):
            model.model_validate_json(json.dumps(case["input"]))
        return
    result = model.model_validate(case["input"]).model_dump(mode="json")
    assert result == case["serialized"]
    assert model.model_validate_json(json.dumps(case["input"])).model_dump(mode="json") == result
    wire = canonical_json(result)
    assert wire.hex() == case["jcs_utf8_hex"]
    assert hashlib.sha256(wire).hexdigest() == case["sha256"]


def test_acceptance_trace_has_exact_context_and_plan():
    for name, model in MODELS.items():
        assert model.model_json_schema() == VECTORS["schemas"][name]
    trace = VECTORS["acceptance_trace"]
    row = dict(trace["listing_binding"])
    domain = StorefrontDomainBinding(**{key: row.pop(key) for key in (
        "offering_mode", "domain_identity", "contract_major", "contract_minor",
    )})
    binding = StorefrontListingBinding(binding=domain, **row)
    context = capture_contact_context(
        binding=binding, listing=BareMetalListing.model_validate(trace["listing"]),
        selected_option=SettlementOption.model_validate(trace["option"]),
        message=BareMetalMessage(duration_seconds=3600, access_method="none"),
    )
    assert context == trace["accepted_context"]
    expected_plan = trace["settlement_plan"]
    built = contact_accepted_obligation_builder(
        ContactSettlementConfig(enabled=True), trace["option"], {
            "buyer_principal": expected_plan["buyer_principal"],
            "seller_principal": expected_plan["seller_principal"],
            "listing_id": trace["declaration"]["listing_id"],
            "expiration_unix": 4102444800, "accepted_context": context,
        },
    )
    plan = SettlementPlan(
        buyer_principal=expected_plan["buyer_principal"], seller_principal=expected_plan["seller_principal"],
        service_terms=built.service_terms, obligations=[built.obligation],
    )
    validate_accepted_contact_context(plan)
    assert plan.model_dump(mode="json") == expected_plan


@pytest.mark.parametrize("case", VECTORS["file_contract"]["raw_cases"], ids=lambda case: case["id"])
def test_contact_declaration_file_bytes(case):
    contract = VECTORS["file_contract"]
    assert MAX_DECLARATION_FILE_BYTES == contract["max_bytes"]
    data = json.dumps(contract["fixture_document"], ensure_ascii=False).encode("utf-8")
    if "pad_to_bytes" in case:
        data += b" " * (case["pad_to_bytes"] - len(data))
    else:
        data = bytes.fromhex(case["utf8_hex"])
    if case["accepted"]:
        assert parse_contact_declaration_offers(data).model_dump(mode="json") == contract["fixture_document"]
    else:
        with pytest.raises(ValueError) as error:
            parse_contact_declaration_offers(data)
        assert str(error.value) == "invalid_contact_declaration_file"


@pytest.mark.parametrize("case", VECTORS["file_contract"]["batch_cases"])
def test_contact_declaration_batch_bound(case):
    contract = VECTORS["file_contract"]
    assert MAX_DECLARATION_OFFERS == contract["max_offers"]
    document = copy.deepcopy(contract["fixture_document"])
    entry = document["offers"][0]
    document["offers"] = []
    for index in range(case["count"]):
        offer = copy.deepcopy(entry)
        offer["declaration"]["listing_id"] = f"declared-contact-example-{index}"
        offer["declaration"]["declaration_id"] = f"declaration-example-{index}"
        document["offers"].append(offer)
    data = json.dumps(document).encode("utf-8")
    assert len(data) < MAX_DECLARATION_FILE_BYTES
    if case["accepted"]:
        assert len(parse_contact_declaration_offers(data).offers) == case["count"]
    else:
        with pytest.raises(ValueError, match="^invalid_contact_declaration_file$"):
            parse_contact_declaration_offers(data)
