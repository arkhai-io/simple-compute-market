from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema


class CapacityValidationError(RuntimeError):
    """Raised when a portable capacity contract is internally inconsistent."""


FINITE_STAGE_ORDER = (
    "q0-host-capability",
    "reference-b1",
    "q1-b1-s1-g1",
    "q2-b2-s1-g1",
    "q3-b4-s1-g1",
    "q4-b8-s1-g1",
    "q5-serialized-reuse",
    "q6-b2-s2-g1",
    "q7-b4-s2-g1",
    "q8-b4-s4-g1",
)

_HOST_RECEIPTS = frozenset(
    {
        "cleanup.recorded",
        "controller.authority-checked",
        "host.provisioning-preflight",
    }
)
_REFERENCE_RECEIPTS = frozenset(
    {
        "cleanup.recorded",
        "controller.authority-checked",
        "controller.observation-recorded",
        "controller.reference-request-invoked",
        "host.provisioning-owned",
    }
)
_AGENT_RECEIPTS = frozenset(
    {
        "buyer.demand-frozen",
        "buyer.demand-invoked",
        "buyer.quickstart-read",
        "cleanup.recorded",
        "controller.authority-checked",
        "controller.observation-recorded",
        "controller.release-recorded",
        "host.provisioning-owned",
        "seller.listing-published",
        "seller.quickstart-read",
        "seller.service-ready",
    }
)

# The finite table is an assertion surface, not an adaptive stage generator.
# O/B/S/H/L/R/G order matches the public planning vocabulary.
_STAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "q0-host-capability": {
        "counts": (1, 0, 0, 1, 0, 0, 1),
        "ownership": "host-agent",
        "arrival": "none",
        "barrier": 0,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (0, 0),
        "receipts": _HOST_RECEIPTS,
    },
    "reference-b1": {
        "counts": (1, 1, 1, 1, 1, 1, 1),
        "ownership": "controller-reference",
        "arrival": "none",
        "barrier": 0,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 0),
        "receipts": _REFERENCE_RECEIPTS,
    },
    "q1-b1-s1-g1": {
        "counts": (1, 1, 1, 1, 1, 1, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 1,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 0),
        "receipts": _AGENT_RECEIPTS,
    },
    "q2-b2-s1-g1": {
        "counts": (1, 2, 1, 1, 1, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 2,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 1),
        "receipts": _AGENT_RECEIPTS,
    },
    "q3-b4-s1-g1": {
        "counts": (1, 4, 1, 1, 1, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 3),
        "receipts": _AGENT_RECEIPTS,
    },
    "q4-b8-s1-g1": {
        "counts": (1, 8, 1, 1, 1, 8, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 8,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 7),
        "receipts": _AGENT_RECEIPTS,
    },
    "q5-serialized-reuse": {
        "counts": (1, 1, 1, 1, 1, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "serialized-reuse",
        "barrier": 0,
        "persistent": True,
        "teardown_between": True,
        "outcomes": (2, 0),
        "receipts": _AGENT_RECEIPTS,
    },
    "q6-b2-s2-g1": {
        "counts": (1, 2, 2, 1, 2, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 2,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 1),
        "receipts": _AGENT_RECEIPTS,
    },
    "q7-b4-s2-g1": {
        "counts": (1, 4, 2, 1, 2, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 3),
        "receipts": _AGENT_RECEIPTS,
    },
    "q8-b4-s4-g1": {
        "counts": (1, 4, 4, 1, 4, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "persistent": False,
        "teardown_between": False,
        "outcomes": (1, 3),
        "receipts": _AGENT_RECEIPTS,
    },
}

_COUNT_KEYS = (
    "orchestrators",
    "buyers",
    "sellers",
    "hosts",
    "listings",
    "requests",
    "physical_gpus",
)


def _schema_path(repo_root: Path, name: str) -> Path:
    return repo_root / "tools" / "issue-discovery" / "schemas" / name


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapacityValidationError(f"expected a JSON object: {path}")
    return value


def _schema_errors(value: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _read_object(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def validate_scenario(scenario: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(scenario, _schema_path(repo_root, "capacity-scenario.schema.json"))
    if errors:
        raise CapacityValidationError("scenario validation failed:\n- " + "\n- ".join(errors))

    stage = str(scenario["stage"])
    expected = _STAGE_CONTRACTS[stage]
    counts = scenario["counts"]
    actual_counts = tuple(counts[key] for key in _COUNT_KEYS)
    if actual_counts != expected["counts"]:
        errors.append(
            f"{stage} counts must be O/B/S/H/L/R/G={expected['counts']}, got {actual_counts}"
        )

    distribution = scenario["listings"]["seller_distribution"]
    if len(distribution) != counts["sellers"]:
        errors.append("listings.seller_distribution must have one entry per seller")
    if sum(distribution) != counts["listings"]:
        errors.append("listings.seller_distribution must sum to counts.listings")

    role_contract = scenario["role_contract"]
    if role_contract["ownership"] != expected["ownership"]:
        errors.append(f"{stage} role_contract.ownership must be {expected['ownership']}")
    if role_contract["persistent_buyer_session"] is not expected["persistent"]:
        errors.append(
            f"{stage} persistent_buyer_session must be {str(expected['persistent']).lower()}"
        )
    receipts = frozenset(role_contract["required_receipts"])
    if receipts != expected["receipts"]:
        errors.append(f"{stage} required_receipts do not match its ownership boundary")

    for quickstart_key in ("buyer_quickstart", "seller_quickstart"):
        quickstart = repo_root / role_contract[quickstart_key]
        if not quickstart.is_file():
            errors.append(f"{quickstart_key} does not resolve to a tracked quickstart")

    arrival = scenario["arrival"]
    if arrival["mode"] != expected["arrival"]:
        errors.append(f"{stage} arrival.mode must be {expected['arrival']}")
    if arrival["barrier_participants"] != expected["barrier"]:
        errors.append(f"{stage} barrier_participants must be {expected['barrier']}")
    if arrival["teardown_between_requests"] is not expected["teardown_between"]:
        errors.append(
            f"{stage} teardown_between_requests must be "
            f"{str(expected['teardown_between']).lower()}"
        )

    expectations = scenario["expectations"]
    outcomes = (expectations["successes"], expectations["scarcity"])
    if outcomes != expected["outcomes"]:
        errors.append(f"{stage} successes/scarcity must be {expected['outcomes']}")
    if sum(outcomes) != counts["requests"]:
        errors.append("expectation outcomes must sum to counts.requests")

    if scenario["scenario_id"] != stage:
        errors.append("scenario_id must equal the finite stage identifier")

    if errors:
        raise CapacityValidationError("scenario validation failed:\n- " + "\n- ".join(errors))


def validate_scenario_file(path: Path, repo_root: Path) -> dict[str, Any]:
    scenario = _read_object(path)
    validate_scenario(scenario, repo_root)
    return scenario


def scenario_sha256(scenario: dict[str, Any]) -> str:
    """Return the SHA-256 of canonical, semantic scenario JSON."""

    canonical = json.dumps(scenario, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
