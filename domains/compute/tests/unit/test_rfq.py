import json
from pathlib import Path

import pytest

from arkhai_compute.rfq import (
    ComputeRfqFilters,
    ComputeRfqRequirements,
    ComputeRfqResponseQuantity,
    ComputeRfqTerm,
    registry_schema,
    validate_filters,
    validate_requirements,
    validate_response_quantity,
)

_TESTS = Path(__file__).resolve().parents[1]
_FIXTURES = _TESTS / "fixtures" / "rfq-wire-cases.json"
_SCHEMA = _TESTS.parent / "registry" / "rfq-schema.json"
_VALIDATORS = {
    "requirements": validate_requirements,
    "search": validate_filters,
    "response_quantity": validate_response_quantity,
}


def _wire_cases():
    for schema, group in json.loads(_FIXTURES.read_text()).items():
        for name, (accepted, override) in group["cases"].items():
            yield pytest.param(_VALIDATORS[schema], group["base"] | override, accepted, id=f"{schema}-{name}")


@pytest.mark.parametrize("validate,body,accepted", tuple(_wire_cases()))
def test_compute_wire_contract(validate, body, accepted):
    if accepted:
        assert validate(body) == body
    else:
        with pytest.raises(ValueError):
            validate(body)


def test_registry_schema_matches_generated_contract():
    assert json.loads(_SCHEMA.read_text()) == registry_schema()



def test_registry_schemas_cover_all_typed_fields():
    schema = registry_schema()
    for definition, model in (
        (schema["requirements"], ComputeRfqRequirements),
        (schema["requirements"]["properties"]["term"], ComputeRfqTerm),
        (schema["search"], ComputeRfqFilters),
        (schema["response_quantity"], ComputeRfqResponseQuantity),
    ):
        assert set(definition.get("required", [])) == model.__required_keys__
        assert definition["properties"].keys() == model.__required_keys__ | model.__optional_keys__
