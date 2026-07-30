from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import jsonschema
import pytest

from issue_discovery.capacity import CapacityValidationError, validate_scenario


HISTORICAL_V1_REF = "d00b064155b778973e2cc2f37f32896ea8011852"
SCENARIO_SCHEMA_PATH = (
    "tools/issue-discovery/schemas/capacity-scenario.schema.json"
)
FINDING_SCHEMA_PATH = "tools/issue-discovery/schemas/capacity-finding.schema.json"
SCENARIO_FIXTURES = {
    "b1-g1-qualification.json": (
        "81746699963632f8caf757d2aa7ed88154d006ca471a0064baf0b159867e6f2b",
        "e3d5b48c2314890b1ff5c191a18face5ff151bbfb8baffa67c8899a2a389a5d9",
    ),
    "b2-g1-contention.json": (
        "84858e8e1c5b026baa295e234ecef637ab8d617d9aa2808e438800bafc2ee030",
        "dff78da34b800f24423bd3e04c4439eb3f86ab2890a0be7bdb81e5f1e57c17e2",
    ),
    "b2-g2-fulfillment.json": (
        "0bcc09326218a126fee4f55e8ad3f8d1544f35595f751702ba418257e76880a9",
        "0055f8044889f0df318478e700f6630d2c02773a1705cefcffea3d73f5da27b8",
    ),
    "b2-s2-g1-contention.json": (
        "8fcf53bafaf347ea85c230dc74d55171f068968d73880174d2b8570068c5ac24",
        "6bd496788c4e888ad1da6a032c33a75c2b3529f7e13206ef81ac340e3ad5eb61",
    ),
    "b2-s2-g2-fulfillment.json": (
        "8e4c1abd0d81257b0bf8dcfcecdb40c30382b5d3473fc898f5db1c551e3d9a2d",
        "0ed7f056dbdf3fd37fe6ef8afa094eb7d2756f1b87f27671912dcec692c7bae4",
    ),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def fixture_root() -> Path:
    return Path(__file__).parent / "fixtures" / "capacity" / "v1"


def git_blob(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{HISTORICAL_V1_REF}:{path}"],
        cwd=repo_root(),
        check=True,
        capture_output=True,
    ).stdout


def load_historical_json(path: str) -> dict[str, Any]:
    fixture_path = fixture_root() / _fixture_name(path)
    blob = git_blob(path)
    assert fixture_path.read_bytes() == blob
    value = json.loads(fixture_path.read_bytes())
    assert isinstance(value, dict)
    return value


def _fixture_name(path: str) -> str:
    if path == SCENARIO_SCHEMA_PATH:
        return "capacity-scenario.schema.json"
    if path == FINDING_SCHEMA_PATH:
        return "capacity-finding.schema.json"
    if path.endswith("/findings/example.json"):
        return "finding-example.json"
    return Path(path).name


def canonical_sha256(value: dict[str, Any]) -> str:
    canonical = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_historical_v1_schemas_are_pinned_by_blob_identity() -> None:
    assert hashlib.sha256(git_blob(SCENARIO_SCHEMA_PATH)).hexdigest() == (
        "49d211ffbf8e01ad3ae1aafe8e0a235756e99a7d1fed880d95360a34a6d144c1"
    )
    assert hashlib.sha256(git_blob(FINDING_SCHEMA_PATH)).hexdigest() == (
        "41546df0cae8062f1a9b5d253c219696475270f9cab86cfe5f286e41a11797ca"
    )


def test_historical_v1_scenarios_retain_attributable_validation_and_hashes() -> None:
    historical_schema = load_historical_json(SCENARIO_SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(historical_schema)

    for name, (blob_sha256, canonical_digest) in SCENARIO_FIXTURES.items():
        path = f"tools/issue-discovery/config/capacity/{name}"
        blob = git_blob(path)
        scenario = load_historical_json(path)
        assert hashlib.sha256(blob).hexdigest() == blob_sha256
        assert list(validator.iter_errors(scenario)) == []
        assert canonical_sha256(scenario) == canonical_digest

        wave = scenario["wave"]
        listing = scenario["listing"]
        assert wave["requests"] == (
            wave["expected_successes"] + wave["expected_scarcity"]
        )
        assert wave["requests"] <= wave["buyers"]
        assert wave["expected_successes"] <= listing["count"]
        assert len(listing["seller_distribution"]) == wave["sellers"]
        assert sum(listing["seller_distribution"]) == listing["count"]


def test_historical_v1_g2_was_listing_bounded_not_gpu_authorized() -> None:
    scenario = load_historical_json(
        "tools/issue-discovery/config/capacity/b2-g2-fulfillment.json"
    )
    assert scenario["listing"]["count"] == 2
    assert scenario["wave"]["expected_successes"] == 2
    assert "independently_assignable_gpus" not in scenario

    with pytest.raises(CapacityValidationError, match="schema_version"):
        validate_scenario(scenario, repo_root())


def test_historical_v1_finding_fixture_remains_ref_scoped() -> None:
    path = "tools/issue-discovery/config/capacity/findings/example.json"
    blob = git_blob(path)
    finding = load_historical_json(path)
    historical_schema = load_historical_json(FINDING_SCHEMA_PATH)

    assert hashlib.sha256(blob).hexdigest() == (
        "4f906a130169ed9e67869f89e3672ccc47e6c238b1097f4fbf6f137d7d1bfcfe"
    )
    assert list(jsonschema.Draft202012Validator(historical_schema).iter_errors(finding)) == []
    assert finding["schema_version"] == 1
    assert "profile_stage_id" not in finding
    assert "result_sha256" not in finding
    assert "upstream_ref" not in finding["observed"]
