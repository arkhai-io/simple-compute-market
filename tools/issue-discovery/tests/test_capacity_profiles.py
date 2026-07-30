from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

import jsonschema
import pytest

from issue_discovery.capacity import (
    FROZEN_G1_SCENARIO_IDS,
    MEASURED_BUYER_REFINEMENT_STAGES,
    MEASURED_INITIAL_BUYER_ORDER,
    MEASURED_REUSE_ORDER,
    QUALIFICATION_STAGE_ORDER,
    CapacityValidationError,
    ValidatedProfileRegistry,
    buyer_frontier_is_lower_bound,
    canonical_sha256,
    resolve_pinned_profile_registry,
    retained_buyer_refinement_counts,
    scenario_sha256,
    select_buyer_refinement_counts,
    select_seller_stage_ids,
    validate_buyer_refinement_sequence,
    validate_measured_sequence,
    validate_profile_registry,
    validate_profile_registry_file,
    validate_qualification_sequence,
    validate_scenario_in_memory,
)


PROFILE_PATH = Path("tools/issue-discovery/config/capacity/profiles/g1-v2.json")
SCENARIO_ROOT = Path("tools/issue-discovery/config/capacity/scenarios")
SCHEMA_ROOT = Path("tools/issue-discovery/schemas")
AUTHORITY_SHA256 = "a" * 64


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def profile(root: Path | None = None) -> dict[str, Any]:
    selected_root = root or repo_root()
    return read_object(selected_root / PROFILE_PATH)


def profile_authority(root: Path | None = None):
    selected_root = root or repo_root()
    return validate_profile_registry_file(
        selected_root / PROFILE_PATH,
        selected_root,
    )


def scenario(scenario_id: str, root: Path | None = None) -> dict[str, Any]:
    selected_root = root or repo_root()
    return read_object(selected_root / SCENARIO_ROOT / f"{scenario_id}.json")


def stages_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["stage_id"]: item for item in registry["stages"]}


def copy_contract(tmp_path: Path) -> Path:
    copied_root = tmp_path / "simple-compute-market"
    copied_schemas = copied_root / SCHEMA_ROOT
    copied_capacity = copied_root / "tools/issue-discovery/config/capacity"
    copied_schemas.parent.mkdir(parents=True)
    shutil.copytree(repo_root() / SCHEMA_ROOT, copied_schemas)
    shutil.copytree(
        repo_root() / "tools/issue-discovery/config/capacity",
        copied_capacity,
    )
    return copied_root


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def commit_contract(root: Path) -> str:
    git(root, "init", "-q", "-b", "fixture")
    git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.name=Capacity Profile Test",
        "-c",
        "user.email=capacity-profile@example.invalid",
        "commit",
        "-q",
        "-m",
        "add capacity profile authority",
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def pinned_profile_authority(
    tmp_path_factory: pytest.TempPathFactory,
) -> ValidatedProfileRegistry:
    copied_root = copy_contract(tmp_path_factory.mktemp("pinned-profile"))
    scm_ref = commit_contract(copied_root)
    return resolve_pinned_profile_registry(copied_root, scm_ref)


