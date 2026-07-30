from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema


SCM_BRANCH = "feat/issue-discovery-harness"
INFRA_BRANCH = "tools/agent-orchestration-scratch"
CAPACITY_SCENARIO_ROOT = PurePosixPath(
    "tools/issue-discovery/config/capacity/scenarios"
)
CAPACITY_SCENARIO_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-scenario.schema.json"
)
CAPACITY_PROFILE_REGISTRY_SCHEMA = "capacity-profile-registry.schema.json"
CAPACITY_PROFILE_ROOT = PurePosixPath(
    "tools/issue-discovery/config/capacity/profiles"
)
CAPACITY_PROFILE_PATH = CAPACITY_PROFILE_ROOT / "g1-v2.json"
CAPACITY_PROFILE_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-profile-registry.schema.json"
)
CAPACITY_PROFILE_STAGE_ROOT = PurePosixPath(
    "tools/issue-discovery/config/capacity/profile-stages"
)
CAPACITY_MOCK_STAGE_PATH = CAPACITY_PROFILE_STAGE_ROOT / "b1-s1-g1-mock.json"
CAPACITY_PROFILE_STAGE_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-profile-stage.schema.json"
)

FROZEN_G1_SCENARIO_IDS = (
    "b1-s1-g1",
    "b2-s1-g1",
    "b3-s1-g1",
    "b4-s1-g1",
    "b5-s1-g1",
    "b6-s1-g1",
    "b7-s1-g1",
    "b8-s1-g1",
    "serialized-reuse-a",
    "serialized-reuse-b",
    "b2-s2-g1",
    "b4-s2-g1",
    "b4-s3-g1",
    "b4-s4-g1",
)
QUALIFICATION_STAGE_ORDER = (
    "observer-probe",
    "b1-s1-g1-reference",
    "b1-s1-g1-qualification",
    "b2-s1-g1-qualification",
    "serialized-reuse-a-qualification",
    "serialized-reuse-b-qualification",
    "b2-s2-g1-qualification",
)
MEASURED_INITIAL_BUYER_ORDER = (
    "q0-b1-s1-g1-measured",
    "b2-s1-g1-measured",
    "b4-s1-g1-measured",
    "b8-s1-g1-measured",
)
MEASURED_BUYER_REFINEMENT_STAGES = (
    "b3-s1-g1-measured",
    "b5-s1-g1-measured",
    "b6-s1-g1-measured",
    "b7-s1-g1-measured",
)
MEASURED_REUSE_ORDER = (
    "serialized-reuse-a-measured",
    "serialized-reuse-b-measured",
)
MEASURED_SELLER_STAGES = (
    "b2-s2-g1-measured",
    "b4-s2-g1-measured",
    "b4-s4-g1-measured",
    "b4-s3-g1-measured",
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNRESOLVED_MARKERS = (
    "${",
    "<placeholder",
    "change-me",
    "changeme",
    "placeholder",
    "tbd",
    "todo",
)
_PROFILE_VALIDATION_TOKEN = object()
_PROFILE_STAGE_VALIDATION_TOKEN = object()


class CapacityValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PinnedScenario:
    """A scenario whose content and identity were reproduced from one Git commit."""

    scenario_id: str
    scm_ref: str
    relative_path: str
    scenario_sha256: str
    _canonical_bytes: bytes = field(repr=False)

    @property
    def scenario(self) -> dict[str, Any]:
        value = json.loads(self._canonical_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise CapacityValidationError("pinned scenario snapshot is not an object")
        return value


@dataclass(frozen=True, slots=True)
class ValidatedProfileRegistry:
    """An exact profile registry snapshot accepted by public validation."""

    profile_id: str
    scm_ref: str | None
    relative_path: str | None
    canonical_sha256: str
    raw_sha256: str
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def registry(self) -> dict[str, Any]:
        value = json.loads(self._canonical_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise CapacityValidationError("validated profile snapshot is not an object")
        return value


@dataclass(frozen=True, slots=True)
class ValidatedProfileStage:
    """One Git-pinned profile-stage authority and its pinned scenario."""

    stage_id: str
    scm_ref: str
    relative_path: str
    canonical_sha256: str
    registry_sha256: str | None
    repo_root: Path
    scenario: PinnedScenario | None
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def stage(self) -> dict[str, Any]:
        value = json.loads(self._canonical_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise CapacityValidationError(
                "validated profile-stage snapshot is not an object"
            )
        return value


def _schema_path(repo_root: Path, name: str) -> Path:
    return repo_root / "tools" / "issue-discovery" / "schemas" / name


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapacityValidationError(f"expected a JSON object: {path}")
    return value


def _schema_errors(value: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _read_object(schema_path)
    return _validation_errors(value, schema)


def _validation_errors(
    value: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for error in sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _strict_json_object(content: bytes, *, source: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value!r} is not valid")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CapacityValidationError(f"invalid JSON object at {source}: {error}") from error
    if not isinstance(value, dict):
        raise CapacityValidationError(f"expected a JSON object: {source}")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a portable artifact with the public deterministic JSON algorithm."""
    try:
        canonical = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise CapacityValidationError(f"value cannot be canonicalized: {error}") from error
    return (canonical + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of a portable artifact's canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _contains_unresolved_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in _UNRESOLVED_MARKERS)
    if isinstance(value, dict):
        return any(
            _contains_unresolved_placeholder(key)
            or _contains_unresolved_placeholder(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_unresolved_placeholder(item) for item in value)
    return False


def _validate_exact_slots(
    slots: object,
    counts: object,
    *,
    errors: list[str],
) -> None:
    role_names = ("observers", "buyers", "sellers", "host_operators")
    if not isinstance(slots, dict) or not isinstance(counts, dict):
        return
    all_slots: list[str] = []
    for role_name in role_names:
        role_slots = slots.get(role_name)
        role_count = counts.get(role_name)
        if not isinstance(role_slots, list) or not all(
            isinstance(item, str) for item in role_slots
        ):
            continue
        if role_count != len(role_slots):
            errors.append(
                f"actor_counts.{role_name} must equal the number of declared "
                f"actor_slots.{role_name}"
            )
        if len(role_slots) != len(set(role_slots)):
            errors.append(f"actor_slots.{role_name} must contain distinct slots")
        all_slots.extend(role_slots)
    if len(all_slots) != len(set(all_slots)):
        errors.append("logical actor slots must be distinct across all roles")
    if counts.get("observers") != 1:
        errors.append("current G1 scenario shapes require exactly one observer")
    if counts.get("host_operators") != 1:
        errors.append("current G1 scenario shapes require exactly one host operator")


def _validate_seller_topology(
    scenario: dict[str, Any],
    *,
    errors: list[str],
) -> dict[str, str]:
    topology = scenario.get("listing_topology")
    actor_slots = scenario.get("actor_slots")
    load_counts = scenario.get("load_counts")
    if (
        not isinstance(topology, dict)
        or not isinstance(actor_slots, dict)
        or not isinstance(load_counts, dict)
    ):
        return {}

    sellers = topology.get("sellers")
    if not isinstance(sellers, list):
        return {}
    expected_authority_mode = (
        "single-seller"
        if len(sellers) == 1
        else "shared-globally-fenced"
    )
    if topology.get("capacity_authority_mode") != expected_authority_mode:
        errors.append(
            "listing_topology.capacity_authority_mode must be "
            f"{expected_authority_mode} for the declared seller topology"
        )

    declared_sellers = actor_slots.get("sellers")
    seller_slots: list[str] = []
    service_slots: list[str] = []
    listing_owners: dict[str, str] = {}
    for seller in sellers:
        if not isinstance(seller, dict):
            continue
        seller_slot = seller.get("seller_slot")
        service_slot = seller.get("service_slot")
        listing_slots = seller.get("listing_slots")
        if isinstance(seller_slot, str):
            seller_slots.append(seller_slot)
        if isinstance(service_slot, str):
            service_slots.append(service_slot)
        if not isinstance(seller_slot, str) or not isinstance(listing_slots, list):
            continue
        if len(listing_slots) != 1:
            errors.append(
                "every current G1 scenario seller must declare exactly one "
                "selected listing"
            )
        for listing_slot in listing_slots:
            if not isinstance(listing_slot, str):
                continue
            if listing_slot in listing_owners:
                errors.append(
                    f"listing slot {listing_slot!r} must belong to exactly one seller"
                )
            else:
                listing_owners[listing_slot] = seller_slot

    if len(seller_slots) != len(set(seller_slots)):
        errors.append("listing topology must contain distinct seller slots")
    if len(service_slots) != len(set(service_slots)):
        errors.append("listing topology must contain distinct service slots")
    if isinstance(declared_sellers, list) and set(seller_slots) != set(declared_sellers):
        errors.append(
            "listing topology must contain exactly the declared logical seller slots"
        )
    if load_counts.get("selected_listings") != len(listing_owners):
        errors.append(
            "load_counts.selected_listings must equal the number of distinct "
            "selected listing slots"
        )
    return listing_owners


def _validate_requests(
    scenario: dict[str, Any],
    listing_owners: dict[str, str],
    *,
    errors: list[str],
) -> None:
    requests = scenario.get("requests")
    actor_slots = scenario.get("actor_slots")
    load_counts = scenario.get("load_counts")
    if (
        not isinstance(requests, list)
        or not isinstance(actor_slots, dict)
        or not isinstance(load_counts, dict)
    ):
        return

    if load_counts.get("requests") != len(requests):
        errors.append("load_counts.requests must equal the number of requests")
    request_ids: list[str] = []
    buyer_slots: list[str] = []
    selected_listing_slots: list[str] = []
    selected_seller_slots: list[str] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        request_id = request.get("request_id")
        buyer_slot = request.get("buyer_slot")
        seller_slot = request.get("seller_slot")
        listing_slot = request.get("listing_slot")
        if isinstance(request_id, str):
            request_ids.append(request_id)
        if isinstance(buyer_slot, str):
            buyer_slots.append(buyer_slot)
        if isinstance(listing_slot, str):
            selected_listing_slots.append(listing_slot)
        if isinstance(seller_slot, str):
            selected_seller_slots.append(seller_slot)
        if (
            isinstance(listing_slot, str)
            and isinstance(seller_slot, str)
            and listing_owners.get(listing_slot) != seller_slot
        ):
            errors.append(
                f"request {request_id!r} must target the declared seller/listing pair"
            )
    if len(request_ids) != len(set(request_ids)):
        errors.append("requests must have distinct logical request IDs")
    if len(buyer_slots) != len(set(buyer_slots)):
        errors.append("each logical buyer may emit exactly one request")
    declared_buyers = actor_slots.get("buyers")
    if isinstance(declared_buyers, list) and set(buyer_slots) != set(declared_buyers):
        errors.append("requests must contain exactly one request for every declared buyer")
    if set(selected_listing_slots) != set(listing_owners):
        errors.append("requests must select every declared logical listing")
    if set(selected_seller_slots) != set(listing_owners.values()):
        errors.append("requests must select every declared logical seller")


def _validate_expected_outcomes(
    scenario: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    outcomes = scenario.get("expected_outcomes")
    load_counts = scenario.get("load_counts")
    physical_capacity = scenario.get("physical_capacity")
    if (
        not isinstance(outcomes, dict)
        or not isinstance(load_counts, dict)
        or not isinstance(physical_capacity, dict)
    ):
        return

    requests = load_counts.get("requests")
    successes = outcomes.get("vm-succeeded")
    refusals = outcomes.get("capacity-refused")
    faults = outcomes.get("fault")
    independently_assignable_gpus = physical_capacity.get(
        "independently_assignable_gpus"
    )
    gpus_per_successful_vm = physical_capacity.get("gpus_per_successful_vm")
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (
            requests,
            successes,
            refusals,
            faults,
            independently_assignable_gpus,
            gpus_per_successful_vm,
        )
    ):
        return
    if requests != successes + refusals + faults:
        errors.append(
            "load_counts.requests must equal all expected terminal outcome cardinalities"
        )
    if gpus_per_successful_vm < 1:
        return
    success_limit = independently_assignable_gpus // gpus_per_successful_vm
    if successes > success_limit:
        errors.append(
            "expected simultaneous VM successes cannot exceed independently "
            "assignable whole-GPU capacity"
        )
    if requests and successes != min(requests, success_limit):
        errors.append(
            "current frozen G1 scenarios must expect the maximal one-GPU success "
            "cardinality"
        )
    if refusals != requests - successes:
        errors.append(
            "all expected non-success outcomes in a current scenario must be "
            "capacity-refused"
        )
    if faults != 0:
        errors.append("a frozen scenario cannot expect a fault outcome")


def _validate_named_g1_shape(
    scenario: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str):
        return
    if scenario_id not in FROZEN_G1_SCENARIO_IDS:
        errors.append("scenario_id is not part of the frozen fourteen-shape G1 envelope")
        return
    if scenario_id in {"serialized-reuse-a", "serialized-reuse-b"}:
        buyers, sellers = 1, 1
    else:
        match = re.fullmatch(r"b([1-8])-s([1-4])-g1", scenario_id)
        if match is None:
            return
        buyers, sellers = (int(value) for value in match.groups())
    expected_actor_counts = {
        "observers": 1,
        "buyers": buyers,
        "sellers": sellers,
        "host_operators": 1,
    }
    expected_load_counts = {
        "selected_listings": sellers,
        "requests": buyers,
    }
    expected_outcomes = {
        "vm-succeeded": 1,
        "capacity-refused": buyers - 1,
        "fault": 0,
    }
    for field, expected in (
        ("actor_counts", expected_actor_counts),
        ("load_counts", expected_load_counts),
        ("expected_outcomes", expected_outcomes),
    ):
        if scenario.get(field) != expected:
            errors.append(
                f"{field} must encode the exact O/B/S/H/L/R/G1 shape named by "
                "scenario_id"
            )


def validate_scenario_in_memory(
    scenario: dict[str, Any],
    repo_root: Path,
    *,
    schema: dict[str, Any] | None = None,
) -> None:
    """Validate v2 scenario structure and mode-neutral portable semantics."""
    errors = (
        _schema_errors(scenario, _schema_path(repo_root, "capacity-scenario.schema.json"))
        if schema is None
        else _validation_errors(scenario, schema)
    )
    if not errors:
        if scenario.get("schema_version") != 2:
            errors.append("current scenario authority requires schema_version 2")
        if scenario.get("deal_type") != "vm":
            errors.append("current capacity scenarios are VM-only")
        if scenario.get("provisioning") != "real-kvm-ansible":
            errors.append("current capacity scenarios require real KVM/Ansible")
        if scenario.get("gpu_assignment") != "whole-device-passthrough":
            errors.append("current capacity scenarios require whole-device GPU passthrough")
        if scenario.get("retry_budget") != 0:
            errors.append("current request-bearing scenarios require retry_budget zero")
        physical_capacity = scenario.get("physical_capacity")
        if isinstance(physical_capacity, dict):
            if physical_capacity.get("gpus_per_successful_vm") != 1:
                errors.append("current scenarios require one GPU per successful VM")
            if physical_capacity.get("independently_assignable_gpus") != 1:
                errors.append(
                    "current scenario authority is restricted to one independently "
                    "assignable GPU"
                )
        if _contains_unresolved_placeholder(scenario):
            errors.append("a frozen scenario cannot contain an unresolved placeholder")
        slots = scenario.get("actor_slots")
        counts = scenario.get("actor_counts")
        _validate_exact_slots(slots, counts, errors=errors)
        listing_owners = _validate_seller_topology(scenario, errors=errors)
        _validate_requests(scenario, listing_owners, errors=errors)
        _validate_expected_outcomes(scenario, errors=errors)
        _validate_named_g1_shape(scenario, errors=errors)
    if errors:
        raise CapacityValidationError("scenario validation failed:\n- " + "\n- ".join(errors))


def validate_scenario(scenario: dict[str, Any], repo_root: Path) -> None:
    """Backward-compatible name for non-authoritative in-memory validation."""
    validate_scenario_in_memory(scenario, repo_root)


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise CapacityValidationError(f"cannot execute Git: {error}") from error
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CapacityValidationError(
            f"Git {' '.join(arguments)} failed"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _validate_repo_root(repo_root: Path) -> Path:
    candidate = repo_root.expanduser()
    try:
        candidate_stat = candidate.stat()
    except OSError as error:
        raise CapacityValidationError(f"SCM repository root is unavailable: {error}") from error
    if not stat.S_ISDIR(candidate_stat.st_mode):
        raise CapacityValidationError("SCM repository root must be a directory")
    top_level = Path(
        _run_git(candidate, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    )
    try:
        same_root = os.path.samefile(candidate, top_level)
    except OSError as error:
        raise CapacityValidationError(f"cannot verify SCM repository root: {error}") from error
    if not same_root:
        raise CapacityValidationError(
            "repository root must be the exact SCM Git worktree root"
        )
    if not (candidate / "tools" / "issue-discovery").is_dir():
        raise CapacityValidationError(
            "repository root does not contain the SCM issue-discovery package"
        )
    return top_level


def _validate_relative_scenario_path(relative_path: str | Path) -> PurePosixPath:
    raw = os.fspath(relative_path)
    if not raw or "\0" in raw or "\\" in raw:
        raise CapacityValidationError(
            "scenario path must use a non-empty repository-relative POSIX path"
        )
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or path.as_posix() != raw
    ):
        raise CapacityValidationError(
            "scenario path must be normalized, relative, and cannot traverse "
            "parent directories"
        )
    try:
        path.relative_to(CAPACITY_SCENARIO_ROOT)
    except ValueError as error:
        raise CapacityValidationError(
            f"scenario path must be under {CAPACITY_SCENARIO_ROOT}"
        ) from error
    if path.parent != CAPACITY_SCENARIO_ROOT or path.suffix != ".json":
        raise CapacityValidationError(
            "scenario path must name one JSON file directly under the capacity "
            "scenario root"
        )
    return path


def _validate_relative_profile_path(relative_path: str | Path) -> PurePosixPath:
    raw = os.fspath(relative_path)
    if not raw or "\0" in raw or "\\" in raw:
        raise CapacityValidationError(
            "profile path must use a non-empty repository-relative POSIX path"
        )
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw or ".." in path.parts:
        raise CapacityValidationError(
            "profile path must be normalized, relative, and cannot traverse "
            "parent directories"
        )
    if path != CAPACITY_PROFILE_PATH:
        raise CapacityValidationError(
            f"current profile authority must use {CAPACITY_PROFILE_PATH}"
        )
    return path


def _validate_worktree_file(repo_root: Path, relative_path: PurePosixPath) -> Path:
    current = repo_root
    for part in relative_path.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise CapacityValidationError(
                f"scenario worktree path is unavailable: {relative_path}"
            ) from error
        if stat.S_ISLNK(mode):
            raise CapacityValidationError(
                f"scenario path cannot contain a symlink: {relative_path}"
            )
    if not stat.S_ISREG(mode):
        raise CapacityValidationError(
            f"scenario path must be a regular file: {relative_path}"
        )
    return current


def _pinned_regular_blob(
    repo_root: Path,
    scm_ref: str,
    relative_path: PurePosixPath,
) -> tuple[str, bytes]:
    entry = _run_git(
        repo_root,
        "ls-tree",
        "-z",
        scm_ref,
        "--",
        relative_path.as_posix(),
    )
    records = [record for record in entry.split(b"\0") if record]
    if len(records) != 1:
        raise CapacityValidationError(
            "authority path must resolve to exactly one tracked Git entry at the SCM ref"
        )
    try:
        metadata, recorded_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        decoded_path = recorded_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise CapacityValidationError("Git returned an invalid authority tree entry") from error
    if decoded_path != relative_path.as_posix():
        raise CapacityValidationError("Git authority entry did not match the selected path")
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise CapacityValidationError(
            "authority file must be tracked as a regular Git file, not a symlink "
            "or submodule"
        )
    blob = _run_git(repo_root, "cat-file", "blob", object_id)
    return object_id, blob


def _checked_pinned_worktree_blob(
    repo_root: Path,
    scm_ref: str,
    relative_path: PurePosixPath,
) -> bytes:
    worktree_path = _validate_worktree_file(repo_root, relative_path)
    tracked = _run_git(
        repo_root,
        "ls-files",
        "--",
        relative_path.as_posix(),
    )
    tracked_paths = tracked.decode("utf-8", errors="strict").splitlines()
    if tracked_paths != [relative_path.as_posix()]:
        raise CapacityValidationError(
            f"authority path must be tracked in the SCM worktree: {relative_path}"
        )
    _blob_id, blob = _pinned_regular_blob(repo_root, scm_ref, relative_path)
    try:
        worktree_bytes = worktree_path.read_bytes()
    except OSError as error:
        raise CapacityValidationError(
            f"cannot read authority worktree bytes at {relative_path}: {error}"
        ) from error
    if worktree_bytes != blob:
        raise CapacityValidationError(
            f"worktree bytes differ from the blob at the pinned SCM ref: {relative_path}"
        )
    return blob


def resolve_pinned_scenario(
    repo_root: Path,
    scm_ref: str,
    relative_path: str | Path,
    expected_sha256: str | None = None,
) -> PinnedScenario:
    """Resolve current scenario authority from exact Git and worktree bytes."""
    root = _validate_repo_root(repo_root)
    if not _COMMIT_RE.fullmatch(scm_ref):
        raise CapacityValidationError("SCM ref must be an exact lowercase 40-character commit")
    object_type = _run_git(root, "cat-file", "-t", scm_ref).decode("ascii").strip()
    if object_type != "commit":
        raise CapacityValidationError("SCM ref must identify a Git commit")
    path = _validate_relative_scenario_path(relative_path)
    blob = _checked_pinned_worktree_blob(root, scm_ref, path)
    schema_blob = _checked_pinned_worktree_blob(
        root,
        scm_ref,
        CAPACITY_SCENARIO_SCHEMA,
    )
    scenario = _strict_json_object(blob, source=f"{scm_ref}:{path.as_posix()}")
    schema = _strict_json_object(
        schema_blob,
        source=f"{scm_ref}:{CAPACITY_SCENARIO_SCHEMA.as_posix()}",
    )
    if path.stem != scenario.get("scenario_id"):
        raise CapacityValidationError(
            "scenario filename stem must equal its canonical scenario_id"
        )
    validate_scenario_in_memory(scenario, root, schema=schema)
    digest = scenario_sha256(scenario)
    if expected_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise CapacityValidationError(
                "declared scenario SHA-256 must be 64 lowercase hexadecimal characters"
            )
        if digest != expected_sha256:
            raise CapacityValidationError(
                "declared scenario SHA-256 does not match canonical scenario bytes"
            )
    return PinnedScenario(
        scenario_id=scenario["scenario_id"],
        scm_ref=scm_ref,
        relative_path=path.as_posix(),
        scenario_sha256=digest,
        _canonical_bytes=canonical_json_bytes(scenario),
    )


def _expected_stage_contracts() -> dict[str, tuple[str | None, str, str, str, bool]]:
    contracts: dict[str, tuple[str | None, str, str, str, bool]] = {
        "observer-probe": (
            None,
            "observer-probe",
            "readiness",
            "none",
            False,
        ),
        "b1-s1-g1-reference": (
            "b1-s1-g1",
            "reference",
            "real-reference",
            "controller-driven",
            False,
        ),
    }
    for stage_id in QUALIFICATION_STAGE_ORDER[2:]:
        scenario_id = stage_id.removesuffix("-qualification")
        contracts[stage_id] = (
            scenario_id,
            "qualification",
            "real-qualification",
            "agent-triggered",
            False,
        )
    measured_stage_ids = (
        *MEASURED_INITIAL_BUYER_ORDER,
        *MEASURED_BUYER_REFINEMENT_STAGES,
        *MEASURED_REUSE_ORDER,
        *MEASURED_SELLER_STAGES,
    )
    optional_stages = {
        *MEASURED_BUYER_REFINEMENT_STAGES,
        "b4-s3-g1-measured",
    }
    for stage_id in measured_stage_ids:
        scenario_id = stage_id.removeprefix("q0-").removesuffix("-measured")
        contracts[stage_id] = (
            scenario_id,
            "measured",
            "real-measured",
            "agent-triggered",
            stage_id in optional_stages,
        )
    return contracts


def _load_registered_scenario(
    binding: dict[str, Any],
    repo_root: Path,
    scm_ref: str | None,
) -> dict[str, Any]:
    scenario_path = binding.get("scenario_path")
    expected_sha256 = binding.get("scenario_sha256")
    if not isinstance(scenario_path, str) or not isinstance(expected_sha256, str):
        raise CapacityValidationError("profile scenario binding is incomplete")
    if scm_ref is not None:
        return resolve_pinned_scenario(
            repo_root,
            scm_ref,
            scenario_path,
            expected_sha256,
        ).scenario
    relative_path = _validate_relative_scenario_path(scenario_path)
    scenario = validate_scenario_file(repo_root / relative_path, repo_root)
    if scenario_sha256(scenario) != expected_sha256:
        raise CapacityValidationError(
            "profile scenario binding does not match the canonical scenario SHA-256"
        )
    return scenario


def _validate_stage_scenario_binding(
    stage: dict[str, Any],
    expected_scenario_id: str | None,
    repo_root: Path,
    scm_ref: str | None,
    *,
    errors: list[str],
) -> None:
    binding = stage.get("scenario_binding")
    if expected_scenario_id is None:
        if binding is not None:
            errors.append("observer-probe must have a null scenario binding")
        expected_probe_values = (
            ("actor_counts", {
                "observers": 1,
                "buyers": 0,
                "sellers": 0,
                "host_operators": 1,
            }),
            ("load_counts", {"selected_listings": 0, "requests": 0}),
            ("independently_assignable_gpus", 1),
            ("expected_outcomes", None),
            ("retry_budget", 0),
        )
        for field, expected in expected_probe_values:
            if stage.get(field) != expected:
                errors.append(f"observer-probe {field} must equal {expected!r}")
        return
    if not isinstance(binding, dict):
        errors.append(f"stage {stage.get('stage_id')!r} requires a scenario binding")
        return
    if binding.get("scenario_id") != expected_scenario_id:
        errors.append(
            f"stage {stage.get('stage_id')!r} must bind scenario "
            f"{expected_scenario_id!r}"
        )
        return
    try:
        scenario = _load_registered_scenario(binding, repo_root, scm_ref)
    except CapacityValidationError as error:
        errors.append(str(error))
        return
    if scenario.get("scenario_id") != expected_scenario_id:
        errors.append("profile binding scenario_id differs from the scenario content")
    for field in ("actor_counts", "load_counts", "expected_outcomes"):
        if stage.get(field) != scenario.get(field):
            errors.append(
                f"stage {stage.get('stage_id')!r} {field} must equal its scenario"
            )
    if stage.get("independently_assignable_gpus") != scenario.get(
        "physical_capacity", {}
    ).get("independently_assignable_gpus"):
        errors.append(
            f"stage {stage.get('stage_id')!r} physical capacity must equal its scenario"
        )
    if stage.get("retry_budget") != scenario.get("retry_budget"):
        errors.append(
            f"stage {stage.get('stage_id')!r} retry budget must equal its scenario"
        )


def _validate_registry_progression(
    registry: dict[str, Any],
    *,
    errors: list[str],
) -> None:
    if tuple(registry.get("qualification_order", ())) != QUALIFICATION_STAGE_ORDER:
        errors.append("qualification_order must contain the exact seven-stage G1 order")
    progression = registry.get("measured_progression")
    if not isinstance(progression, dict):
        return
    if tuple(progression.get("initial_buyer_order", ())) != MEASURED_INITIAL_BUYER_ORDER:
        errors.append("measured initial buyer order must be exact B1/B2/B4/B8")
    refinement = progression.get("buyer_refinement")
    if isinstance(refinement, dict):
        expected_refinement = {
            "algorithm": "deterministic-integer-bisection",
            "candidate_stage_ids": list(MEASURED_BUYER_REFINEMENT_STAGES),
            "timing": "immediately-before-reuse",
            "retain": "below-at-above",
        }
        if refinement != expected_refinement:
            errors.append(
                "buyer refinement must use the exact frozen deterministic-bisection contract"
            )
    if tuple(progression.get("reuse_order", ())) != MEASURED_REUSE_ORDER:
        errors.append("measured reuse order must contain exact A then B stages")
    seller = progression.get("seller_progression")
    expected_seller = {
        "requires_buyer_frontier_receipt": True,
        "initial_stage_id": "b2-s2-g1-measured",
        "b4_entry_stage_id": "b4-s2-g1-measured",
        "conditional_s4_stage_id": "b4-s4-g1-measured",
        "refinement_s3_stage_id": "b4-s3-g1-measured",
        "stop_after_s2_failure": True,
        "s3_after_s4_failure_only": True,
        "s3_fallback_when_s4_inadmissible": True,
    }
    if isinstance(seller, dict) and seller != expected_seller:
        errors.append("seller progression must equal the exact frozen G1 contract")


def _validate_stage_admission(stage: dict[str, Any], *, errors: list[str]) -> None:
    stage_id = stage.get("stage_id")
    admission = stage.get("admission")
    if not isinstance(stage_id, str) or not isinstance(admission, dict):
        return
    all_of = admission.get("all_of")
    any_of = admission.get("any_of")
    if not isinstance(all_of, list) or not isinstance(any_of, list):
        return
    expected_all_of: set[str]
    expected_any_of: set[frozenset[str]] = set()
    if stage_id == "observer-probe":
        expected_all_of = {"private-observer-readiness"}
    elif stage_id == "b1-s1-g1-reference":
        expected_all_of = {
            "observer-probe-complete",
            "deterministic-reference-authority",
            "verified-g1-topology",
        }
    elif stage_id == "b1-s1-g1-qualification":
        expected_all_of = {"reference-complete", "verified-g1-topology"}
    elif stage_id in {
        "b2-s1-g1-qualification",
        "serialized-reuse-a-qualification",
    }:
        expected_all_of = {"previous-stage-clean", "verified-g1-topology"}
    elif stage_id == "serialized-reuse-b-qualification":
        expected_all_of = {
            "previous-stage-clean",
            "serialized-reuse-a-baseline-equivalent",
            "verified-g1-topology",
        }
    elif stage_id == "b2-s2-g1-qualification":
        expected_all_of = {
            "previous-stage-clean",
            "verified-g1-topology",
            "distinct-seller-services-2",
        }
    elif stage_id == "q0-b1-s1-g1-measured":
        expected_all_of = {
            "qualification-complete",
            "pre-q0-contract-frozen",
            "verified-g1-topology",
        }
    elif stage_id in MEASURED_INITIAL_BUYER_ORDER[1:]:
        expected_all_of = {
            "q0-complete",
            "previous-stage-clean",
            "verified-g1-topology",
        }
    elif stage_id in MEASURED_BUYER_REFINEMENT_STAGES:
        expected_all_of = {
            "initial-buyer-progression-complete",
            "deterministic-bisection-selected",
            "previous-stage-clean",
            "verified-g1-topology",
        }
    elif stage_id == "serialized-reuse-a-measured":
        expected_all_of = {
            "buyer-refinement-complete",
            "previous-stage-clean",
            "verified-g1-topology",
        }
    elif stage_id == "serialized-reuse-b-measured":
        expected_all_of = {
            "previous-stage-clean",
            "serialized-reuse-a-baseline-equivalent",
            "verified-g1-topology",
        }
    elif stage_id == "b2-s2-g1-measured":
        expected_all_of = {
            "serialized-reuse-b-baseline-equivalent",
            "buyer-frontier-receipt",
            "distinct-seller-services-2",
            "verified-g1-topology",
        }
    elif stage_id == "b4-s2-g1-measured":
        expected_all_of = {
            "b2-s2-stage-complete",
            "buyer-frontier-receipt",
            "buyer-b4-correctness-frontier",
            "buyer-b4-load-generator-frontier",
            "distinct-seller-services-2",
            "previous-stage-clean",
            "verified-g1-topology",
        }
    elif stage_id == "b4-s4-g1-measured":
        expected_all_of = {
            "b4-s2-stage-passed",
            "buyer-frontier-receipt",
            "buyer-b4-correctness-frontier",
            "buyer-b4-load-generator-frontier",
            "distinct-seller-services-4",
            "previous-stage-clean",
            "verified-g1-topology",
        }
    elif stage_id == "b4-s3-g1-measured":
        expected_all_of = {
            "b4-s2-stage-passed",
            "buyer-frontier-receipt",
            "buyer-b4-correctness-frontier",
            "buyer-b4-load-generator-frontier",
            "previous-stage-clean",
            "verified-g1-topology",
        }
        expected_any_of = {
            frozenset({"b4-s4-stage-failed"}),
            frozenset(
                {
                    "four-seller-admission-unavailable",
                    "distinct-seller-services-3",
                }
            ),
        }
    else:
        return
    actual_all_of = set(all_of)
    actual_any_of = {
        frozenset(option)
        for option in any_of
        if isinstance(option, list)
    }
    if actual_all_of != expected_all_of:
        errors.append(
            f"stage {stage_id!r} admission all_of must equal the exact stage contract"
        )
    if actual_any_of != expected_any_of:
        errors.append(
            f"stage {stage_id!r} admission any_of must equal the exact stage contract"
        )


def validate_profile_registry(
    registry: dict[str, Any],
    repo_root: Path,
    *,
    scm_ref: str | None = None,
    _schema: dict[str, Any] | None = None,
    _raw_bytes: bytes | None = None,
    _relative_path: str | None = None,
) -> ValidatedProfileRegistry:
    """Validate the exact frozen G1 profile registry and all scenario bindings."""
    if scm_ref is not None and (
        _schema is None or _raw_bytes is None or _relative_path is None
    ):
        raise CapacityValidationError(
            "Git-pinned profile authority must use resolve_pinned_profile_registry"
        )
    errors = (
        _schema_errors(
            registry,
            _schema_path(repo_root, CAPACITY_PROFILE_REGISTRY_SCHEMA),
        )
        if _schema is None
        else _validation_errors(registry, _schema)
    )
    if not errors:
        if registry.get("schema_version") != 2 or registry.get("profile_id") != "g1-v2":
            errors.append("current capacity profile must be schema v2 with id g1-v2")
        if registry.get("scenario_root") != CAPACITY_SCENARIO_ROOT.as_posix():
            errors.append("profile scenario_root must name the public scenario directory")
        if registry.get("independently_assignable_gpus") != 1:
            errors.append("current profile authority is restricted to G1")
        if registry.get("freeze_point") != "before-q0":
            errors.append("profile registry must freeze before Q0")
        if registry.get("non_counted_actors") != ["deterministic-controller"]:
            errors.append("only the deterministic controller is non-counted orchestration")
        if tuple(registry.get("frozen_scenario_ids", ())) != FROZEN_G1_SCENARIO_IDS:
            errors.append("profile must freeze the exact ordered fourteen-scenario envelope")
        contracts = _expected_stage_contracts()
        stages = registry.get("stages")
        if isinstance(stages, list):
            stage_ids = [
                stage.get("stage_id")
                for stage in stages
                if isinstance(stage, dict)
            ]
            if len(stage_ids) != len(set(stage_ids)):
                errors.append("profile stage IDs must be unique")
            if set(stage_ids) != set(contracts):
                errors.append("profile must contain exactly the twenty-one frozen G1 stages")
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                stage_id = stage.get("stage_id")
                if not isinstance(stage_id, str) or stage_id not in contracts:
                    continue
                (
                    expected_scenario_id,
                    stage_class,
                    execution_boundary,
                    actor_trigger,
                    optional,
                ) = contracts[stage_id]
                for field, expected in (
                    ("stage_class", stage_class),
                    ("execution_boundary", execution_boundary),
                    ("actor_trigger", actor_trigger),
                    ("optional", optional),
                ):
                    if stage.get(field) != expected:
                        errors.append(
                            f"stage {stage_id!r} {field} must equal {expected!r}"
                        )
                _validate_stage_scenario_binding(
                    stage,
                    expected_scenario_id,
                    repo_root,
                    scm_ref,
                    errors=errors,
                )
                _validate_stage_admission(stage, errors=errors)
        _validate_registry_progression(registry, errors=errors)
    if errors:
        raise CapacityValidationError(
            "profile registry validation failed:\n- " + "\n- ".join(errors)
        )
    canonical = canonical_json_bytes(registry)
    raw = _raw_bytes if _raw_bytes is not None else canonical
    return ValidatedProfileRegistry(
        profile_id="g1-v2",
        scm_ref=scm_ref,
        relative_path=_relative_path,
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        repo_root=repo_root.resolve(),
        _canonical_bytes=canonical,
        _validation_token=_PROFILE_VALIDATION_TOKEN,
    )


def validate_profile_registry_file(
    path: Path,
    repo_root: Path,
    *,
    scm_ref: str | None = None,
) -> ValidatedProfileRegistry:
    if scm_ref is not None:
        raise CapacityValidationError(
            "Git-pinned profile authority must use resolve_pinned_profile_registry"
        )
    try:
        relative_path = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise CapacityValidationError(
            "profile registry must be inside the SCM repository"
        ) from error
    _validate_relative_profile_path(relative_path)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CapacityValidationError(f"cannot read profile registry {path}: {error}") from error
    registry = _strict_json_object(content, source=str(path))
    return validate_profile_registry(
        registry,
        repo_root,
        scm_ref=scm_ref,
        _raw_bytes=content,
        _relative_path=relative_path,
    )


def resolve_pinned_profile_registry(
    repo_root: Path,
    scm_ref: str,
    relative_path: str | Path = CAPACITY_PROFILE_PATH.as_posix(),
    expected_sha256: str | None = None,
) -> ValidatedProfileRegistry:
    """Resolve the exact G1 registry and schema through pinned Git authority."""
    root = _validate_repo_root(repo_root)
    if not _COMMIT_RE.fullmatch(scm_ref):
        raise CapacityValidationError("SCM ref must be an exact lowercase 40-character commit")
    object_type = _run_git(root, "cat-file", "-t", scm_ref).decode("ascii").strip()
    if object_type != "commit":
        raise CapacityValidationError("SCM ref must identify a Git commit")
    path = _validate_relative_profile_path(relative_path)
    registry_blob = _checked_pinned_worktree_blob(root, scm_ref, path)
    schema_blob = _checked_pinned_worktree_blob(
        root,
        scm_ref,
        CAPACITY_PROFILE_SCHEMA,
    )
    registry = _strict_json_object(
        registry_blob,
        source=f"{scm_ref}:{path.as_posix()}",
    )
    schema = _strict_json_object(
        schema_blob,
        source=f"{scm_ref}:{CAPACITY_PROFILE_SCHEMA.as_posix()}",
    )
    authority = validate_profile_registry(
        registry,
        root,
        scm_ref=scm_ref,
        _schema=schema,
        _raw_bytes=registry_blob,
        _relative_path=path.as_posix(),
    )
    if expected_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise CapacityValidationError(
                "declared profile SHA-256 must be 64 lowercase hexadecimal characters"
            )
        if authority.canonical_sha256 != expected_sha256:
            raise CapacityValidationError(
                "declared profile SHA-256 does not match the canonical registry"
            )
    return authority


def profile_stage_sha256(stage: dict[str, Any]) -> str:
    """Return the canonical SHA-256 of one closed profile-stage record."""
    return canonical_sha256(stage)


def resolve_pinned_profile_stage(
    repo_root: Path,
    scm_ref: str,
    stage_id: str,
    *,
    expected_sha256: str | None = None,
) -> ValidatedProfileStage:
    """Resolve one real-registry or standalone mock stage from exact Git bytes."""
    root = _validate_repo_root(repo_root)
    if not _COMMIT_RE.fullmatch(scm_ref):
        raise CapacityValidationError(
            "SCM ref must be an exact lowercase 40-character commit"
        )
    object_type = _run_git(root, "cat-file", "-t", scm_ref).decode("ascii").strip()
    if object_type != "commit":
        raise CapacityValidationError("SCM ref must identify a Git commit")
    if not isinstance(stage_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]*",
        stage_id,
    ):
        raise CapacityValidationError("profile-stage ID is invalid")

    registry_sha256: str | None
    scenario: PinnedScenario | None
    if stage_id == "b1-s1-g1-mock":
        stage_blob = _checked_pinned_worktree_blob(
            root,
            scm_ref,
            CAPACITY_MOCK_STAGE_PATH,
        )
        schema_blob = _checked_pinned_worktree_blob(
            root,
            scm_ref,
            CAPACITY_PROFILE_STAGE_SCHEMA,
        )
        stage = _strict_json_object(
            stage_blob,
            source=f"{scm_ref}:{CAPACITY_MOCK_STAGE_PATH.as_posix()}",
        )
        schema = _strict_json_object(
            schema_blob,
            source=f"{scm_ref}:{CAPACITY_PROFILE_STAGE_SCHEMA.as_posix()}",
        )
        errors = _validation_errors(stage, schema)
        if stage.get("stage_id") != stage_id:
            errors.append("standalone profile-stage identity does not match its path")
        binding = stage.get("scenario_binding")
        if not isinstance(binding, dict):
            errors.append("standalone mock stage must bind one scenario")
            scenario = None
        else:
            try:
                scenario = resolve_pinned_scenario(
                    root,
                    scm_ref,
                    binding.get("scenario_path"),
                    expected_sha256=binding.get("scenario_sha256"),
                )
            except CapacityValidationError as error:
                errors.append(str(error))
                scenario = None
            else:
                scenario_value = scenario.scenario
                if binding.get("scenario_id") != scenario.scenario_id:
                    errors.append(
                        "standalone mock stage scenario identity does not match"
                    )
                for key in ("actor_counts", "load_counts"):
                    if stage.get(key) != scenario_value.get(key):
                        errors.append(
                            f"standalone mock stage {key} does not match its scenario"
                        )
                physical = scenario_value.get("physical_capacity")
                if (
                    not isinstance(physical, dict)
                    or stage.get("independently_assignable_gpus")
                    != physical.get("independently_assignable_gpus")
                ):
                    errors.append(
                        "standalone mock stage GPU authority does not match its scenario"
                    )
                if stage.get("retry_budget") != scenario_value.get("retry_budget"):
                    errors.append(
                        "standalone mock stage retry authority does not match its scenario"
                    )
        if errors:
            raise CapacityValidationError(
                "profile-stage validation failed:\n- " + "\n- ".join(errors)
            )
        relative_path = CAPACITY_MOCK_STAGE_PATH.as_posix()
        registry_sha256 = None
    else:
        registry = resolve_pinned_profile_registry(root, scm_ref)
        matches = [
            item
            for item in registry.registry["stages"]
            if item.get("stage_id") == stage_id
        ]
        if len(matches) != 1:
            raise CapacityValidationError(
                "profile-stage must resolve exactly once in the pinned G1 registry"
            )
        stage = matches[0]
        binding = stage.get("scenario_binding")
        if binding is None:
            scenario = None
        elif isinstance(binding, dict):
            scenario = resolve_pinned_scenario(
                root,
                scm_ref,
                binding["scenario_path"],
                expected_sha256=binding["scenario_sha256"],
            )
        else:
            raise CapacityValidationError(
                "pinned profile-stage has invalid scenario authority"
            )
        relative_path = CAPACITY_PROFILE_PATH.as_posix()
        registry_sha256 = registry.canonical_sha256

    digest = profile_stage_sha256(stage)
    if expected_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise CapacityValidationError(
                "declared profile-stage SHA-256 must be 64 lowercase "
                "hexadecimal characters"
            )
        if digest != expected_sha256:
            raise CapacityValidationError(
                "declared profile-stage SHA-256 does not match pinned authority"
            )
    return ValidatedProfileStage(
        stage_id=stage_id,
        scm_ref=scm_ref,
        relative_path=relative_path,
        canonical_sha256=digest,
        registry_sha256=registry_sha256,
        repo_root=root,
        scenario=scenario,
        _canonical_bytes=canonical_json_bytes(stage),
        _validation_token=_PROFILE_STAGE_VALIDATION_TOKEN,
    )


def require_pinned_profile_stage(
    authority: ValidatedProfileStage,
) -> dict[str, Any]:
    """Revalidate an immutable profile-stage authority at its exact SCM ref."""
    if (
        not isinstance(authority, ValidatedProfileStage)
        or authority._validation_token is not _PROFILE_STAGE_VALIDATION_TOKEN
    ):
        raise CapacityValidationError(
            "profile-stage operations require validated Git-pinned authority"
        )
    reproduced = resolve_pinned_profile_stage(
        authority.repo_root,
        authority.scm_ref,
        authority.stage_id,
        expected_sha256=authority.canonical_sha256,
    )
    if (
        reproduced.relative_path != authority.relative_path
        or reproduced.registry_sha256 != authority.registry_sha256
        or reproduced.scenario != authority.scenario
    ):
        raise CapacityValidationError(
            "profile-stage authority changed after validation"
        )
    return authority.stage


def _require_validated_profile(
    authority: ValidatedProfileRegistry,
) -> dict[str, Any]:
    if (
        not isinstance(authority, ValidatedProfileRegistry)
        or authority._validation_token is not _PROFILE_VALIDATION_TOKEN
    ):
        raise CapacityValidationError(
            "profile sequence requires a previously validated registry authority"
        )
    if authority.relative_path is not None:
        relative_path = _validate_relative_profile_path(authority.relative_path)
        if authority.scm_ref is None:
            try:
                current_bytes = (authority.repo_root / relative_path).read_bytes()
            except OSError as error:
                raise CapacityValidationError(
                    f"cannot recheck profile registry bytes: {error}"
                ) from error
        else:
            current_bytes = _checked_pinned_worktree_blob(
                authority.repo_root,
                authority.scm_ref,
                relative_path,
            )
            _checked_pinned_worktree_blob(
                authority.repo_root,
                authority.scm_ref,
                CAPACITY_PROFILE_SCHEMA,
            )
            seen_scenarios: set[tuple[str, str]] = set()
            for stage in authority.registry["stages"]:
                binding = stage["scenario_binding"]
                if binding is None:
                    continue
                scenario_authority = (
                    binding["scenario_path"],
                    binding["scenario_sha256"],
                )
                if scenario_authority in seen_scenarios:
                    continue
                seen_scenarios.add(scenario_authority)
                resolve_pinned_scenario(
                    authority.repo_root,
                    authority.scm_ref,
                    binding["scenario_path"],
                    binding["scenario_sha256"],
                )
        if hashlib.sha256(current_bytes).hexdigest() != authority.raw_sha256:
            raise CapacityValidationError(
                "profile registry raw bytes changed after validation"
            )
    return authority.registry


def _require_pinned_profile(
    authority: ValidatedProfileRegistry,
) -> dict[str, Any]:
    registry = _require_validated_profile(authority)
    if (
        authority.scm_ref is None
        or not _COMMIT_RE.fullmatch(authority.scm_ref)
        or authority.relative_path != CAPACITY_PROFILE_PATH.as_posix()
    ):
        raise CapacityValidationError(
            "campaign sequence requires a Git-pinned G1 profile authority"
        )
    return registry


def _require_stage_passes(stage_passes: dict[str, bool]) -> None:
    if not isinstance(stage_passes, dict) or any(
        not isinstance(stage_id, str) or type(passed) is not bool
        for stage_id, passed in stage_passes.items()
    ):
        raise CapacityValidationError(
            "stage_passes must map stage IDs to exact boolean results"
        )


def _require_nonnegative_int(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise CapacityValidationError(f"{name} must be a nonnegative integer")


def _require_sha256_authority(name: str, value: str | None) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CapacityValidationError(
            f"{name} must be an exact lowercase SHA-256 digest"
        )
    return value


def _buyer_count_for_stage(stage_id: str) -> int:
    match = re.match(r"^(?:q0-)?b([1-8])-s1-g1-measured$", stage_id)
    if match is None:
        raise CapacityValidationError(f"not a measured buyer stage: {stage_id}")
    return int(match.group(1))


def select_buyer_refinement_counts(
    stage_passes: dict[str, bool],
) -> tuple[int, ...]:
    """Select frozen integer probes until the observed pass/fail bracket is adjacent."""
    _require_stage_passes(stage_passes)
    observations: dict[int, bool] = {}
    for stage_id in MEASURED_INITIAL_BUYER_ORDER:
        if stage_id not in stage_passes:
            raise CapacityValidationError(
                f"buyer refinement requires a pass/fail result for {stage_id}"
            )
        observations[_buyer_count_for_stage(stage_id)] = stage_passes[stage_id]

    selected: list[int] = []
    while True:
        ordered_observations = [
            passed for _count, passed in sorted(observations.items())
        ]
        if any(
            not earlier and later
            for earlier, later in zip(
                ordered_observations,
                ordered_observations[1:],
            )
        ):
            raise CapacityValidationError(
                "buyer frontier observations must form a monotonic passing prefix"
            )
        passing = [count for count, passed in observations.items() if passed]
        failing = [count for count, passed in observations.items() if not passed]
        if not passing or not failing:
            expected_stage_id = None
        else:
            low = max(passing)
            high = min(count for count in failing if count > low)
            expected_stage_id = (
                None
                if high - low <= 1
                else f"b{(low + high) // 2}-s1-g1-measured"
            )
        if expected_stage_id is None:
            break
        if expected_stage_id not in MEASURED_BUYER_REFINEMENT_STAGES:
            raise CapacityValidationError("buyer refinement selected an unfrozen shape")
        count = _buyer_count_for_stage(expected_stage_id)
        selected.append(count)
        if expected_stage_id not in stage_passes:
            break
        observations[count] = stage_passes[expected_stage_id]
    return tuple(selected)


def retained_buyer_refinement_counts(
    stage_passes: dict[str, bool],
) -> tuple[int, ...]:
    """Return the bounded observations retained around the final buyer frontier."""
    selected = select_buyer_refinement_counts(stage_passes)
    selected_stage_ids = [
        f"b{count}-s1-g1-measured"
        for count in selected
    ]
    missing = [
        stage_id for stage_id in selected_stage_ids if stage_id not in stage_passes
    ]
    if missing:
        raise CapacityValidationError(
            f"retained buyer bracket requires a result for {missing[0]}"
        )
    observations = {
        _buyer_count_for_stage(stage_id): passed
        for stage_id, passed in stage_passes.items()
        if re.fullmatch(r"(?:q0-)?b[1-8]-s1-g1-measured", stage_id)
    }
    ordered_counts = sorted(observations)
    passing = [count for count in ordered_counts if observations[count]]
    failing = [count for count in ordered_counts if not observations[count]]
    if not passing or not failing:
        return tuple(ordered_counts[-3:] if passing else ordered_counts[:3])
    low = max(passing)
    high = min(count for count in failing if count > low)
    below = [count for count in ordered_counts if count < low]
    retained = [*below[-1:], low, high]
    return tuple(dict.fromkeys(retained))


def buyer_frontier_is_lower_bound(
    stage_passes: dict[str, bool],
    *,
    generator_ended_first: bool = False,
) -> bool:
    """Report when the frozen B8 envelope ends before a product failure."""
    _require_stage_passes(stage_passes)
    if type(generator_ended_first) is not bool:
        raise CapacityValidationError("generator_ended_first must be an exact boolean")
    b8_stage = "b8-s1-g1-measured"
    if b8_stage not in stage_passes:
        raise CapacityValidationError("buyer lower-bound authority requires the B8 result")
    return stage_passes[b8_stage] or generator_ended_first


def validate_buyer_refinement_sequence(
    refinement_stage_ids: list[str] | tuple[str, ...],
    stage_passes: dict[str, bool],
) -> None:
    """Validate adaptive buyer probes against deterministic integer bisection."""
    expected_stage_ids = tuple(
        f"b{count}-s1-g1-measured"
        for count in select_buyer_refinement_counts(stage_passes)
    )
    if tuple(refinement_stage_ids) != expected_stage_ids:
        raise CapacityValidationError(
            "buyer refinement does not follow deterministic integer bisection"
        )
    missing = [
        stage_id
        for stage_id in expected_stage_ids
        if stage_id not in stage_passes
    ]
    if missing:
        raise CapacityValidationError(
            f"buyer refinement requires a pass/fail result for {missing[0]}"
        )


def _validate_qualification_order(
    stage_ids: list[str] | tuple[str, ...],
) -> None:
    if tuple(stage_ids) != QUALIFICATION_STAGE_ORDER:
        raise CapacityValidationError(
            "qualification sequence must equal the exact seven-stage G1 order"
        )


def validate_qualification_sequence(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
) -> None:
    """Validate qualification against exact Git-pinned profile authority."""
    _require_pinned_profile(authority)
    _validate_qualification_order(stage_ids)


def validate_qualification_sequence_in_memory(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
) -> None:
    """Validate qualification order without granting campaign authority."""
    _require_validated_profile(authority)
    _validate_qualification_order(stage_ids)


def select_seller_stage_ids(
    *,
    buyer_frontier_receipt_sha256: str,
    buyer_correctness_frontier: int,
    load_generator_frontier: int,
    distinct_seller_identities: int,
    distinct_service_instances: int,
    stage_passes: dict[str, bool],
) -> tuple[str, ...]:
    """Select the bounded seller progression admitted by buyer and topology proof."""
    _require_sha256_authority(
        "buyer_frontier_receipt_sha256",
        buyer_frontier_receipt_sha256,
    )
    _require_nonnegative_int("buyer_correctness_frontier", buyer_correctness_frontier)
    _require_nonnegative_int("load_generator_frontier", load_generator_frontier)
    _require_nonnegative_int("distinct_seller_identities", distinct_seller_identities)
    _require_nonnegative_int("distinct_service_instances", distinct_service_instances)
    _require_stage_passes(stage_passes)
    available_sellers = min(distinct_seller_identities, distinct_service_instances)
    if available_sellers < 2:
        raise CapacityValidationError(
            "seller scaling requires two distinct seller identities and services"
        )
    selected = ["b2-s2-g1-measured"]
    if "b2-s2-g1-measured" not in stage_passes:
        return tuple(selected)
    if not stage_passes["b2-s2-g1-measured"]:
        return tuple(selected)
    if buyer_correctness_frontier < 4 or load_generator_frontier < 4:
        return tuple(selected)
    selected.append("b4-s2-g1-measured")
    if "b4-s2-g1-measured" not in stage_passes:
        return tuple(selected)
    if not stage_passes["b4-s2-g1-measured"]:
        return tuple(selected)
    if available_sellers >= 4:
        selected.append("b4-s4-g1-measured")
        if stage_passes.get("b4-s4-g1-measured") is False:
            selected.append("b4-s3-g1-measured")
    elif available_sellers >= 3:
        selected.append("b4-s3-g1-measured")
    return tuple(selected)


def _validate_profile_stage_sequence(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
    *,
    require_pinned_authority: bool,
    stage_passes: dict[str, bool] | None = None,
    pre_q0_registry_sha256: str | None = None,
    pre_q0_registry_raw_sha256: str | None = None,
    buyer_frontier_receipt_sha256: str | None = None,
    buyer_correctness_frontier: int = 0,
    load_generator_frontier: int = 0,
    distinct_seller_identities: int = 0,
    distinct_service_instances: int = 0,
) -> None:
    """Validate an exact qualification or dynamically selected measured sequence."""
    if require_pinned_authority:
        _require_pinned_profile(authority)
    else:
        _require_validated_profile(authority)
    _require_nonnegative_int("buyer_correctness_frontier", buyer_correctness_frontier)
    _require_nonnegative_int("load_generator_frontier", load_generator_frontier)
    _require_nonnegative_int("distinct_seller_identities", distinct_seller_identities)
    _require_nonnegative_int("distinct_service_instances", distinct_service_instances)
    if buyer_frontier_receipt_sha256 is not None:
        _require_sha256_authority(
            "buyer_frontier_receipt_sha256",
            buyer_frontier_receipt_sha256,
        )
    passes = {} if stage_passes is None else stage_passes
    _require_stage_passes(passes)
    sequence = tuple(stage_ids)
    if len(sequence) != len(set(sequence)):
        raise CapacityValidationError("profile stage sequence cannot contain duplicates")
    if sequence == QUALIFICATION_STAGE_ORDER:
        _validate_qualification_order(sequence)
        return
    if tuple(sequence[:4]) != MEASURED_INITIAL_BUYER_ORDER:
        raise CapacityValidationError(
            "measured sequence must begin with exact B1/B2/B4/B8 stages"
        )
    _require_sha256_authority(
        "pre_q0_registry_sha256",
        pre_q0_registry_sha256,
    )
    _require_sha256_authority(
        "pre_q0_registry_raw_sha256",
        pre_q0_registry_raw_sha256,
    )
    if authority.canonical_sha256 != pre_q0_registry_sha256:
        raise CapacityValidationError("profile registry changed after Q0 began")
    if authority.raw_sha256 != pre_q0_registry_raw_sha256:
        raise CapacityValidationError("profile registry raw bytes changed after Q0 began")
    try:
        reuse_index = sequence.index(MEASURED_REUSE_ORDER[0], 4)
    except ValueError as error:
        raise CapacityValidationError(
            "measured sequence is missing serialized reuse A"
        ) from error
    refinement = sequence[4:reuse_index]
    validate_buyer_refinement_sequence(refinement, passes)
    if sequence[reuse_index : reuse_index + 2] != MEASURED_REUSE_ORDER:
        raise CapacityValidationError("measured sequence must run reuse A then reuse B")
    seller_sequence = sequence[reuse_index + 2 :]
    if not seller_sequence:
        if buyer_frontier_receipt_sha256 is not None:
            raise CapacityValidationError(
                "measured sequence with a buyer-frontier receipt must begin seller scaling"
            )
        return
    receipt_sha256 = _require_sha256_authority(
        "buyer_frontier_receipt_sha256",
        buyer_frontier_receipt_sha256,
    )
    expected_sellers = select_seller_stage_ids(
        buyer_frontier_receipt_sha256=receipt_sha256,
        buyer_correctness_frontier=buyer_correctness_frontier,
        load_generator_frontier=load_generator_frontier,
        distinct_seller_identities=distinct_seller_identities,
        distinct_service_instances=distinct_service_instances,
        stage_passes=passes,
    )
    if seller_sequence != expected_sellers:
        raise CapacityValidationError(
            "seller stage sequence does not match the admitted bounded progression"
        )
    for stage_id in expected_sellers:
        if stage_id not in passes:
            raise CapacityValidationError(
                f"seller progression requires a pass/fail result for {stage_id}"
            )


def validate_profile_stage_sequence(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
    **sequence_authority: Any,
) -> None:
    """Validate a campaign sequence against Git-pinned profile authority."""
    _validate_profile_stage_sequence(
        authority,
        stage_ids,
        require_pinned_authority=True,
        **sequence_authority,
    )


def validate_measured_sequence(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
    **sequence_authority: Any,
) -> None:
    """Validate measured execution against Git-pinned profile authority."""
    _validate_profile_stage_sequence(
        authority,
        stage_ids,
        require_pinned_authority=True,
        **sequence_authority,
    )


def validate_measured_sequence_in_memory(
    authority: ValidatedProfileRegistry,
    stage_ids: list[str] | tuple[str, ...],
    **sequence_authority: Any,
) -> None:
    """Validate measured ordering without granting campaign authority."""
    _validate_profile_stage_sequence(
        authority,
        stage_ids,
        require_pinned_authority=False,
        **sequence_authority,
    )


def validate_finding(finding: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(finding, _schema_path(repo_root, "capacity-finding.schema.json"))
    if not errors:
        branch = finding["observed"]["working_branch"]
        classification = finding["classification"]
        destination = finding["destination_repo"]
        if classification in {"public-product", "public-harness"}:
            if destination != "simple-compute-market" or branch != SCM_BRANCH:
                errors.append("public findings must target the SCM working branch")
        if classification == "private-infra":
            if destination != "compute-market-internal-infra" or branch != INFRA_BRANCH:
                errors.append("private findings must target the infra working branch")
        for item in finding["evidence"]:
            path = Path(item)
            if path.is_absolute() or ".." in path.parts:
                errors.append("evidence references must be relative and cannot traverse parents")
    if errors:
        raise CapacityValidationError("finding validation failed:\n- " + "\n- ".join(errors))


def validate_scenario_file(path: Path, repo_root: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CapacityValidationError(f"cannot read scenario file {path}: {error}") from error
    scenario = _strict_json_object(content, source=str(path))
    if path.stem != scenario.get("scenario_id"):
        raise CapacityValidationError(
            "scenario filename stem must equal its canonical scenario_id"
        )
    validate_scenario_in_memory(scenario, repo_root)
    return scenario


def scenario_sha256(scenario: dict[str, Any]) -> str:
    """Return the SHA-256 of the scenario's canonical JSON representation."""
    return canonical_sha256(scenario)


def validate_finding_file(path: Path, repo_root: Path) -> dict[str, Any]:
    finding = _read_object(path)
    validate_finding(finding, repo_root)
    return finding


def ingest_finding(run_dir: Path, finding_path: Path, repo_root: Path) -> dict[str, Any]:
    finding = validate_finding_file(finding_path, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    observed = finding["observed"]
    if manifest_path.exists():
        manifest = _read_object(manifest_path)
        for key, expected in (
            ("run_id", observed["run_id"]),
            ("working_branch", observed["working_branch"]),
            ("observed_ref", observed["observed_ref"]),
        ):
            if manifest.get(key) != expected:
                raise CapacityValidationError(
                    f"capacity finding {key} does not match the existing run manifest"
                )
    else:
        manifest = {
            "schema_version": 1,
            "campaign": "capacity",
            "run_id": observed["run_id"],
            "mode": "capacity-finding-ingest",
            "status": "finding_detected",
            "repo_root": str(repo_root.resolve()),
            "working_branch": observed["working_branch"],
            "observed_ref": observed["observed_ref"],
            "started_at": None,
            "completed_at": None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    findings_path = run_dir / "capacity-findings.jsonl"
    existing = [
        json.loads(line)
        for line in findings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if findings_path.exists() else []
    matches = [item for item in existing if item.get("finding_id") == finding["finding_id"]]
    if matches:
        if matches[0] != finding:
            raise CapacityValidationError("finding_id already exists with different content")
        return finding
    with findings_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(finding, sort_keys=True) + "\n")
    append_lifecycle(
        run_dir,
        finding=finding,
        state="detected",
        detail="Validated immutable capacity finding occurrence.",
    )
    from issue_discovery.issues import IssuePacketGenerator

    IssuePacketGenerator(run_dir, repo_root=repo_root).generate()
    return finding


def append_lifecycle(
    run_dir: Path,
    *,
    finding: dict[str, Any],
    state: str,
    detail: str,
    issue_number: int | None = None,
    issue_url: str | None = None,
) -> None:
    event = {
        "schema_version": 1,
        "finding_id": finding["finding_id"],
        "fingerprint": finding["fingerprint"],
        "destination_repo": finding["destination_repo"],
        "scenario_id": finding["scenario_id"],
        "scenario_fingerprint": finding["scenario_fingerprint"],
        "run_id": finding["observed"]["run_id"],
        "stage": finding["observed"]["stage"],
        "working_branch": finding["observed"]["working_branch"],
        "observed_ref": finding["observed"]["observed_ref"],
        "state": state,
        "detail": detail,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "issue_number": issue_number,
        "issue_url": issue_url,
    }
    with (run_dir / "issue-lifecycle.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
