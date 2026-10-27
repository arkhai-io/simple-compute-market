"""The wire models reproduce the API-credits service's OpenAPI components under its label."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arkhai_api.labels import IssuanceLabel
from arkhai_api_contracts import models

BASELINE = Path(__file__).resolve().parents[5] / "domains" / "apicredits" / "service" / "tests" / "fixtures" / "baseline"
COMPONENTS = json.loads((BASELINE / "openapi.json").read_text(encoding="utf-8"))["components"]["schemas"]
API_CREDITS = IssuanceLabel("api-credits", "api-credit-fulfillment.v1")
INFERENCE = IssuanceLabel("inference")


def _without_nulls(value):
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_without_nulls(v) for v in value]
    return value


def _component(model, mode: str) -> dict:
    """The model's schema as the service's OpenAPI document renders it, null defaults omitted."""

    schema = model.model_json_schema(ref_template="#/components/schemas/{model}", mode=mode)
    schema.pop("$defs", None)
    return _without_nulls(schema)


@pytest.mark.parametrize(
    ("model", "mode"),
    [
        (models.issuance_request_model(API_CREDITS), "validation"),
        (models.KeyDisposition, "validation"),
        (models.ConsumeRequest, "validation"),
        (models.ConsumeBatchItem, "validation"),
        (models.ConsumeBatchRequest, "validation"),
        (models.VerifyRequest, "validation"),
        (models.AdjustRequest, "validation"),
        (models.issuance_response_model(API_CREDITS), "serialization"),
        (models.ConsumeBatchResponse, "serialization"),
        (models.KeyListResponse, "serialization"),
        (models.GrantListResponse, "serialization"),
        (models.UsageListResponse, "serialization"),
    ],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_a_wire_model_is_the_recorded_openapi_component(model, mode):
    assert _component(model, mode) == COMPONENTS[model.__name__]


def test_the_response_is_bound_to_its_label_and_carries_the_secret():
    identity = "api-credit-fulfillment.v1:" + "a" * 64
    wire = {
        "schema": API_CREDITS.issuance_result_schema,
        "fulfillment_id": identity,
        "grant_id": identity,
        "negotiation_id": "neg-1",
        # A development value never used on any network.
        "owner": {"scheme": "eip191", "identifier": "0xabcdef0000000000000000000000000000000001"},
        "service": "weather-api",
        "resource_id": "weather-quota",
        "quantity": 3,
        "key_mode": "new",
        "key_id": "ak_1",
        "balance": 3,
        "request_digest": "sha256:" + "b" * 64,
        "committed_at_unix": 2_000_000_000,
        "secret": "ak_1.private",
    }
    response = models.issuance_response_model(API_CREDITS).model_validate(wire)
    assert response.model_dump(mode="json")["secret"] == "ak_1.private"
    assert "private" not in repr(response)
    with pytest.raises(ValidationError):
        models.issuance_response_model(INFERENCE).model_validate(wire)
    assert models.issuance_response_model(API_CREDITS) is models.issuance_response_model(API_CREDITS)


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (models.ConsumeOutcome, {"ok": True, "balance": 1, "unexpected": 1}),
        (models.ConsumeOutcome, {"ok": True}),
        (models.VerifyResponse, {"valid": True, "status": "active", "balance": 1, "unexpected": 1}),
        (models.ConsumeRefusal, {"error": "insufficient_credits", "balance": 0, "unexpected": 1}),
    ],
    ids=["outcome with an unknown field", "outcome missing a field", "verify with an unknown field", "refusal with an unknown field"],
)
def test_a_gate_facing_response_refuses_a_body_it_does_not_declare(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)