def mutate_scenario(
    scenario_id: str,
    mutation: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    value = scenario(scenario_id)
    mutation(value)
    return value


def initial_buyer_passes(
    b1: bool,
    b2: bool,
    b4: bool,
    b8: bool,
    **refinements: bool,
) -> dict[str, bool]:
    result = dict(
        zip(
            MEASURED_INITIAL_BUYER_ORDER,
            (b1, b2, b4, b8),
            strict=True,
        )
    )
    result.update(refinements)
    return result


def measured_prefix() -> tuple[str, ...]:
    return (*MEASURED_INITIAL_BUYER_ORDER, *MEASURED_REUSE_ORDER)


def test_exact_registry_and_all_stage_schemas_validate() -> None:
    registry = profile()
    validate_profile_registry(registry, repo_root())

    registry_schema = read_object(
        repo_root() / SCHEMA_ROOT / "capacity-profile-registry.schema.json"
    )
    stage_schema = read_object(
        repo_root() / SCHEMA_ROOT / "capacity-profile-stage.schema.json"
    )
    jsonschema.Draft202012Validator(registry_schema).validate(registry)
    stage_validator = jsonschema.Draft202012Validator(stage_schema)

    assert len(registry["stages"]) == 21
    assert len(stages_by_id(registry)) == 21
    assert tuple(registry["frozen_scenario_ids"]) == FROZEN_G1_SCENARIO_IDS
    assert {
        path.stem for path in (repo_root() / SCENARIO_ROOT).glob("*.json")
    } == set(FROZEN_G1_SCENARIO_IDS)

    for stage in registry["stages"]:
        stage_validator.validate(stage)
        binding = stage["scenario_binding"]
        if binding is None:
            continue
        scenario_value = scenario(binding["scenario_id"])
        assert binding["scenario_path"] == (
            SCENARIO_ROOT / f"{binding['scenario_id']}.json"
        ).as_posix()
        assert binding["scenario_sha256"] == scenario_sha256(scenario_value)


def test_observer_probe_is_no_request_but_keeps_o1_h1_g1_authority() -> None:
    observer = stages_by_id(profile())["observer-probe"]

    assert observer["scenario_binding"] is None
    assert observer["actor_counts"] == {
        "observers": 1,
        "buyers": 0,
        "sellers": 0,
        "host_operators": 1,
    }
    assert observer["load_counts"] == {"selected_listings": 0, "requests": 0}
    assert observer["independently_assignable_gpus"] == 1
    assert observer["expected_outcomes"] is None
    assert observer["execution_boundary"] == "readiness"
    assert observer["actor_trigger"] == "none"


def test_mode_neutral_shapes_are_reused_without_relabeling_evidence() -> None:
    stages = stages_by_id(profile())
    reference = stages["b1-s1-g1-reference"]
    qualification = stages["b1-s1-g1-qualification"]
    measured = stages["q0-b1-s1-g1-measured"]

    assert (
        reference["scenario_binding"]
        == qualification["scenario_binding"]
        == measured["scenario_binding"]
    )
    assert {
        (reference["execution_boundary"], reference["actor_trigger"]),
        (qualification["execution_boundary"], qualification["actor_trigger"]),
        (measured["execution_boundary"], measured["actor_trigger"]),
    } == {
        ("real-reference", "controller-driven"),
        ("real-qualification", "agent-triggered"),
        ("real-measured", "agent-triggered"),
    }

    for reuse_id in ("serialized-reuse-a", "serialized-reuse-b"):
        assert (
            stages[f"{reuse_id}-qualification"]["scenario_binding"]
            == stages[f"{reuse_id}-measured"]["scenario_binding"]
        )


def test_qualification_order_and_optional_stage_set_are_exact(
    pinned_profile_authority: ValidatedProfileRegistry,
) -> None:
    registry = profile()
    validate_qualification_sequence(
        pinned_profile_authority,
        list(QUALIFICATION_STAGE_ORDER),
    )

    for invalid in (
        QUALIFICATION_STAGE_ORDER[1:],
        (*QUALIFICATION_STAGE_ORDER, "extra"),
        (
            QUALIFICATION_STAGE_ORDER[1],
            QUALIFICATION_STAGE_ORDER[0],
            *QUALIFICATION_STAGE_ORDER[2:],
        ),
    ):
        with pytest.raises(CapacityValidationError, match="exact seven-stage"):
            validate_qualification_sequence(pinned_profile_authority, invalid)

    assert {
        stage["stage_id"] for stage in registry["stages"] if stage["optional"]
    } == {
        *MEASURED_BUYER_REFINEMENT_STAGES,
        "b4-s3-g1-measured",
    }

    ambient_authority = validate_profile_registry(registry, repo_root())
    with pytest.raises(CapacityValidationError, match="Git-pinned"):
        validate_qualification_sequence(
            ambient_authority,
            QUALIFICATION_STAGE_ORDER,
        )


def test_registry_binding_and_scenario_byte_drift_are_rejected(
    tmp_path: Path,
) -> None:
    registry = profile()
    drifted_binding = deepcopy(registry)
    stages_by_id(drifted_binding)["b1-s1-g1-reference"]["scenario_binding"][
        "scenario_sha256"
    ] = "f" * 64
    with pytest.raises(CapacityValidationError, match="canonical scenario SHA-256"):
        validate_profile_registry(drifted_binding, repo_root())

    copied_root = copy_contract(tmp_path)
    copied_scenario = scenario("b1-s1-g1", copied_root)
    copied_scenario["requests"][0]["request_id"] = "request-9"
    (copied_root / SCENARIO_ROOT / "b1-s1-g1.json").write_text(
        json.dumps(copied_scenario, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CapacityValidationError, match="canonical scenario SHA-256"):
        validate_profile_registry(profile(copied_root), copied_root)


def test_git_pinned_profile_registry_binds_registry_schema_and_scenarios(
    tmp_path: Path,
) -> None:
    copied_root = copy_contract(tmp_path)
    scm_ref = commit_contract(copied_root)
    expected_digest = canonical_sha256(profile(copied_root))

    authority = resolve_pinned_profile_registry(
        copied_root,
        scm_ref,
        PROFILE_PATH.as_posix(),
        expected_sha256=expected_digest,
    )

    assert authority.profile_id == "g1-v2"
    assert authority.scm_ref == scm_ref
    assert authority.relative_path == PROFILE_PATH.as_posix()
    assert authority.canonical_sha256 == expected_digest
    validate_qualification_sequence(authority, QUALIFICATION_STAGE_ORDER)

    with pytest.raises(CapacityValidationError, match="profile path"):
        resolve_pinned_profile_registry(
            copied_root,
            scm_ref,
            "tools/issue-discovery/config/capacity/profiles/../g1-v2.json",
        )
    with pytest.raises(CapacityValidationError, match="declared profile SHA-256"):
        resolve_pinned_profile_registry(
            copied_root,
            scm_ref,
            expected_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    "drift_path",
    [
        PROFILE_PATH,
        SCHEMA_ROOT / "capacity-profile-registry.schema.json",
    ],
)
def test_git_pinned_profile_rejects_hidden_raw_authority_drift(
    tmp_path: Path,
    drift_path: Path,
) -> None:
    copied_root = copy_contract(tmp_path)
    scm_ref = commit_contract(copied_root)
    git(copied_root, "update-index", "--assume-unchanged", drift_path.as_posix())
    path = copied_root / drift_path
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert git(copied_root, "status", "--porcelain", "--", drift_path.as_posix()) == ""

    with pytest.raises(CapacityValidationError, match="worktree bytes differ"):
        resolve_pinned_profile_registry(copied_root, scm_ref)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.update(scenario_id="b1-s2-g1"),
            "not one of",
        ),
        (
            lambda value: value["physical_capacity"].update(
                independently_assignable_gpus=2
            ),
            "1 was expected",
        ),
        (
            lambda value: value.update(scenario_id="b2-s1-g1"),
            "exact O/B/S/H/L/R/G1 shape",
        ),
    ],
)
def test_unknown_g2_and_mislabeled_scenario_shapes_are_rejected(
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    value = mutate_scenario("b1-s1-g1", mutation)
    with pytest.raises(CapacityValidationError, match=message):
        validate_scenario_in_memory(value, repo_root())


def test_single_and_multi_seller_fence_modes_are_exact() -> None:
    validate_scenario_in_memory(scenario("b1-s1-g1"), repo_root())
    validate_scenario_in_memory(scenario("b2-s2-g1"), repo_root())

    wrong_single = mutate_scenario(
        "b1-s1-g1",
        lambda value: value["listing_topology"].update(
            capacity_authority_mode="shared-globally-fenced"
        ),
    )
    wrong_shared = mutate_scenario(
        "b2-s2-g1",
        lambda value: value["listing_topology"].update(
            capacity_authority_mode="single-seller"
        ),
    )
    for value in (wrong_single, wrong_shared):
        with pytest.raises(CapacityValidationError, match="capacity_authority_mode"):
            validate_scenario_in_memory(value, repo_root())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["requests"][1].update(seller_slot="seller-1"),
            "seller/listing pair",
        ),
        (
            lambda value: value["requests"][1].update(
                seller_slot="seller-1",
                listing_slot="listing-1",
            ),
            "select every declared logical",
        ),
        (
            lambda value: value["listing_topology"]["sellers"][1].update(
                service_slot="seller-service-1"
            ),
            "distinct service slots",
        ),
        (
            lambda value: value["listing_topology"]["sellers"][1].update(
                listing_slots=["listing-1"]
            ),
            "exactly one seller",
        ),
        (
            lambda value: value["requests"][1].update(buyer_slot="buyer-9"),
            "exactly one request for every declared buyer",
        ),
        (
            lambda value: value["listing_topology"]["sellers"][0].update(
                listing_slots=["listing-1", "listing-3"]
            ),
            "exactly one selected listing",
        ),
    ],
)
def test_seller_listing_and_request_ownership_is_fail_closed(
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    value = mutate_scenario("b2-s2-g1", mutation)
    with pytest.raises(CapacityValidationError, match=message):
        validate_scenario_in_memory(value, repo_root())


def test_buyer_refinement_selects_exact_integer_bisection_paths() -> None:
    lower_bound = initial_buyer_passes(True, True, True, True)
    assert select_buyer_refinement_counts(lower_bound) == ()
    assert retained_buyer_refinement_counts(lower_bound) == (2, 4, 8)
    assert buyer_frontier_is_lower_bound(lower_bound) is True
    assert select_buyer_refinement_counts(
        initial_buyer_passes(True, False, False, False)
    ) == ()
    assert select_buyer_refinement_counts(
        initial_buyer_passes(True, True, False, False)
    ) == (3,)
    assert select_buyer_refinement_counts(
        initial_buyer_passes(
            True,
            True,
            False,
            False,
            **{"b3-s1-g1-measured": True},
        )
    ) == (3,)
    assert select_buyer_refinement_counts(
        initial_buyer_passes(True, True, True, False)
    ) == (6,)
    assert select_buyer_refinement_counts(
        initial_buyer_passes(
            True,
            True,
            True,
            False,
            **{"b6-s1-g1-measured": False},
        )
    ) == (6, 5)
    assert select_buyer_refinement_counts(
        initial_buyer_passes(
            True,
            True,
            True,
            False,
            **{"b6-s1-g1-measured": True},
        )
    ) == (6, 7)

    passes = initial_buyer_passes(
        True,
        True,
        True,
        False,
        **{
            "b6-s1-g1-measured": False,
            "b5-s1-g1-measured": True,
        },
    )
    validate_buyer_refinement_sequence(
        ("b6-s1-g1-measured", "b5-s1-g1-measured"),
        passes,
    )
    assert retained_buyer_refinement_counts(passes) == (4, 5, 6)
    assert buyer_frontier_is_lower_bound(passes) is False
    assert (
        buyer_frontier_is_lower_bound(passes, generator_ended_first=True)
        is True
    )


def test_buyer_refinement_rejects_nonmonotonic_or_unfinished_search() -> None:
    with pytest.raises(CapacityValidationError, match="monotonic passing prefix"):
        select_buyer_refinement_counts(
            initial_buyer_passes(True, False, True, False)
        )

    passes = initial_buyer_passes(True, True, True, False)
    with pytest.raises(CapacityValidationError, match="integer bisection"):
        validate_buyer_refinement_sequence((), passes)
    with pytest.raises(CapacityValidationError, match="pass/fail result"):
        validate_buyer_refinement_sequence(("b6-s1-g1-measured",), passes)


@pytest.mark.parametrize("invalid_result", [1, 0, "true", None])
def test_progression_rejects_non_boolean_stage_results(
    invalid_result: object,
) -> None:
    passes: dict[str, Any] = initial_buyer_passes(True, True, True, True)
    passes["q0-b1-s1-g1-measured"] = invalid_result
    with pytest.raises(CapacityValidationError, match="exact boolean"):
        select_buyer_refinement_counts(passes)  # type: ignore[arg-type]


def test_seller_selection_is_gated_by_b2_and_b4_frontiers() -> None:
    common = {
        "buyer_frontier_receipt_sha256": AUTHORITY_SHA256,
        "distinct_seller_identities": 4,
        "distinct_service_instances": 4,
    }
    assert select_seller_stage_ids(
        buyer_correctness_frontier=4,
        load_generator_frontier=4,
        stage_passes={},
        **common,
    ) == ("b2-s2-g1-measured",)
    assert select_seller_stage_ids(
        buyer_correctness_frontier=4,
        load_generator_frontier=4,
        stage_passes={"b2-s2-g1-measured": False},
        **common,
    ) == ("b2-s2-g1-measured",)
    assert select_seller_stage_ids(
        buyer_correctness_frontier=3,
        load_generator_frontier=4,
        stage_passes={"b2-s2-g1-measured": True},
        **common,
    ) == ("b2-s2-g1-measured",)
    assert select_seller_stage_ids(
        buyer_correctness_frontier=4,
        load_generator_frontier=4,
        stage_passes={"b2-s2-g1-measured": True},
        **common,
    ) == ("b2-s2-g1-measured", "b4-s2-g1-measured")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("buyer_correctness_frontier", True),
        ("load_generator_frontier", -1),
        ("distinct_seller_identities", 2.0),
        ("distinct_service_instances", "2"),
    ],
)
def test_seller_selection_rejects_non_integer_authority(
    field: str,
    invalid_value: object,
) -> None:
    authority: dict[str, Any] = {
        "buyer_frontier_receipt_sha256": AUTHORITY_SHA256,
        "buyer_correctness_frontier": 4,
        "load_generator_frontier": 4,
        "distinct_seller_identities": 2,
        "distinct_service_instances": 2,
        "stage_passes": {"b2-s2-g1-measured": False},
    }
    authority[field] = invalid_value
    with pytest.raises(CapacityValidationError, match="nonnegative integer"):
        select_seller_stage_ids(**authority)


