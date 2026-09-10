"""Replay the source-owned, language-neutral contact carrier vectors."""

import hashlib
import json
from importlib.resources import files

import pytest
from market_contact_exchange import ContactProfile
from market_contact_exchange.delivery_contract import ContactText, IntroductionReview, parse_contact_text
from market_contact_exchange.source_contract import ContextContactOption
from market_core.schemas import derive_settlement_option_id
from market_identity import canonical_json

VECTORS = json.loads(files("market_contact_exchange.fixtures").joinpath("contact_source_v1.json").read_text())
MODELS = {
    "contact_text": ContactText, "review_v2": IntroductionReview,
    "context_option": ContextContactOption,
}


@pytest.mark.parametrize("case", [case for case in VECTORS["cases"] if case["carrier"] in MODELS], ids=lambda case: case["id"])
def test_contact_source_vectors(case):
    model = MODELS[case["carrier"]]
    if not case["accepted"]:
        with pytest.raises(ValueError):
            model.model_validate(case["input"])
        with pytest.raises(ValueError):
            model.model_validate_json(json.dumps(case["input"]))
        if case["carrier"] == "contact_text":
            with pytest.raises(ValueError) as error:
                parse_contact_text(case["input"])
            assert str(error.value) == case["error"]
        return
    result = model.model_validate(case["input"]).model_dump(mode="json")
    assert result == case["serialized"]
    assert model.model_validate_json(json.dumps(case["input"])).model_dump(mode="json") == result
    wire = canonical_json(result)
    assert wire.hex() == case["jcs_utf8_hex"]
    assert hashlib.sha256(wire).hexdigest() == case["sha256"]


def test_source_schema_and_option_compatibility_matrix():
    assert VECTORS["signed_envelope_version"] == 2
    for name, model in MODELS.items():
        assert model.model_json_schema() == VECTORS["schemas"][name]
    ids = set()
    for option in VECTORS["compatibility_options"].values():
        assert option["option_id"] == derive_settlement_option_id(
            mechanism=option["mechanism"], asset=option["asset"], rates=[], params=option["params"],
        )
        ids.add(option["option_id"])
    assert len(ids) == 3
    legacy = ContactProfile(channel="email", terms="Unchanged terms")
    assert legacy.model_dump() == {"channel": "email", "terms": "Unchanged terms"}
    for value in (None, "future", True):
        with pytest.raises(ValueError):
            ContactProfile(channel="email", terms="terms", context_contract=value)
    with pytest.raises(ValueError, match="requires delivery policy"):
        ContactProfile(channel="email", terms="terms", context_contract="accepted-listing.v1")
