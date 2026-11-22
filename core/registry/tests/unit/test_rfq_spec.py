import json
from pathlib import Path

import pytest

from core_registry.api.filter_eval import evaluate_path
from core_registry.api.rfq_spec import RfqInputError, load_rfq_spec

_COMPUTE = Path(__file__).resolve().parents[4] / "domains" / "compute"
_SCHEMA = _COMPUTE / "registry" / "rfq-schema.json"
_FIXTURES = json.loads((_COMPUTE / "tests" / "fixtures" / "rfq-wire-cases.json").read_text())


@pytest.fixture
def contract():
    spec = load_rfq_spec(str(_SCHEMA))
    assert spec is not None
    return spec


def _wire_cases():
    for schema, group in _FIXTURES.items():
        for name, (accepted, override) in group["cases"].items():
            yield pytest.param(schema, group["base"] | override, accepted, id=f"{schema}-{name}")


@pytest.mark.parametrize("schema,body,accepted", tuple(_wire_cases()))
def test_registry_agrees_with_compute_wire_cases(contract, schema, body, accepted):
    entry = {
        "requirements": contract.validate_requirements,
        "search": contract.search_criteria,
        "response_quantity": lambda quantity: contract.offered_quantity(
            quantity, request=_FIXTURES["requirements"]["base"]
        ),
    }[schema]
    if accepted:
        entry(body)
    else:
        with pytest.raises(RfqInputError):
            entry(body)


def test_filters_match_hardware_quantity_and_one_of_the_requested_regions(contract):
    body = _FIXTURES["requirements"]["base"]
    assert contract.kind == "compute"
    criteria = contract.search_criteria(
        {"gpu_model": "B300", "min_node_count": 100, "region": "region-two"}
    )
    assert all(evaluate_path(body, criterion) for criterion in criteria)
    assert not all(evaluate_path(body | {"node_count": 99}, criterion) for criterion in criteria)
    assert not all(evaluate_path(body | {"regions": ["region-one"]}, criterion) for criterion in criteria)
    assert not all(evaluate_path(body | {"shape": {"vcpu_count": 16}}, criterion) for criterion in criteria)
    [literal] = contract.search_criteria({"gpu_model": "in:[B300]"})
    assert not evaluate_path(body, literal)


def test_response_can_omit_quantity_or_offer_up_to_the_request(contract):
    request = _FIXTURES["requirements"]["base"]
    assert contract.offered_quantity({}, request=request) is None
    assert contract.offered_quantity({"offered_node_count": 100}, request=request) == 100
    with pytest.raises(RfqInputError, match="rfq_response_quantity_exceeds_request"):
        contract.offered_quantity({"offered_node_count": 101}, request=request)


def test_rfq_validation_is_opt_in():
    assert load_rfq_spec(None) is None


@pytest.mark.parametrize(
    "section,attribute,value",
    [
        ("filters", "op", "not_in"),
        ("filters", "path", "$.shape.missing"),
        ("filters", "path", "$..gpu_model"),
        ("filters", "value_type", "integer"),
        ("filters", "on_missing", "pass"),
        ("fields", "quantity", "start_earliest"),
        ("requirements", "type", "invalid"),
        ("requirements", "$ref", "https://schema.example/not-local"),
        ("requirements", "$ref", "#/$defs/NoSuchDefinition"),
        ("requirements", "additionalProperties", True),
    ],
)
def test_malformed_definitions_refuse_to_load(section, attribute, value, tmp_path):
    document = json.loads(_SCHEMA.read_text())
    changed = document[section]
    if section == "filters":
        changed = changed[0]
    changed[attribute] = value
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(document))

    with pytest.raises(RuntimeError, match="invalid REGISTRY_RFQ_SPEC_PATH configuration"):
        load_rfq_spec(str(path))



def test_schema_rejects_unparsable_paths_and_missing_quantity_bounds(tmp_path):
    path = tmp_path / "schema.json"
    document = json.loads(_SCHEMA.read_text())
    document["filters"][0]["path"] = "$.shape.where"
    document["requirements"]["properties"]["shape"]["properties"]["where"] = {"type": "string"}
    path.write_text(json.dumps(document))
    with pytest.raises(RuntimeError, match="invalid REGISTRY_RFQ_SPEC_PATH configuration"):
        load_rfq_spec(str(path))

    document = json.loads(_SCHEMA.read_text())
    del document["response_quantity"]["properties"]["offered_node_count"]["minimum"]
    path.write_text(json.dumps(document))
    with pytest.raises(RuntimeError, match="invalid REGISTRY_RFQ_SPEC_PATH configuration"):
        load_rfq_spec(str(path))


def test_rfq_filter_names_do_not_inherit_listing_settlement_semantics(tmp_path):
    path = tmp_path / "schema.json"
    document = json.loads(_SCHEMA.read_text())
    document["filters"][0]["name"] = "option_asset"
    search = document["search"]["properties"]
    search["option_asset"] = search.pop("gpu_model")
    path.write_text(json.dumps(document))
    spec = load_rfq_spec(str(path))
    assert spec is not None

    [criterion] = spec.search_criteria({"option_asset": "B300"})
    assert evaluate_path(_FIXTURES["requirements"]["base"], criterion)



@pytest.mark.parametrize("configuration", ["scalar_parent", "tuple_path", "unmapped_key", "nan_bound"])
def test_mapped_fields_remain_typed_and_exhaustive(configuration, tmp_path):
    document = json.loads(_SCHEMA.read_text())
    properties = document["requirements"]["properties"]
    if configuration == "scalar_parent":
        model = properties["shape"]["properties"]["gpu_model"]
        model["properties"] = {"name": {"type": "string"}}
        document["filters"][0]["path"] = "$.shape.gpu_model.name"
    elif configuration == "tuple_path":
        properties["regions"]["prefixItems"] = [{"type": "array"}]
    elif configuration == "unmapped_key":
        document["search"]["patternProperties"] = {"^unknown$": {"type": "string"}}
    else:
        properties["node_count"]["minimum"] = float("nan")
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(document))

    with pytest.raises(RuntimeError, match="invalid REGISTRY_RFQ_SPEC_PATH configuration"):
        load_rfq_spec(str(path))


def test_loaded_schema_cannot_turn_a_local_time_into_a_deadline(tmp_path):
    document = json.loads(_SCHEMA.read_text())
    document["requirements"]["properties"]["respond_by"]["pattern"] = "."
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(document))
    spec = load_rfq_spec(str(path))
    assert spec is not None

    requirements = _FIXTURES["requirements"]["base"] | {"respond_by": "2026-12-15T18:00:00"}
    with pytest.raises(RfqInputError, match="invalid_rfq_requirements"):
        spec.validate_requirements(requirements)