@pytest.mark.parametrize("receipt", [True, 1, "A" * 64, "a" * 63, ""])
def test_seller_selection_requires_exact_frontier_receipt_digest(
    receipt: object,
) -> None:
    with pytest.raises(CapacityValidationError, match="lowercase SHA-256"):
        select_seller_stage_ids(
            buyer_frontier_receipt_sha256=receipt,  # type: ignore[arg-type]
            buyer_correctness_frontier=4,
            load_generator_frontier=4,
            distinct_seller_identities=2,
            distinct_service_instances=2,
            stage_passes={"b2-s2-g1-measured": False},
        )


def test_seller_selection_runs_s4_then_s3_only_on_failure() -> None:
    common = {
        "buyer_frontier_receipt_sha256": AUTHORITY_SHA256,
        "buyer_correctness_frontier": 4,
        "load_generator_frontier": 4,
        "distinct_seller_identities": 4,
        "distinct_service_instances": 4,
    }
    assert select_seller_stage_ids(
        stage_passes={
            "b2-s2-g1-measured": True,
            "b4-s2-g1-measured": True,
        },
        **common,
    ) == (
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s4-g1-measured",
    )
    assert select_seller_stage_ids(
        stage_passes={
            "b2-s2-g1-measured": True,
            "b4-s2-g1-measured": True,
            "b4-s4-g1-measured": True,
        },
        **common,
    ) == (
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s4-g1-measured",
    )
    assert select_seller_stage_ids(
        stage_passes={
            "b2-s2-g1-measured": True,
            "b4-s2-g1-measured": True,
            "b4-s4-g1-measured": False,
        },
        **common,
    ) == (
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s4-g1-measured",
        "b4-s3-g1-measured",
    )


