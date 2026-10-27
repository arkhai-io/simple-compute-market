from pathlib import Path

import pytest

from arkhai_api.issuance import issuance_request_model
from arkhai_api.labels import IssuanceLabel

SRC = Path(__file__).resolve().parents[2] / "src" / "arkhai_api"


def test_a_label_spells_every_schema_string():
    label = IssuanceLabel("weather")
    assert label.fulfillment_id_prefix == "weather-fulfillment.v1"
    assert label.issuance_request_schema == "arkhai.weather.issuance-request.v1"
    assert label.issuance_result_schema == "arkhai.weather.issuance-result.v1"
    assert label.evidence_protocol == "arkhai.weather.issuance-evidence.v1"
    assert label.evidence_capability == "weather.issuance.v1"
    assert label.portable_fulfillment_ref_schema == "arkhai.weather.portable-fulfillment-ref.v1"


def test_a_domain_may_keep_the_identity_prefix_its_grants_carry():
    label = IssuanceLabel("weather-api", "weather-fulfillment.v1")
    assert label.fulfillment_id_prefix == "weather-fulfillment.v1"
    assert label.issuance_request_schema == "arkhai.weather-api.issuance-request.v1"


@pytest.mark.parametrize("name", ["", "Weather", "weather_api", "-weather", "weather-", "a" * 65])
def test_a_label_is_lowercase_words_joined_by_hyphens(name):
    with pytest.raises(ValueError):
        IssuanceLabel(name)


@pytest.mark.parametrize("prefix", ["with:colon", "/slash", " "])
def test_the_identity_prefix_is_a_safe_reference(prefix):
    with pytest.raises(ValueError):
        IssuanceLabel("weather", prefix)


def test_equal_labels_bind_one_model_class():
    assert issuance_request_model(IssuanceLabel("weather")) is issuance_request_model(IssuanceLabel("weather"))
    assert issuance_request_model(IssuanceLabel("weather")) is not issuance_request_model(IssuanceLabel("climate"))


def test_the_vocabulary_names_no_domain():
    for module in SRC.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        for value in ("api-credits", "api_credits", "inference"):
            assert value not in text, f"{module.name} names {value!r}"
