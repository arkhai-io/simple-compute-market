from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from issue_discovery.redaction import Redactor


class CapacityInputError(ValueError):
    """Raised when input text cannot be parsed as capacity JSON at all.

    Distinct from :class:`CapacityValidationError`, which reports a parseable
    document that fails a contract. Callers map the two to different result
    codes, so a malformed file is never reported as a contract failure.
    """


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
        "buyer.same-session-invocation",
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
        "listing_assignment": "none",
        "request_assignment": "none",
        "same_session": False,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (0, 0),
        "receipts": _HOST_RECEIPTS,
    },
    "reference-b1": {
        "counts": (1, 1, 1, 1, 1, 1, 1),
        "ownership": "controller-reference",
        "arrival": "none",
        "barrier": 0,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "controller-reference",
        "same_session": False,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 0),
        "receipts": _REFERENCE_RECEIPTS,
    },
    "q1-b1-s1-g1": {
        "counts": (1, 1, 1, 1, 1, 1, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 1,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 0),
        "receipts": _AGENT_RECEIPTS,
    },
    "q2-b2-s1-g1": {
        "counts": (1, 2, 1, 1, 1, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 2,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 1),
        "receipts": _AGENT_RECEIPTS,
    },
    "q3-b4-s1-g1": {
        "counts": (1, 4, 1, 1, 1, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 3),
        "receipts": _AGENT_RECEIPTS,
    },
    "q4-b8-s1-g1": {
        "counts": (1, 8, 1, 1, 1, 8, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 8,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 7),
        "receipts": _AGENT_RECEIPTS,
    },
    "q5-serialized-reuse": {
        "counts": (1, 1, 1, 1, 1, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "serialized-reuse",
        "barrier": 0,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "single-persistent-buyer",
        "same_session": True,
        "persistent_across_requests": True,
        "teardown_between": True,
        "outcomes": (2, 0),
        "receipts": _AGENT_RECEIPTS,
    },
    "q6-b2-s2-g1": {
        "counts": (1, 2, 2, 1, 2, 2, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 2,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 1),
        "receipts": _AGENT_RECEIPTS,
    },
    "q7-b4-s2-g1": {
        "counts": (1, 4, 2, 1, 2, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
        "teardown_between": False,
        "outcomes": (1, 3),
        "receipts": _AGENT_RECEIPTS,
    },
    "q8-b4-s4-g1": {
        "counts": (1, 4, 4, 1, 4, 4, 1),
        "ownership": "substantive-agents",
        "arrival": "release-barrier",
        "barrier": 4,
        "listing_assignment": "seller-ordinal",
        "request_assignment": "buyer-ordinal",
        "same_session": True,
        "persistent_across_requests": False,
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

_Q0_LIFECYCLE = {
    "applicability": "not-applicable",
    "reservation_identity": "not-applicable",
    "fulfillment_identity": "not-applicable",
    "reservation_fulfillment_correlation_required": False,
    "terminal_status_required": False,
    "versioned_result_required": False,
    "executor_ref_target_correlation": "not-applicable",
    "fulfillment_teardown_required": False,
}

_MARKET_LIFECYCLE = {
    "applicability": "market-request",
    "reservation_identity": "capacity_reservation_id",
    "fulfillment_identity": "fulfillment_id",
    "reservation_fulfillment_correlation_required": True,
    "terminal_status_required": True,
    "versioned_result_required": True,
    "executor_ref_target_correlation": "sanitized-assertion",
    "fulfillment_teardown_required": True,
}


def _schema_path(repo_root: Path, name: str) -> Path:
    return repo_root / "tools" / "issue-discovery" / "schemas" / name


MAX_JSON_NESTING_DEPTH = 100
"""Deepest container nesting accepted in any capacity input.

Every capacity schema nests a handful of levels, so this bound is far above
any admissible document. It exists so that over-nested input is refused by
this contract rather than by whatever recursion limit the running interpreter
happens to impose: interpreters differ in the depth at which the JSON decoder
fails, and some parse depths that others reject. Refusing here keeps the
reported result code identical everywhere.
"""


def json_nesting_depth(text: str) -> int:
    """Return the deepest container nesting in ``text``.

    Scans the raw document rather than a parsed value, because parsing is the
    step this bound protects. String contents are skipped so that brackets
    inside string literals do not count toward depth.
    """

    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif character in "]}":
            depth -= 1
    return deepest


def load_json_text(text: str, path: Path) -> Any:
    """Parse ``text`` as capacity JSON, refusing input that is not parseable.

    Raises :class:`CapacityInputError` for both over-nested and syntactically
    invalid input so that callers report one code for unusable input.
    """

    if json_nesting_depth(text) > MAX_JSON_NESTING_DEPTH:
        raise CapacityInputError(
            f"input nests deeper than {MAX_JSON_NESTING_DEPTH} levels: {path}"
        )
    try:
        return json.loads(text)
    except (RecursionError, UnicodeError) as exc:
        raise CapacityInputError(f"input is not parseable JSON: {path}") from exc


def _read_object(path: Path) -> dict[str, Any]:
    value = load_json_text(path.read_text(encoding="utf-8"), path)
    if not isinstance(value, dict):
        raise CapacityValidationError(f"expected a JSON object: {path}")
    return value


def _schema_errors(value: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _read_object(schema_path)
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = []
    for error in sorted(
        validator.iter_errors(value), key=lambda item: list(item.absolute_path)
    ):
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def validate_scenario(scenario: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(
        scenario, _schema_path(repo_root, "capacity-scenario.schema.json")
    )
    if errors:
        raise CapacityValidationError(
            "scenario validation failed:\n- " + "\n- ".join(errors)
        )

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

    bindings = scenario["bindings"]
    if bindings["listing_assignment"] != expected["listing_assignment"]:
        errors.append(
            f"{stage} bindings.listing_assignment must be {expected['listing_assignment']}"
        )
    if bindings["request_assignment"] != expected["request_assignment"]:
        errors.append(
            f"{stage} bindings.request_assignment must be {expected['request_assignment']}"
        )
    if (bindings["listing_set_sha256"] is None) is not (counts["listings"] == 0):
        errors.append(
            "bindings.listing_set_sha256 must be null exactly when no listings exist"
        )
    if (bindings["demand_set_sha256"] is None) is not (counts["requests"] == 0):
        errors.append(
            "bindings.demand_set_sha256 must be null exactly when no requests exist"
        )

    role_contract = scenario["role_contract"]
    if role_contract["ownership"] != expected["ownership"]:
        errors.append(
            f"{stage} role_contract.ownership must be {expected['ownership']}"
        )
    if (
        role_contract["same_session_prepare_wait_invoke"]
        is not expected["same_session"]
    ):
        errors.append(
            f"{stage} same_session_prepare_wait_invoke must be "
            f"{str(expected['same_session']).lower()}"
        )
    if (
        role_contract["persistent_across_requests"]
        is not expected["persistent_across_requests"]
    ):
        errors.append(
            f"{stage} persistent_across_requests must be "
            f"{str(expected['persistent_across_requests']).lower()}"
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

    expected_lifecycle = (
        _Q0_LIFECYCLE if stage == "q0-host-capability" else _MARKET_LIFECYCLE
    )
    if scenario["lifecycle"] != expected_lifecycle:
        errors.append(f"{stage} lifecycle does not match its request applicability")
    expected_vm_teardown = (
        "not-applicable" if stage == "q0-host-capability" else "immediate"
    )
    if scenario["cleanup"]["vm_teardown"] != expected_vm_teardown:
        errors.append(f"{stage} cleanup.vm_teardown must be {expected_vm_teardown}")
    expected_lease = (
        "not-applicable" if stage == "q0-host-capability" else "backstop-only"
    )
    if scenario["cleanup"]["lease"] != expected_lease:
        errors.append(f"{stage} cleanup.lease must be {expected_lease}")

    if scenario["scenario_id"] != stage:
        errors.append("scenario_id must equal the finite stage identifier")

    if errors:
        raise CapacityValidationError(
            "scenario validation failed:\n- " + "\n- ".join(errors)
        )


def validate_scenario_file(path: Path, repo_root: Path) -> dict[str, Any]:
    scenario = _read_object(path)
    validate_scenario(scenario, repo_root)
    return scenario


def scenario_sha256(scenario: dict[str, Any]) -> str:
    """Return the SHA-256 of canonical, semantic scenario JSON."""

    semantic = json.loads(json.dumps(scenario))
    semantic["role_contract"]["required_receipts"] = sorted(
        semantic["role_contract"]["required_receipts"]
    )
    canonical = json.dumps(semantic, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,159}$")
_SAFE_RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_OBSERVED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,99}$")
_FAILURE_LOCATION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
_CONTRACT_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")
_SUPPORTED_CONTRACT_MAJOR = 1


def _is_default_or_qualified_branch(value: str) -> bool:
    return value in {"dev", "main"} or value.startswith(("origin/", "refs/"))


_DEFECT_CLASSIFICATIONS = frozenset(
    {
        "harness-defect",
        "possible-product-defect",
        "environment-provider-issue",
        "cleanup-failure",
    }
)
_RESULT_STATES = frozenset(
    {
        "assigned",
        "dispatch_pending",
        "dispatching",
        "active",
        "failed",
        "teardown_dispatch_pending",
        "tearing_down",
        "torn_down",
        "teardown_failed",
        "abandoned",
    }
)
_TERMINATIONS = frozenset(
    {
        "completed",
        "timeout",
        "cancelled",
        "partial-launch",
        "role-failure",
        "controller-failure",
    }
)
_FAULT_ORIGINS = frozenset({"harness", "product", "environment-provider"})
_CORRELATION_STATES = frozenset(
    {"satisfied", "failed", "not-observed", "not-applicable"}
)
_EMPTY_CORRELATIONS = {
    "reservation_fulfillment": "not-observed",
    "terminal_status": "not-observed",
    "executor_ref_target": "not-observed",
    "versioned_result": "not-observed",
    "fulfillment_teardown": "not-observed",
}
_Q0_CORRELATIONS = {
    "reservation_fulfillment": "not-applicable",
    "terminal_status": "not-applicable",
    "executor_ref_target": "not-applicable",
    "versioned_result": "not-applicable",
    "fulfillment_teardown": "not-applicable",
}
_SATISFIED_CORRELATIONS = {
    "reservation_fulfillment": "satisfied",
    "terminal_status": "satisfied",
    "executor_ref_target": "satisfied",
    "versioned_result": "satisfied",
    "fulfillment_teardown": "satisfied",
}


def _expect_object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapacityValidationError(f"{label} must be an object")
    missing = sorted(keys - set(value))
    extra = sorted(set(value) - keys)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise CapacityValidationError(f"{label} has {'; '.join(details)}")
    return value


def _expect_string(
    value: Any,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    max_length: int = 480,
) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise CapacityValidationError(f"{label} must be a nonempty bounded string")
    if "\n" in value or "\r" in value:
        raise CapacityValidationError(f"{label} must be a single line")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise CapacityValidationError(f"{label} has an invalid format")
    return value


def _expect_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise CapacityValidationError(f"{label} must be a boolean")
    return value


def _expect_choice(value: Any, label: str, choices: set[str] | frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CapacityValidationError(
            f"{label} must be one of {', '.join(sorted(choices))}"
        )
    return value


def _expect_utc_timestamp(value: Any, label: str) -> str:
    timestamp = _expect_string(
        value,
        label,
        pattern=_OBSERVED_AT_RE,
        max_length=20,
    )
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CapacityValidationError(f"{label} must be a valid UTC date-time") from exc
    return timestamp


def _validate_failure(value: Any, label: str) -> dict[str, str]:
    failure = _expect_object(
        value,
        label,
        {"code", "location", "evidence_summary"},
    )
    return {
        "code": _expect_string(
            failure["code"], f"{label}.code", pattern=_FAILURE_CODE_RE
        ),
        "location": _expect_string(
            failure["location"],
            f"{label}.location",
            pattern=_FAILURE_LOCATION_RE,
        ),
        "evidence_summary": _expect_string(
            failure["evidence_summary"], f"{label}.evidence_summary"
        ),
    }


def _validate_identity_receipt(value: Any, label: str) -> dict[str, str]:
    receipt = _expect_object(
        value,
        label,
        {"contract_version", "fulfillment_id", "capacity_reservation_id", "state"},
    )
    return {
        "contract_version": _expect_string(
            receipt["contract_version"],
            f"{label}.contract_version",
            pattern=_CONTRACT_VERSION_RE,
            max_length=24,
        ),
        "fulfillment_id": _expect_string(
            receipt["fulfillment_id"],
            f"{label}.fulfillment_id",
            pattern=_SAFE_ID_RE,
            max_length=128,
        ),
        "capacity_reservation_id": _expect_string(
            receipt["capacity_reservation_id"],
            f"{label}.capacity_reservation_id",
            pattern=_SAFE_ID_RE,
            max_length=128,
        ),
        "state": _expect_choice(receipt["state"], f"{label}.state", _RESULT_STATES),
    }


def _validate_success_observation(observation: dict[str, Any], label: str) -> None:
    _expect_string(
        observation["capacity_reservation_id"],
        f"{label}.capacity_reservation_id",
        pattern=_SAFE_ID_RE,
        max_length=128,
    )
    fulfillment = _expect_object(
        observation["fulfillment"],
        f"{label}.fulfillment",
        {
            "acceptance",
            "status",
            "result",
            "executor_correlation",
            "teardown_acceptance",
            "teardown_status",
        },
    )
    _validate_identity_receipt(
        fulfillment["acceptance"], f"{label}.fulfillment.acceptance"
    )
    _validate_identity_receipt(fulfillment["status"], f"{label}.fulfillment.status")
    _validate_identity_receipt(
        fulfillment["teardown_acceptance"],
        f"{label}.fulfillment.teardown_acceptance",
    )
    _validate_identity_receipt(
        fulfillment["teardown_status"],
        f"{label}.fulfillment.teardown_status",
    )

    result = _expect_object(
        fulfillment["result"],
        f"{label}.fulfillment.result",
        {
            "kind",
            "schema_version",
            "fulfillment_id",
            "capacity_reservation_id",
            "state",
            "domain_result",
        },
    )
    _expect_string(result["kind"], f"{label}.fulfillment.result.kind", max_length=80)
    if not isinstance(result["schema_version"], int) or isinstance(
        result["schema_version"], bool
    ):
        raise CapacityValidationError(
            f"{label}.fulfillment.result.schema_version must be an integer"
        )
    _expect_string(
        result["fulfillment_id"],
        f"{label}.fulfillment.result.fulfillment_id",
        pattern=_SAFE_ID_RE,
        max_length=128,
    )
    _expect_string(
        result["capacity_reservation_id"],
        f"{label}.fulfillment.result.capacity_reservation_id",
        pattern=_SAFE_ID_RE,
        max_length=128,
    )
    _expect_choice(result["state"], f"{label}.fulfillment.result.state", _RESULT_STATES)
    domain = _expect_object(
        result["domain_result"],
        f"{label}.fulfillment.result.domain_result",
        {"kind", "schema_version", "present"},
    )
    _expect_string(domain["kind"], f"{label}.fulfillment.result.domain_result.kind")
    if not isinstance(domain["schema_version"], int) or isinstance(
        domain["schema_version"], bool
    ):
        raise CapacityValidationError(
            f"{label}.fulfillment.result.domain_result.schema_version must be an integer"
        )
    _expect_bool(domain["present"], f"{label}.fulfillment.result.domain_result.present")

    executor = _expect_object(
        fulfillment["executor_correlation"],
        f"{label}.fulfillment.executor_correlation",
        {"reference_correlated", "target_correlated", "failure_origin"},
    )
    for key in ("reference_correlated", "target_correlated"):
        _expect_bool(executor[key], f"{label}.fulfillment.executor_correlation.{key}")
    if executor["reference_correlated"] and executor["target_correlated"]:
        if executor["failure_origin"] is not None:
            raise CapacityValidationError(
                f"{label}.fulfillment.executor_correlation.failure_origin must be null "
                "when both assertions correlate"
            )
    else:
        _expect_choice(
            executor["failure_origin"],
            f"{label}.fulfillment.executor_correlation.failure_origin",
            _FAULT_ORIGINS,
        )


def _validate_assertion_receipt(
    value: Any,
    label: str,
    *,
    choices: set[str] | frozenset[str],
) -> dict[str, Any]:
    receipt = _expect_object(value, label, {"status", "failure"})
    status = _expect_choice(receipt["status"], f"{label}.status", choices)
    if status == "not-observed":
        _validate_failure(receipt["failure"], f"{label}.failure")
    elif receipt["failure"] is not None:
        raise CapacityValidationError(
            f"{label}.failure must be null unless the assertion was not observed"
        )
    return receipt


def validate_cancellation_receipt(
    receipt: Any,
    *,
    termination: str,
    repo_root: Path,
) -> None:
    """Validate a sanitized capacity-run cancellation receipt."""

    cancellation = _expect_object(
        receipt,
        "result.cancellation",
        {"attempted", "status", "failure"},
    )
    attempted = _expect_bool(cancellation["attempted"], "result.cancellation.attempted")
    cancellation_status = _expect_choice(
        cancellation["status"],
        "result.cancellation.status",
        {"not-required", "succeeded", "failed"},
    )
    if attempted is (cancellation_status == "not-required"):
        raise CapacityValidationError(
            "result.cancellation status must agree with whether cancellation was attempted"
        )
    if cancellation_status == "failed":
        _validate_failure(cancellation["failure"], "result.cancellation.failure")
    elif cancellation["failure"] is not None:
        raise CapacityValidationError(
            "result.cancellation.failure must be null unless cancellation failed"
        )
    if termination != "completed" and attempted is False:
        raise CapacityValidationError(
            "result.cancellation must be attempted for a non-completed termination"
        )
    validate_public_capacity_data(
        cancellation,
        repo_root,
        subject="cancellation receipt",
    )


def validate_cleanup_receipt(receipt: Any, *, repo_root: Path) -> None:
    """Validate a sanitized capacity-run cleanup receipt."""

    cleanup = _expect_object(
        receipt,
        "result.cleanup",
        {"attempted", "status", "zero_residue", "failure"},
    )
    cleanup_attempted = _expect_bool(cleanup["attempted"], "result.cleanup.attempted")
    cleanup_status = _expect_choice(
        cleanup["status"],
        "result.cleanup.status",
        {"succeeded", "failed", "not-attempted"},
    )
    zero_residue = _expect_bool(cleanup["zero_residue"], "result.cleanup.zero_residue")
    if cleanup_attempted is (cleanup_status == "not-attempted"):
        raise CapacityValidationError(
            "result.cleanup status must agree with whether cleanup was attempted"
        )
    if cleanup_status == "succeeded" and zero_residue is False:
        raise CapacityValidationError(
            "result.cleanup.zero_residue must be true when cleanup succeeded"
        )
    if cleanup_status != "succeeded" and zero_residue is True:
        raise CapacityValidationError(
            "result.cleanup.zero_residue must be false unless cleanup succeeded"
        )
    if cleanup_status == "failed":
        _validate_failure(cleanup["failure"], "result.cleanup.failure")
    elif cleanup_status == "not-attempted":
        _validate_failure(cleanup["failure"], "result.cleanup.failure")
    elif cleanup["failure"] is not None:
        raise CapacityValidationError(
            "result.cleanup.failure must be null when cleanup succeeded"
        )
    validate_public_capacity_data(cleanup, repo_root, subject="cleanup receipt")


def validate_capacity_result(
    result: dict[str, Any],
    scenario: dict[str, Any],
    repo_root: Path,
) -> None:
    """Validate one sanitized, non-live capacity receipt document.

    The shape is deliberately implemented here rather than as a third public
    schema: results are an internal CLI boundary, while scenarios and findings
    are the two portable persisted contracts.
    """

    value = _expect_object(
        result,
        "result",
        {
            "schema_version",
            "scenario_id",
            "scenario_sha256",
            "termination",
            "run",
            "role_receipts",
            "serialized_reuse",
            "host_preflight",
            "observations",
            "run_failure",
            "cancellation",
            "cleanup",
        },
    )
    if value["schema_version"] != 1:
        raise CapacityValidationError("result.schema_version must be 1")
    if value["scenario_id"] != scenario["scenario_id"]:
        raise CapacityValidationError("result.scenario_id does not match the scenario")
    expected_scenario_hash = scenario_sha256(scenario)
    if value["scenario_sha256"] != expected_scenario_hash:
        raise CapacityValidationError(
            "result.scenario_sha256 does not match the scenario"
        )
    termination = _expect_choice(
        value["termination"],
        "result.termination",
        _TERMINATIONS,
    )

    run = _expect_object(
        value["run"],
        "result.run",
        {"run_id", "observed_at", "timeout_seconds", "repository", "branch", "sha"},
    )
    timeout_seconds = run["timeout_seconds"]
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 86_400
    ):
        raise CapacityValidationError(
            "result.run.timeout_seconds must be 1 through 86400"
        )
    _expect_string(
        run["run_id"], "result.run.run_id", pattern=_SAFE_RUN_RE, max_length=120
    )
    _expect_utc_timestamp(run["observed_at"], "result.run.observed_at")
    if run["repository"] != "arkhai-io/simple-compute-market":
        raise CapacityValidationError(
            "result.run.repository must be the public SCM repository"
        )
    branch = validate_public_capacity_branch(
        run["branch"],
        repo_root,
        label="result.run.branch",
    )
    _expect_string(run["sha"], "result.run.sha", pattern=_SHA40_RE, max_length=40)
    validate_public_capacity_data(
        {
            "repository": run["repository"],
            "branch": branch,
            "run_id": run["run_id"],
        },
        repo_root,
        subject="capacity run metadata",
    )

    _validate_assertion_receipt(
        value["role_receipts"],
        "result.role_receipts",
        choices={"satisfied", "not-observed"},
    )
    serialized = _validate_assertion_receipt(
        value["serialized_reuse"],
        "result.serialized_reuse",
        choices={"satisfied", "not-observed", "not-applicable"},
    )
    allowed_serialized = (
        {"satisfied", "not-observed"}
        if scenario["stage"] == "q5-serialized-reuse"
        else {"not-applicable"}
    )
    if serialized["status"] not in allowed_serialized:
        raise CapacityValidationError(
            "result.serialized_reuse does not match the scenario arrival contract"
        )

    host = _expect_object(
        value["host_preflight"],
        "result.host_preflight",
        {"status", "failure"},
    )
    host_status = _expect_choice(
        host["status"],
        "result.host_preflight.status",
        {"not-applicable", "succeeded", "failed"},
    )
    if host_status == "failed":
        _validate_failure(host["failure"], "result.host_preflight.failure")
    elif host["failure"] is not None:
        raise CapacityValidationError(
            "result.host_preflight.failure must be null unless the preflight failed"
        )

    observations = value["observations"]
    if not isinstance(observations, list) or len(observations) > 8:
        raise CapacityValidationError(
            "result.observations must be an array of at most 8 items"
        )
    for index, item in enumerate(observations):
        label = f"result.observations[{index}]"
        if not isinstance(item, dict):
            raise CapacityValidationError(f"{label} must be an object")
        outcome = _expect_choice(
            item.get("outcome"),
            f"{label}.outcome",
            {
                "success",
                "http-error",
                "harness-failure",
                "product-failure",
                "environment-provider-failure",
            },
        )
        if outcome == "success":
            expected_keys = {
                "request_ordinal",
                "outcome",
                "capacity_reservation_id",
                "fulfillment",
            }
        elif outcome == "http-error":
            expected_keys = {"request_ordinal", "outcome", "http_status", "detail"}
        else:
            expected_keys = {"request_ordinal", "outcome", "failure"}
        observation = _expect_object(item, label, expected_keys)
        ordinal = observation["request_ordinal"]
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
            or ordinal > 8
        ):
            raise CapacityValidationError(
                f"{label}.request_ordinal must be 1 through 8"
            )
        if outcome == "success":
            _validate_success_observation(observation, label)
        elif outcome == "http-error":
            status = observation["http_status"]
            if (
                not isinstance(status, int)
                or isinstance(status, bool)
                or not 100 <= status <= 599
            ):
                raise CapacityValidationError(
                    f"{label}.http_status must be a valid HTTP status"
                )
            detail = observation["detail"]
            if not isinstance(detail, dict):
                raise CapacityValidationError(f"{label}.detail must be an object")
            if set(detail) == {"error", "reason"}:
                _expect_string(detail["error"], f"{label}.detail.error", max_length=100)
                _expect_string(
                    detail["reason"], f"{label}.detail.reason", max_length=160
                )
            elif set(detail) == {"code"}:
                _expect_string(detail["code"], f"{label}.detail.code", max_length=100)
            else:
                raise CapacityValidationError(
                    f"{label}.detail must contain only error/reason or a sanitized code"
                )
        else:
            _validate_failure(observation["failure"], f"{label}.failure")

    run_failure = value["run_failure"]
    if run_failure is None:
        if termination != "completed":
            raise CapacityValidationError(
                "result.run_failure is required when termination is not completed"
            )
    else:
        failure = _expect_object(
            run_failure,
            "result.run_failure",
            {"origin", "code", "location", "evidence_summary"},
        )
        _expect_choice(
            failure["origin"],
            "result.run_failure.origin",
            _FAULT_ORIGINS,
        )
        _expect_string(
            failure["code"],
            "result.run_failure.code",
            pattern=_FAILURE_CODE_RE,
        )
        _expect_string(
            failure["location"],
            "result.run_failure.location",
            pattern=_FAILURE_LOCATION_RE,
        )
        _expect_string(
            failure["evidence_summary"],
            "result.run_failure.evidence_summary",
        )
        if termination == "completed":
            raise CapacityValidationError(
                "result.run_failure must be null when termination is completed"
            )

    validate_cancellation_receipt(
        value["cancellation"],
        termination=termination,
        repo_root=repo_root,
    )
    validate_cleanup_receipt(value["cleanup"], repo_root=repo_root)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_summary(value: str) -> str:
    return " ".join(value.split()).casefold()


def finding_fingerprint(
    *,
    scenario_sha256_value: str,
    classification: str,
    code: str,
    location: str,
    stable_evidence_summary: str,
) -> str:
    """Hash stable sanitized defect identity, never occurrence metadata."""

    if _SHA256_RE.fullmatch(scenario_sha256_value) is None:
        raise CapacityValidationError("scenario_sha256_value must be a SHA-256 digest")
    if classification not in _DEFECT_CLASSIFICATIONS:
        raise CapacityValidationError("classification is not a finding classification")
    _expect_string(code, "failure.code", pattern=_FAILURE_CODE_RE)
    _expect_string(location, "failure.location", pattern=_FAILURE_LOCATION_RE)
    _expect_string(stable_evidence_summary, "failure.stable_evidence_summary")
    identity = {
        "schema_version": 1,
        "scenario_sha256": scenario_sha256_value,
        "classification": classification,
        "failure": {
            "code": code,
            "location": location,
            "stable_evidence_summary": _normalized_summary(stable_evidence_summary),
        },
    }
    return _canonical_sha256(identity)


def _defect(
    classification: str,
    code: str,
    location: str,
    evidence_summary: str,
    *,
    request_ordinal: int | None = None,
    correlations: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "code": code,
        "location": location,
        "evidence_summary": evidence_summary,
        "request_ordinal": request_ordinal,
        "correlations": dict(correlations or _EMPTY_CORRELATIONS),
    }


def _success_correlations(
    observation: dict[str, Any],
) -> tuple[dict[str, str], dict[str, bool]]:
    fulfillment = observation["fulfillment"]
    acceptance = fulfillment["acceptance"]
    status = fulfillment["status"]
    result = fulfillment["result"]
    teardown_acceptance = fulfillment["teardown_acceptance"]
    teardown_status = fulfillment["teardown_status"]
    reservation_ids = {
        observation["capacity_reservation_id"],
        acceptance["capacity_reservation_id"],
        status["capacity_reservation_id"],
        result["capacity_reservation_id"],
        teardown_acceptance["capacity_reservation_id"],
        teardown_status["capacity_reservation_id"],
    }
    fulfillment_ids = {
        acceptance["fulfillment_id"],
        status["fulfillment_id"],
        result["fulfillment_id"],
        teardown_acceptance["fulfillment_id"],
        teardown_status["fulfillment_id"],
    }
    wire_versions_match = all(
        int(receipt["contract_version"].split(".", 1)[0]) == _SUPPORTED_CONTRACT_MAJOR
        for receipt in (
            acceptance,
            status,
            teardown_acceptance,
            teardown_status,
        )
    )
    identities_match = len(reservation_ids) == 1 and len(fulfillment_ids) == 1
    terminal_status = (
        identities_match and wire_versions_match and status["state"] == "active"
    )
    domain_result = result["domain_result"]
    result_versioned = (
        identities_match
        and result["kind"] == "fulfillment.result.v1"
        and result["schema_version"] == 1
        and result["state"] == "active"
        and domain_result["kind"] == "vm.fulfillment.result.v1"
        and domain_result["schema_version"] == 1
        and domain_result["present"] is True
    )
    executor = fulfillment["executor_correlation"]
    executor_matches = (
        executor["reference_correlated"] is True
        and executor["target_correlated"] is True
    )
    teardown_terminal = (
        identities_match
        and wire_versions_match
        and teardown_acceptance["state"]
        in {
            "teardown_dispatch_pending",
            "tearing_down",
            "torn_down",
            "teardown_failed",
        }
        and teardown_status["state"] == "torn_down"
    )
    correlations = {
        "reservation_fulfillment": "satisfied" if identities_match else "failed",
        "terminal_status": "satisfied" if terminal_status else "failed",
        "executor_ref_target": "satisfied" if executor_matches else "failed",
        "versioned_result": "satisfied" if result_versioned else "failed",
        "fulfillment_teardown": "satisfied" if teardown_terminal else "failed",
    }
    checks = {
        "identities_match": identities_match,
        "wire_versions_match": wire_versions_match,
        "active_status": terminal_status,
        "result_versioned": result_versioned,
        "executor_matches": executor_matches,
        "teardown_terminal": teardown_terminal,
    }
    return correlations, checks


def _finding_from_defect(
    scenario: dict[str, Any],
    result: dict[str, Any],
    defect: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    scenario_hash = scenario_sha256(scenario)
    stable_summary = _normalized_summary(defect["evidence_summary"])
    fingerprint = finding_fingerprint(
        scenario_sha256_value=scenario_hash,
        classification=defect["classification"],
        code=defect["code"],
        location=defect["location"],
        stable_evidence_summary=stable_summary,
    )
    cleanup = result["cleanup"]
    cleanup_proven = (
        cleanup["attempted"] is True
        and cleanup["status"] == "succeeded"
        and cleanup["zero_residue"] is True
        and defect["classification"] != "cleanup-failure"
    )
    finding_cleanup = {
        "attempted": cleanup["attempted"],
        "status": cleanup["status"],
        "zero_residue": cleanup["zero_residue"],
    }
    finding = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "classification": defect["classification"],
        "summary": defect["evidence_summary"][:240],
        "public_context": {
            "repository": result["run"]["repository"],
            "branch": result["run"]["branch"],
            "sha": result["run"]["sha"],
        },
        "scenario": {"id": scenario["scenario_id"], "sha256": scenario_hash},
        "occurrence": {
            "run_id": result["run"]["run_id"],
            "observed_at": result["run"]["observed_at"],
            "termination": result["termination"],
            "timeout_seconds": result["run"]["timeout_seconds"],
            "request_ordinal": defect["request_ordinal"],
        },
        "failure": {
            "code": defect["code"],
            "location": defect["location"],
            "stable_evidence_summary": stable_summary,
        },
        "correlations": defect["correlations"],
        "cancellation": {
            "attempted": result["cancellation"]["attempted"],
            "status": result["cancellation"]["status"],
        },
        "cleanup": finding_cleanup,
        "evidence": [
            {
                "kind": "sanitized-assertion",
                "summary": f"Sanitized assertions for {defect['code']}.",
            }
        ],
        "publication": {
            "eligible": cleanup_proven,
            "reason": "cleanup-proven" if cleanup_proven else "cleanup-failed",
        },
    }
    validate_finding(finding, repo_root)
    return finding


def evaluate_capacity_result(
    scenario: dict[str, Any],
    result: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Evaluate a sanitized receipt without invoking an adapter or subprocess."""

    validate_scenario(scenario, repo_root)
    validate_capacity_result(result, scenario, repo_root)
    expected = scenario["expectations"]
    defects: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    successes = 0
    scarcity_candidates: list[dict[str, Any]] = []

    role_receipts = result["role_receipts"]
    if role_receipts["status"] != "satisfied":
        failure = role_receipts["failure"]
        defects.append(
            _defect(
                "harness-defect",
                failure["code"],
                failure["location"],
                failure["evidence_summary"],
                correlations=(
                    _Q0_CORRELATIONS
                    if scenario["stage"] == "q0-host-capability"
                    else _EMPTY_CORRELATIONS
                ),
            )
        )

    serialized_reuse = result["serialized_reuse"]
    if serialized_reuse["status"] == "not-observed":
        failure = serialized_reuse["failure"]
        defects.append(
            _defect(
                "harness-defect",
                failure["code"],
                failure["location"],
                failure["evidence_summary"],
            )
        )

    run_failure = result["run_failure"]
    if run_failure is not None:
        classification = {
            "harness": "harness-defect",
            "product": "possible-product-defect",
            "environment-provider": "environment-provider-issue",
        }[run_failure["origin"]]
        defects.append(
            _defect(
                classification,
                run_failure["code"],
                run_failure["location"],
                run_failure["evidence_summary"],
                correlations=(
                    _Q0_CORRELATIONS
                    if scenario["stage"] == "q0-host-capability"
                    else _EMPTY_CORRELATIONS
                ),
            )
        )

    host = result["host_preflight"]
    if scenario["stage"] == "q0-host-capability":
        if host["status"] == "failed":
            failure = host["failure"]
            defects.append(
                _defect(
                    "environment-provider-issue",
                    failure["code"],
                    failure["location"],
                    failure["evidence_summary"],
                    correlations=_Q0_CORRELATIONS,
                )
            )
        elif host["status"] != "succeeded":
            defects.append(
                _defect(
                    "harness-defect",
                    "host-preflight-not-observed",
                    "host_preflight",
                    "Q0 did not record the required host provisioning preflight.",
                    correlations=_Q0_CORRELATIONS,
                )
            )
    elif host["status"] == "failed":
        failure = host["failure"]
        defects.append(
            _defect(
                "environment-provider-issue",
                failure["code"],
                failure["location"],
                failure["evidence_summary"],
            )
        )

    ordinals = [item["request_ordinal"] for item in result["observations"]]
    expected_ordinals = list(range(1, scenario["counts"]["requests"] + 1))
    if sorted(ordinals) != expected_ordinals:
        defects.append(
            _defect(
                "harness-defect",
                "request-observation-set-mismatch",
                "observations",
                "The sanitized result did not contain exactly one observation per request ordinal.",
            )
        )

    for observation in sorted(
        result["observations"], key=lambda item: item["request_ordinal"]
    ):
        ordinal = observation["request_ordinal"]
        outcome = observation["outcome"]
        if outcome == "success":
            correlations, checks = _success_correlations(observation)
            if not checks["identities_match"]:
                defect = _defect(
                    "possible-product-defect",
                    "reservation-fulfillment-mismatch",
                    "fulfillment_correlation",
                    "Reservation and fulfillment identities did not correlate across lifecycle receipts.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            elif not checks["wire_versions_match"]:
                defect = _defect(
                    "possible-product-defect",
                    "fulfillment-wire-contract-mismatch",
                    "fulfillment_contract",
                    "The fulfillment lifecycle receipts did not use the current wire contract version.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            elif not checks["active_status"]:
                defect = _defect(
                    "possible-product-defect",
                    "active-status-not-observed",
                    "fulfillment_status",
                    "The successful request did not record an active fulfillment status before result validation.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            elif not checks["result_versioned"]:
                defect = _defect(
                    "possible-product-defect",
                    "versioned-result-mismatch",
                    "fulfillment_result",
                    "The successful request did not expose the current versioned VM fulfillment result envelopes.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            elif not checks["executor_matches"]:
                executor_origin = observation["fulfillment"]["executor_correlation"][
                    "failure_origin"
                ]
                defect = _defect(
                    {
                        "harness": "harness-defect",
                        "product": "possible-product-defect",
                        "environment-provider": "environment-provider-issue",
                    }[executor_origin],
                    "executor-ref-target-mismatch",
                    "executor_correlation",
                    "The sanitized executor reference and target assertion did not correlate.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            elif not checks["teardown_terminal"]:
                defect = _defect(
                    "cleanup-failure",
                    "fulfillment-teardown-not-terminal",
                    "fulfillment_teardown",
                    "The fulfillment did not reach correlated terminal teardown.",
                    request_ordinal=ordinal,
                    correlations=correlations,
                )
            else:
                successes += 1
                evaluated.append(
                    {
                        "request_ordinal": ordinal,
                        "classification": "success",
                        "correlations": correlations,
                    }
                )
                continue
            defects.append(defect)
            evaluated.append(
                {
                    "request_ordinal": ordinal,
                    "classification": defect["classification"],
                    "correlations": correlations,
                }
            )
        elif outcome == "http-error":
            detail = observation["detail"]
            if (
                observation["http_status"] == 409
                and detail.get("error") == "offer_unfulfillable"
                and detail.get("reason") == "no_matching_inventory"
            ):
                scarcity_candidates.append(observation)
            else:
                if observation["http_status"] != 409:
                    code = "unexpected-http-status"
                    summary = "Request returned an HTTP status other than the expected scarcity status."
                elif "code" in detail:
                    code = "unexpected-http-conflict"
                    summary = "HTTP 409 carried a sanitized conflict code rather than the exact scarcity contract."
                elif detail["error"] != "offer_unfulfillable":
                    code = "unexpected-scarcity-error"
                    summary = "HTTP 409 carried an error code other than the exact scarcity contract."
                else:
                    code = "unexpected-scarcity-reason"
                    summary = "HTTP 409 carried a reason other than the exact scarcity contract."
                defect = _defect(
                    "possible-product-defect",
                    code,
                    "request_result",
                    summary,
                    request_ordinal=ordinal,
                )
                defects.append(defect)
                evaluated.append(
                    {
                        "request_ordinal": ordinal,
                        "classification": defect["classification"],
                        "correlations": dict(_EMPTY_CORRELATIONS),
                    }
                )
        else:
            failure = observation["failure"]
            classification = {
                "harness-failure": "harness-defect",
                "product-failure": "possible-product-defect",
                "environment-provider-failure": "environment-provider-issue",
            }[outcome]
            defect = _defect(
                classification,
                failure["code"],
                failure["location"],
                failure["evidence_summary"],
                request_ordinal=ordinal,
            )
            defects.append(defect)
            evaluated.append(
                {
                    "request_ordinal": ordinal,
                    "classification": classification,
                    "correlations": dict(_EMPTY_CORRELATIONS),
                }
            )

    expected_scarcity = expected["scarcity"]
    for index, observation in enumerate(
        sorted(scarcity_candidates, key=lambda item: item["request_ordinal"])
    ):
        ordinal = observation["request_ordinal"]
        if index < expected_scarcity:
            classification = "expected-scarcity"
        else:
            classification = "possible-product-defect"
            defects.append(
                _defect(
                    classification,
                    "unexpected-scarcity-count",
                    "request_result",
                    "More requests reached exact inventory scarcity than the finite scenario permits.",
                    request_ordinal=ordinal,
                )
            )
        evaluated.append(
            {
                "request_ordinal": ordinal,
                "classification": classification,
                "correlations": dict(_EMPTY_CORRELATIONS),
            }
        )

    if successes > expected["successes"]:
        defects.append(
            _defect(
                "possible-product-defect",
                "unexpected-success-count",
                "observations",
                (
                    f"Observed {successes} successful durable fulfillments where the finite "
                    f"scenario permits {expected['successes']}."
                ),
                correlations=_SATISFIED_CORRELATIONS,
            )
        )

    cancellation = result["cancellation"]
    if cancellation["status"] == "failed":
        failure = cancellation["failure"]
        defects.append(
            _defect(
                "harness-defect",
                failure["code"],
                failure["location"],
                failure["evidence_summary"],
            )
        )

    cleanup = result["cleanup"]
    cleanup_proven = (
        cleanup["attempted"] is True
        and cleanup["status"] == "succeeded"
        and cleanup["zero_residue"] is True
    )
    if not cleanup_proven:
        failure = cleanup["failure"] or {
            "code": "cleanup-not-proven",
            "location": "cleanup",
            "evidence_summary": "Cleanup did not prove an attempted, successful zero-residue baseline.",
        }
        if not any(
            item["classification"] == "cleanup-failure"
            and item["code"] == failure["code"]
            and item["location"] == failure["location"]
            for item in defects
        ):
            defects.append(
                _defect(
                    "cleanup-failure",
                    failure["code"],
                    failure["location"],
                    failure["evidence_summary"],
                )
            )

    if scenario["stage"] == "q0-host-capability":
        for defect in defects:
            defect["correlations"] = dict(_Q0_CORRELATIONS)

    findings = [
        _finding_from_defect(scenario, result, defect, repo_root) for defect in defects
    ]
    priority = (
        "cleanup-failure",
        "harness-defect",
        "environment-provider-issue",
        "possible-product-defect",
    )
    classification = next(
        (
            name
            for name in priority
            if any(item["classification"] == name for item in defects)
        ),
        "success",
    )
    if classification == "success" and successes == 0 and expected_scarcity:
        classification = "expected-scarcity"
    return {
        "schema_version": 1,
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": scenario_sha256(scenario),
        "termination": result["termination"],
        "run": dict(result["run"]),
        "role_receipts": {"status": role_receipts["status"]},
        "serialized_reuse": {"status": serialized_reuse["status"]},
        "classification": classification,
        "counts": {
            "success": successes,
            "expected_scarcity": min(len(scarcity_candidates), expected_scarcity),
            "findings": len(findings),
        },
        "observations": sorted(evaluated, key=lambda item: item["request_ordinal"]),
        "cancellation": {
            "attempted": cancellation["attempted"],
            "status": cancellation["status"],
        },
        "cleanup": {
            "attempted": cleanup["attempted"],
            "status": cleanup["status"],
            "zero_residue": cleanup["zero_residue"],
        },
        "findings": findings,
    }


def _iter_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_iter_string_values(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_iter_string_values(item))
        return strings
    return []


_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:password|secret|token|api[_-]?key|private[_-]?key|"
    r"access[_-]?key|credential)\s*[:=]\s*\S+"
)
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
    r"glpat-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|"
    r"(?:AKIA|ASIA)[A-Z0-9]{12,}|"
    r"sk-(?:(?:ant|proj|svcacct)-)?[A-Za-z0-9_-]{8,}|"
    r"[sr]k_(?:live|test)_[A-Za-z0-9]+|npm_[A-Za-z0-9]+|"
    r"pypi-[A-Za-z0-9_-]+|"
    r"xox[a-z]-[A-Za-z0-9-]+|ya29\.[A-Za-z0-9_-]+|"
    r"4/0A[A-Za-z0-9_-]+|Bearer\s+\S+)",
    re.IGNORECASE,
)
_JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,}\."
    r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}"
    r"(?![A-Za-z0-9_-])"
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)\b(?:proxy-)?authorization\s*[:=]\s*basic\s+\S+"
)
_BASIC_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\bbasic\s+([A-Za-z0-9+/]{8,}={0,2})(?![A-Za-z0-9+/=])"
)
_SSH_IDENTITY_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b(?:ssh-(?:ed25519|rsa)(?:-cert-v01@openssh\.com)?|"
    r"ecdsa-sha2-[^\s]+|sk-ssh-ed25519@openssh\.com)"
    r"\s+[A-Za-z0-9+/]{16,}={0,3}|"
    r"\bSHA256:[A-Za-z0-9+/]{16,}={0,3})"
)
_EVM_VALUE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])0x(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9a-f])"
)
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9_])(?:"
    r"[A-Za-z]:[\\/]|\\\\[^\\\s]+\\[^\\\s]+|"
    r"~[\\/]|\.\.?[\\/]|\.ssh[\\/]|"
    r"/(?:[A-Za-z0-9._~+-]+(?:/|$)))"
)
_PATH_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:path|file|directory|dir|cwd|workspace|home)\s*[:=]\s*\S+"
)
_ADDRESS_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IP_CANDIDATE_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:\[[0-9A-Fa-f:.%]+\]|[0-9A-Fa-f:.%]{2,})(?![0-9A-Za-z])"
)
_MAC_PATTERN = re.compile(
    r"(?i)\b(?:[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}|"
    r"[0-9a-f]{4}(?:\.[0-9a-f]{4}){2})\b"
)
_HOSTNAME_PATTERN = re.compile(
    r"(?i)\b(?:localhost|"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:invalid|internal|local|localdomain|localhost|lan|home|corp))"
    r"(?::\d{1,5})?\b"
)
_HOST_PORT_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9.-])"
    r"([a-z][a-z0-9-]{0,62}(?:\.[a-z0-9-]{1,63})*):([0-9]{1,5})\b"
)
_HOSTISH_LABELS = frozenset(
    {
        "bastion",
        "controller",
        "devbox",
        "gateway",
        "host",
        "localhost",
        "machine",
        "node",
        "router",
        "server",
        "tower",
        "worker",
    }
)
_COMMON_NETWORK_PORTS = frozenset(
    {
        21,
        22,
        25,
        53,
        80,
        110,
        143,
        443,
        465,
        587,
        993,
        995,
        2222,
        2375,
        2376,
        5432,
        6379,
        8000,
        8080,
        8443,
    }
)
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CONTROL_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]"
)
_OPAQUE_IDENTITY_PATTERN = re.compile(
    r"(?i)\b(?:capacity_reservation_id|fulfillment_id|executor_ref|"
    r"executor_target|wallet_id|wallet_address|project_id|project_number|"
    r"account_id|host_id)"
    r"\s*[:=]\s*\S+"
)
_PRIVATE_REFERENCE_PATTERN = re.compile(
    r"(?i)(?:internal[-_ ]infra|agent[-_ ]orchestration|"
    r"(?:private|internal)[-_ ](?:repository|branch|ref|sha))"
)


def _contains_ip_address(text: str) -> bool:
    for match in _IP_CANDIDATE_PATTERN.finditer(text):
        candidate = match.group(0).strip("[]")
        if ":" not in candidate and "." not in candidate:
            continue
        candidate = candidate.split("%", 1)[0]
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def _contains_basic_credential(text: str) -> bool:
    for match in _BASIC_CREDENTIAL_PATTERN.finditer(text):
        encoded = match.group(1)
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if b":" in decoded:
            return True
    return False


def _contains_host_port(text: str) -> bool:
    for match in _HOST_PORT_PATTERN.finditer(text):
        hostname = match.group(1).lower()
        port = int(match.group(2))
        if not 1 <= port <= 65_535:
            continue
        if (
            "." in hostname
            or "-" in hostname
            or hostname in _HOSTISH_LABELS
            or port in _COMMON_NETWORK_PORTS
        ):
            return True
    return False


def _public_capacity_privacy_errors(
    value: Any,
    repo_root: Path,
    *,
    subject: str,
) -> list[str]:
    redactions_path = (
        repo_root / "tools" / "issue-discovery" / "config" / "redactions.yaml"
    )
    if not redactions_path.is_file():
        return ["configured public redaction rules are unavailable"]
    redactor = Redactor.from_file(redactions_path)
    for text in _iter_string_values(value):
        if redactor.redact(text) != text:
            return [f"{subject} contains text matched by configured redaction rules"]
        if "\n" in text or "\r" in text or _CONTROL_PATTERN.search(text):
            return [f"{subject} contains multiline or raw-log-shaped text"]
        if (
            "-----BEGIN " in text
            or _CREDENTIAL_PATTERN.search(text)
            or _TOKEN_PATTERN.search(text)
            or _JWT_PATTERN.search(text)
            or _AUTHORIZATION_PATTERN.search(text)
            or _contains_basic_credential(text)
            or _SSH_IDENTITY_PATTERN.search(text)
            or _EVM_VALUE_PATTERN.search(text)
        ):
            return [f"{subject} contains a credential-shaped value"]
        if _PRIVATE_PATH_PATTERN.search(text) or _PATH_ASSIGNMENT_PATTERN.search(text):
            return [f"{subject} contains a filesystem path"]
        if (
            _ADDRESS_PATTERN.search(text)
            or _contains_ip_address(text)
            or _MAC_PATTERN.search(text)
            or _HOSTNAME_PATTERN.search(text)
            or _contains_host_port(text)
            or "://" in text
        ):
            return [f"{subject} contains a raw network address or URL"]
        if _EMAIL_PATTERN.search(text):
            return [f"{subject} contains an account-shaped value"]
        if _OPAQUE_IDENTITY_PATTERN.search(text):
            return [f"{subject} contains an opaque runtime identity"]
        if _PRIVATE_REFERENCE_PATTERN.search(text):
            return [f"{subject} contains a private repository or ref shape"]
    return []


def validate_public_capacity_data(
    value: Any,
    repo_root: Path,
    *,
    subject: str,
) -> None:
    """Reject private or credential-shaped text before public serialization."""

    errors = _public_capacity_privacy_errors(value, repo_root, subject=subject)
    if errors:
        raise CapacityValidationError(
            f"{subject} privacy validation failed:\n- " + "\n- ".join(errors)
        )


def validate_public_capacity_branch(
    value: Any,
    repo_root: Path,
    *,
    label: str,
) -> str:
    """Validate one canonical public working-branch name without Git execution."""

    branch = _expect_string(value, label, pattern=_SAFE_BRANCH_RE, max_length=160)
    components = branch.split("/")
    pseudo_refs = {
        "HEAD",
        "FETCH_HEAD",
        "ORIG_HEAD",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
    }
    if (
        _is_default_or_qualified_branch(branch)
        or branch in pseudo_refs
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or branch.endswith(("/", ".", ".lock"))
        or any(
            not component or component.startswith(".") or component.endswith(".lock")
            for component in components
        )
    ):
        raise CapacityValidationError(f"{label} must be a canonical non-default branch")
    validate_public_capacity_data(branch, repo_root, subject=label)
    return branch


def validate_finding(finding: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(
        finding,
        _schema_path(repo_root, "capacity-finding.schema.json"),
    )
    if not errors:
        try:
            validate_public_capacity_branch(
                finding["public_context"]["branch"],
                repo_root,
                label="public_context.branch",
            )
        except CapacityValidationError as exc:
            errors.append(str(exc))
        if finding["scenario"]["id"] not in FINITE_STAGE_ORDER:
            errors.append("scenario.id must be one of the finite VM/G1 stages")
        try:
            _expect_utc_timestamp(
                finding["occurrence"]["observed_at"],
                "occurrence.observed_at",
            )
        except CapacityValidationError as exc:
            errors.append(str(exc))
        cancellation = finding["cancellation"]
        if cancellation["attempted"] is (cancellation["status"] == "not-required"):
            errors.append(
                "cancellation status must agree with whether cancellation was attempted"
            )
        if (
            finding["occurrence"]["termination"] != "completed"
            and cancellation["attempted"] is False
        ):
            errors.append(
                "non-completed termination requires a bounded cancellation attempt"
            )
        cleanup = finding["cleanup"]
        if cleanup["attempted"] is (cleanup["status"] == "not-attempted"):
            errors.append(
                "cleanup status must agree with whether cleanup was attempted"
            )
        if (cleanup["status"] == "succeeded") is not cleanup["zero_residue"]:
            errors.append(
                "cleanup zero_residue must be true exactly when cleanup succeeded"
            )
        cleanup_proven = (
            cleanup["attempted"] is True
            and cleanup["status"] == "succeeded"
            and cleanup["zero_residue"] is True
            and finding["classification"] != "cleanup-failure"
        )
        publication = finding["publication"]
        if publication != {
            "eligible": cleanup_proven,
            "reason": "cleanup-proven" if cleanup_proven else "cleanup-failed",
        }:
            errors.append("publication must be derived from proven cleanup eligibility")
        expected_fingerprint = finding_fingerprint(
            scenario_sha256_value=finding["scenario"]["sha256"],
            classification=finding["classification"],
            code=finding["failure"]["code"],
            location=finding["failure"]["location"],
            stable_evidence_summary=finding["failure"]["stable_evidence_summary"],
        )
        if finding["fingerprint"] != expected_fingerprint:
            errors.append(
                "fingerprint does not match sanitized semantic defect identity"
            )
        if finding["failure"]["stable_evidence_summary"] != _normalized_summary(
            finding["failure"]["stable_evidence_summary"]
        ):
            errors.append("stable_evidence_summary must use its normalized public form")

        correlations = finding["correlations"]
        if finding["scenario"]["id"] == "q0-host-capability":
            if correlations != _Q0_CORRELATIONS:
                errors.append(
                    "Q0 findings require not-applicable lifecycle correlations"
                )
        elif "not-applicable" in correlations.values():
            errors.append(
                "market-request findings cannot use not-applicable lifecycle correlations"
            )

        errors.extend(
            _public_capacity_privacy_errors(
                finding,
                repo_root,
                subject="finding",
            )
        )
    if errors:
        raise CapacityValidationError(
            "finding validation failed:\n- " + "\n- ".join(errors)
        )


def validate_finding_file(path: Path, repo_root: Path) -> dict[str, Any]:
    finding = _read_object(path)
    validate_finding(finding, repo_root)
    return finding