def test_seller_selection_uses_s3_fallback_or_stops_at_s2_lower_bound() -> None:
    common = {
        "buyer_frontier_receipt_sha256": AUTHORITY_SHA256,
        "buyer_correctness_frontier": 4,
        "load_generator_frontier": 4,
        "stage_passes": {
            "b2-s2-g1-measured": True,
            "b4-s2-g1-measured": True,
        },
    }
    assert select_seller_stage_ids(
        distinct_seller_identities=3,
        distinct_service_instances=3,
        **common,
    ) == (
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s3-g1-measured",
    )
    assert select_seller_stage_ids(
        distinct_seller_identities=2,
        distinct_service_instances=2,
        **common,
    ) == ("b2-s2-g1-measured", "b4-s2-g1-measured")

    with pytest.raises(CapacityValidationError, match="lowercase SHA-256"):
        select_seller_stage_ids(
            buyer_frontier_receipt_sha256="",
            buyer_correctness_frontier=4,
            load_generator_frontier=4,
            distinct_seller_identities=2,
            distinct_service_instances=2,
            stage_passes={},
        )


def test_measured_sequence_enforces_seller_decisions_and_results(
    pinned_profile_authority: ValidatedProfileRegistry,
) -> None:
    authority = pinned_profile_authority
    passes = initial_buyer_passes(True, True, True, True)
    base = measured_prefix()
    ambient_authority = profile_authority()
    with pytest.raises(CapacityValidationError, match="Git-pinned"):
        validate_measured_sequence(
            ambient_authority,
            base,
            stage_passes=passes,
            pre_q0_registry_sha256=ambient_authority.canonical_sha256,
            pre_q0_registry_raw_sha256=ambient_authority.raw_sha256,
        )
    validate_measured_sequence(
        authority,
        base,
        stage_passes=passes,
        pre_q0_registry_sha256=authority.canonical_sha256,
        pre_q0_registry_raw_sha256=authority.raw_sha256,
    )

    seller_passes = {
        **passes,
        "b2-s2-g1-measured": True,
        "b4-s2-g1-measured": True,
        "b4-s4-g1-measured": False,
        "b4-s3-g1-measured": True,
    }
    complete = (
        *base,
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s4-g1-measured",
        "b4-s3-g1-measured",
    )
    validate_measured_sequence(
        authority,
        complete,
        stage_passes=seller_passes,
        pre_q0_registry_sha256=authority.canonical_sha256,
        pre_q0_registry_raw_sha256=authority.raw_sha256,
        buyer_frontier_receipt_sha256=AUTHORITY_SHA256,
        buyer_correctness_frontier=4,
        load_generator_frontier=4,
        distinct_seller_identities=4,
        distinct_service_instances=4,
    )

    with pytest.raises(CapacityValidationError, match="bounded progression"):
        validate_measured_sequence(
            authority,
            (*base, "b2-s2-g1-measured"),
            stage_passes={**passes, "b2-s2-g1-measured": True},
            pre_q0_registry_sha256=authority.canonical_sha256,
            pre_q0_registry_raw_sha256=authority.raw_sha256,
            buyer_frontier_receipt_sha256=AUTHORITY_SHA256,
            buyer_correctness_frontier=4,
            load_generator_frontier=4,
            distinct_seller_identities=4,
            distinct_service_instances=4,
        )

    fallback_passes = {
        **passes,
        "b2-s2-g1-measured": True,
        "b4-s2-g1-measured": True,
        "b4-s3-g1-measured": True,
    }
    fallback_sequence = (
        *base,
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s3-g1-measured",
    )
    validate_measured_sequence(
        authority,
        fallback_sequence,
        stage_passes=fallback_passes,
        pre_q0_registry_sha256=authority.canonical_sha256,
        pre_q0_registry_raw_sha256=authority.raw_sha256,
        buyer_frontier_receipt_sha256=AUTHORITY_SHA256,
        buyer_correctness_frontier=4,
        load_generator_frontier=4,
        distinct_seller_identities=3,
        distinct_service_instances=3,
    )
    with pytest.raises(CapacityValidationError, match="bounded progression"):
        validate_measured_sequence(
            authority,
            fallback_sequence,
            stage_passes=fallback_passes,
            pre_q0_registry_sha256=authority.canonical_sha256,
            pre_q0_registry_raw_sha256=authority.raw_sha256,
            buyer_frontier_receipt_sha256=AUTHORITY_SHA256,
            buyer_correctness_frontier=4,
            load_generator_frontier=4,
            distinct_seller_identities=2,
            distinct_service_instances=2,
        )
    with pytest.raises(CapacityValidationError, match="bounded progression"):
        validate_measured_sequence(
            authority,
            complete[:-1],
            stage_passes=seller_passes,
            pre_q0_registry_sha256=authority.canonical_sha256,
            pre_q0_registry_raw_sha256=authority.raw_sha256,
            buyer_frontier_receipt_sha256=AUTHORITY_SHA256,
            buyer_correctness_frontier=4,
            load_generator_frontier=4,
            distinct_seller_identities=4,
            distinct_service_instances=4,
        )


