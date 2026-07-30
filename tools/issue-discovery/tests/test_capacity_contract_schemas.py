from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = PACKAGE_ROOT / "schemas"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "capacity" / "v2"
DELETE = object()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(schema_name: str) -> Draft202012Validator:
    schema = load_json(SCHEMA_ROOT / schema_name)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize(
    ("schema_name", "fixture_name", "collection"),
    [
        ("capacity-profile-stage.schema.json", "profile-stage.json", False),
        ("capacity-role-plan.schema.json", "role-plans.json", True),
        ("capacity-role-receipt.schema.json", "role-receipts.json", True),
        ("capacity-frozen-action.schema.json", "frozen-actions.json", True),
        ("capacity-action-result.schema.json", "action-results.json", True),
        ("capacity-result.schema.json", "capacity-result.json", False),
    ],
)
def test_capacity_v2_positive_contract_fixtures(
    schema_name: str,
    fixture_name: str,
    collection: bool,
) -> None:
    value = load_json(FIXTURE_ROOT / fixture_name)
    values = value if collection else [value]
    contract = validator(schema_name)

    assert values
    for item in values:
        contract.validate(item)


def test_all_json_schemas_are_valid_draft_2020_12_contracts() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))

    assert schemas
    for path in schemas:
        Draft202012Validator.check_schema(load_json(path))


@dataclass(frozen=True)
class NegativeCase:
    name: str
    schema_name: str
    fixture_name: str
    item_index: int | None
    path: tuple[str | int, ...]
    replacement: object


NEGATIVE_CASES = [
    NegativeCase(
        "unknown profile-stage key",
        "capacity-profile-stage.schema.json",
        "profile-stage.json",
        None,
        ("private_host_id",),
        "host-17",
    ),
    NegativeCase(
        "missing exact SCM authority",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("scm_ref",),
        DELETE,
    ),
    NegativeCase(
        "unresolved scenario path placeholder",
        "capacity-profile-stage.schema.json",
        "profile-stage.json",
        None,
        ("scenario_binding", "scenario_path"),
        "${SCENARIO_PATH}",
    ),
    NegativeCase(
        "private wallet identity field",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("wallet_address",),
        "0x1234567890abcdef",
    ),
    NegativeCase(
        "executor-local instruction path",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("instruction", "path"),
        "/home/operator/private-buyer.md",
    ),
    NegativeCase(
        "malformed content digest",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("instruction", "sha256"),
        "not-a-sha256",
    ),
    NegativeCase(
        "calendar-invalid lifecycle timestamp",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("lifecycle", "started_at"),
        "not-a-timestamp",
    ),
    NegativeCase(
        "duplicate logical listing identities",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        1,
        ("role_plan", "listing_slots"),
        ["listing-1", "listing-1"],
    ),
    NegativeCase(
        "duplicate native evidence identities",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        3,
        ("role_evidence", "native_evidence_bindings"),
        [
            {
                "method": "hmac-sha256-v1",
                "domain": "scm.capacity.native-evidence.v1",
                "value": "f" * 64,
            },
            {
                "method": "hmac-sha256-v1",
                "domain": "scm.capacity.native-evidence.v1",
                "value": "f" * 64,
            },
        ],
    ),
    NegativeCase(
        "frozen action retry",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("attempt",),
        2,
    ),
    NegativeCase(
        "one-shot result retry",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("attempt",),
        2,
    ),
    NegativeCase(
        "buyer role with seller variant",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("role_plan",),
        {
            "kind": "seller",
            "service_slot": "seller-service-1",
            "listing_slots": ["listing-1"],
            "service_start_action_id": "seller-service-start-1",
            "publication_action_ids": ["seller-publication-1"],
            "required_steps": [
                "install-build",
                "configuration",
                "wallet-preparation",
                "publication-preparation",
                "service-start",
                "listing-publication",
                "observation-liveness",
            ],
        },
    ),
    NegativeCase(
        "buyer action with service-start variant",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("logical_selection",),
        {
            "kind": "seller-service-start",
            "seller_slot": "seller-1",
            "service_slot": "seller-service-1",
        },
    ),
    NegativeCase(
        "wrong topology binding domain",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        2,
        ("role_plan", "topology_authority_binding", "domain"),
        "scm.capacity.reversible-baseline.v1",
    ),
    NegativeCase(
        "wrong native-evidence binding domain",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        3,
        ("role_evidence", "native_evidence_bindings", 0, "domain"),
        "scm.capacity.topology-authority.v1",
    ),
    NegativeCase(
        "wrong runtime binding domain",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("runtime_binding", "domain"),
        "scm.capacity.topology-authority.v1",
    ),
    NegativeCase(
        "wrong baseline binding domain",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        ("baseline", "reversible_baseline_binding", "domain"),
        "scm.capacity.baseline-equivalence.v1",
    ),
    NegativeCase(
        "missing scenario digest authority",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("scenario_sha256",),
        DELETE,
    ),
    NegativeCase(
        "malformed independent result digest",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        ("aggregate_observation_sha256",),
        "a" * 63,
    ),
    NegativeCase(
        "malformed action terminal timestamp",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("terminal_at",),
        "2026-07-30 10:00:03",
    ),
    NegativeCase(
        "cross-role actor identity",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("actor_slot",),
        "seller-1",
    ),
    NegativeCase(
        "emitted result carries failure",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("failure_code",),
        "emission-failed",
    ),
    NegativeCase(
        "private capacity-result identity field",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        ("cloud_project_id",),
        "private-project",
    ),
]


def mutate(value: object, path: tuple[str | int, ...], replacement: object) -> None:
    assert path
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    key = path[-1]
    if replacement is DELETE:
        del cursor[key]  # type: ignore[index]
    else:
        cursor[key] = deepcopy(replacement)  # type: ignore[index]


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=lambda case: case.name)
def test_capacity_v2_contracts_reject_invalid_authority(case: NegativeCase) -> None:
    fixture = load_json(FIXTURE_ROOT / case.fixture_name)
    value = fixture if case.item_index is None else fixture[case.item_index]
    invalid = deepcopy(value)
    mutate(invalid, case.path, case.replacement)

    errors = list(validator(case.schema_name).iter_errors(invalid))

    assert errors, f"{case.name} unexpectedly passed {case.schema_name}"