def test_pre_q0_registry_digest_fences_measured_execution(
    tmp_path: Path,
    pinned_profile_authority: ValidatedProfileRegistry,
) -> None:
    authority = pinned_profile_authority
    passes = initial_buyer_passes(True, True, True, True)
    validate_measured_sequence(
        authority,
        measured_prefix(),
        stage_passes=passes,
        pre_q0_registry_sha256=authority.canonical_sha256,
        pre_q0_registry_raw_sha256=authority.raw_sha256,
    )

    reordered_root = copy_contract(tmp_path / "canonical-drift")
    reordered = profile(reordered_root)
    admission = stages_by_id(reordered)["b1-s1-g1-reference"]["admission"]["all_of"]
    admission.reverse()
    (reordered_root / PROFILE_PATH).write_text(
        json.dumps(reordered, indent=2) + "\n",
        encoding="utf-8",
    )
    reordered_ref = commit_contract(reordered_root)
    reordered_authority = resolve_pinned_profile_registry(
        reordered_root,
        reordered_ref,
    )
    with pytest.raises(CapacityValidationError, match="changed after Q0"):
        validate_measured_sequence(
            reordered_authority,
            measured_prefix(),
            stage_passes=passes,
            pre_q0_registry_sha256=authority.canonical_sha256,
            pre_q0_registry_raw_sha256=reordered_authority.raw_sha256,
        )

    copied_root = copy_contract(tmp_path / "raw-drift")
    copied_ref = commit_contract(copied_root)
    file_authority = resolve_pinned_profile_registry(copied_root, copied_ref)
    registry_path = copied_root / PROFILE_PATH
    registry_path.write_text(
        json.dumps(profile(copied_root), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CapacityValidationError, match="worktree bytes differ"):
        validate_measured_sequence(
            file_authority,
            measured_prefix(),
            stage_passes=passes,
            pre_q0_registry_sha256=file_authority.canonical_sha256,
            pre_q0_registry_raw_sha256=file_authority.raw_sha256,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda registry: stages_by_id(registry)["q0-b1-s1-g1-measured"][
            "admission"
        ]["all_of"].append("previous-stage-clean"),
        lambda registry: stages_by_id(registry)["b4-s3-g1-measured"][
            "admission"
        ]["any_of"].pop(),
    ],
)
def test_stage_admission_drift_is_rejected(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    registry = profile()
    mutation(registry)
    with pytest.raises(CapacityValidationError, match="exact stage contract"):
        validate_profile_registry(registry, repo_root())
