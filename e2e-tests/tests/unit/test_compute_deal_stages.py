"""The canonical compute deal's stage set is declared, ordered, and wired.

The stage set is read from source rather than collected, so a scenario module is
checked without its lane's settings or services; one stage's body is run with
injected mocks where its skip is the behaviour under test. Each compute lane's
scenario is one row of ``LANES``; a lane that runs the canonical deal adds its
row.

The stages module defines two kinds of stage: shared stages, which every lane
runs, and mock-lane stages (subclasses of ``MockLaneStage``), which only a lane
delivering through the provisioning mock profile runs. Both are defined in the
mock lanes' run order, so a mock lane declares every stage in definition order.
The lane delivering through a real host, ``REAL_LANE``, declares every shared
stage in that order and none of the mock-lane stages, with its own between them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.e2e.roles.helpers.compute_deal_stages import (
    ComputeDealState,
    Stage08b_SettlementSubmittedAndJobQueued,
)
from tests.unit.stage_sources import (
    StateUse,
    base_names,
    class_named,
    classes,
    domain_stages,
    fields,
    is_stage,
    run_order,
    state_use,
    tree,
)

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
SHARED = ROLES / "helpers" / "compute_deal_stages.py"
DOMAIN_DEAL = ROLES / "helpers" / "domain_deal.py"
STATE = "deal_state"
DRIVER = "deal_driver"
#: The fixture only a mock lane provides: the provisioning service's mock routes.
MOCK_TEST_CLIENT = "provisioning_test_client"
MOCK_LANE_MARKER = "MockLaneStage"


@dataclass(frozen=True)
class Lane:
    name: str
    scenario: Path
    #: The module and class of the state the lane's stages write.
    state_module: Path
    state_class: str


LANES = (
    Lane(
        "vms",
        ROLES / "scenarios" / "vms" / "test_full_deal.py",
        ROLES / "scenarios" / "vms" / "conftest.py",
        "DealState",
    ),
    Lane(
        "bare_metal",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_mock_deal.py",
        ROLES / "scenarios" / "bare_metal" / "conftest.py",
        "BareMetalDealState",
    ),
)
#: The lanes that deliver through the provisioning mock profile.
MOCK_LANES = LANES
#: The lane that delivers through a real host.
REAL_LANE = Lane(
    "vms_real",
    ROLES / "scenarios" / "vms" / "test_real_provisioning_deal.py",
    ROLES / "scenarios" / "vms" / "real_compute_deal_driver.py",
    "RealVmDealState",
)
ALL_LANES = (*LANES, REAL_LANE)

#: The real lane's run order: every shared stage, by its name here, with the
#: lane's own stages, by their declared names, where they replace a mock lane's
#: gate or prove what the mock lanes cannot.
REAL_LANE_ORDER = [
    "Stage00_LifecycleHeld",
    "Stage00a_StorefrontHealth",
    "Stage00b_RegistryReachable",
    "Stage00c_ProvisioningHealth",
    "Stage00c2_ProvisioningContractPins",
    "Stage00d_NegotiationStrategy",
    # The VM-execution check, in place of the mock lanes' 00e.
    "TestStage00e1_VmExecutionIsReal",
    "Stage00f1_ExecutorHostRegistry",
    "TestStage00f2_RegisteredHostIsTheTarget",
    "Stage00g_AlkahestConfigured",
    "Stage00h_ProvisioningStorefrontLink",
    "TestStage02b_ListingCreated",
    "TestStage03b_ListingPublished",
    "Stage04a_PrimaryRegistryPublish",
    "Stage05a_EvaluateNegotiate",
    "Stage05b_NegotiationStartsAndVisible",
    "Stage06b_ForceAcceptAndTerminal",
    "Stage07_OnChainEscrow",
    "Stage07b_VerifyEscrow",
    "Stage08a_EvaluateSettle",
    # The settlement preflight, immediately before settlement.
    "TestStage08a2_SettlementPreviewChoseTheTarget",
    "Stage08b_SettlementSubmittedAndJobQueued",
    # The create-job poll, where a mock lane releases its create gate.
    "TestStage08b3_CreateJobSucceeded",
    "Stage09a_FulfillmentConvergesToActive",
    "TestStage09a2_CapacityEventCycle",
    "Stage09b_SettlementReadyAndCredentials",
    "Stage09c_LeaseRecorded",
    "TestStage09c3_LeaseNamesTheCreateJob",
    # The access checks.
    "TestStage09d_BuyerReachesTheNegotiatedShape",
    "TestStage09e_UnrelatedKeyRefused",
    "Stage10a_LeaseExpirySetup",
    "Stage10b_LeaseCycleBeginsTeardown",
    "Stage11a_TeardownDispatch",
    # The teardown-job poll, where a mock lane releases its teardown gate.
    "TestStage11a3_TeardownJobSucceeded",
    "Stage11b_TeardownCompletion",
    # The guest's absence from the host, then the end of its access.
    "TestStage11c_GuestGoneFromHost",
    "TestStage11d_DeliveredAccessEnded",
]


STAGES_TREE = tree(SHARED)
STAGES = [node for node in classes(STAGES_TREE) if is_stage(node)]
STAGE_NAMES = [node.name for node in STAGES]
MOCK_LANE_STAGES = [node for node in STAGES if MOCK_LANE_MARKER in base_names(node)]
SHARED_STAGES = [node for node in STAGES if MOCK_LANE_MARKER not in base_names(node)]
SHARED_NAMES = [node.name for node in SHARED_STAGES]
COMPUTE_FIELDS = fields(class_named(STAGES_TREE, "ComputeDealState"))
DOMAIN_DEAL_FIELDS = fields(class_named(tree(DOMAIN_DEAL), "DomainDealState"))
STAGES_USE = state_use(STAGES, state=STATE)


def _members(protocol: str) -> set[str]:
    node = class_named(STAGES_TREE, protocol)
    return {
        item.name for item in node.body if isinstance(item, ast.FunctionDef)
    } | fields(node)


MOCK_GATES = _members("MockGates")


def _lane_own_stages(lane: Lane) -> list[ast.ClassDef]:
    return [
        node for node in domain_stages(lane.scenario)
        if not set(base_names(node)) & set(STAGE_NAMES)
    ]


def _scenario(lane: Lane) -> list[tuple[str, StateUse]]:
    return run_order(lane.scenario, STAGES, state=STATE)


def _driver_annotation(stage: ast.ClassDef) -> str | None:
    """The annotation of the driver a stage's test takes, if it takes one."""
    for item in stage.body:
        if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
            for arg in item.args.args:
                if arg.arg == DRIVER:
                    assert isinstance(arg.annotation, ast.Name), (
                        f"{stage.name} takes {DRIVER} without naming its protocol"
                    )
                    return arg.annotation.id
    return None


def test_the_stages_are_not_collected_where_they_are_defined():
    assert SHARED_STAGES, "the stages module defines no shared stage"
    assert MOCK_LANE_STAGES, "the stages module defines no mock-lane stage"
    collected = [node.name for node in classes(STAGES_TREE) if node.name.startswith("Test")]
    assert collected == [], collected


@pytest.mark.parametrize("lane", MOCK_LANES, ids=lambda lane: lane.name)
def test_a_mock_lane_declares_every_stage_once_in_order(lane: Lane):
    declared: list[str] = []
    for node in domain_stages(lane.scenario):
        defined = [name for name in base_names(node) if name in STAGE_NAMES]
        if not defined:
            continue
        (base,) = defined
        assert node.name == "Test" + base, (
            f"{lane.name} declares {base} as {node.name}; the stage's ID and "
            "test names come from its name"
        )
        assert len(node.body) == 1 and isinstance(node.body[0], ast.Pass), (
            f"{lane.name}'s {node.name} has a body of its own; a stage's body is "
            "defined once, and a domain's part goes through its driver"
        )
        declared.append(base)
    assert declared == STAGE_NAMES, (
        f"{lane.name} declares the stages {declared}; a mock lane declares each "
        f"once, in the defined order {STAGE_NAMES}"
    )


def test_the_real_lane_runs_every_shared_stage_in_its_order_and_no_mock_stage():
    declared: list[str] = []
    for node in domain_stages(REAL_LANE.scenario):
        defined = [name for name in base_names(node) if name in STAGE_NAMES]
        if not defined:
            declared.append(node.name)
            continue
        (base,) = defined
        assert base in SHARED_NAMES, f"the real lane declares mock-lane stage {base}"
        assert node.name == "Test" + base, (base, node.name)
        assert len(node.body) == 1 and isinstance(node.body[0], ast.Pass), (
            f"the real lane's {node.name} has a body of its own"
        )
        declared.append(base)
    assert [name for name in declared if name in SHARED_NAMES] == SHARED_NAMES, (
        "the real lane runs every shared stage once, in the defined order"
    )
    assert declared == REAL_LANE_ORDER, declared


def test_the_real_lane_consumes_every_field_it_produces():
    """The mock lanes' consumption check reads every compute field, and the real
    lane produces none of the mock gates'; here every field it does produce is
    read by a later stage, or by the module's own fixtures, whose finalisers
    read the state once every stage has run."""
    produced: set[str] = set()
    consumed: set[str] = set()
    for _name, use in _scenario(REAL_LANE):
        consumed |= (use.read | use.required) & produced
        produced |= use.written
    fixtures = [
        node for node in tree(REAL_LANE.scenario).body if isinstance(node, ast.FunctionDef)
    ]
    finalised = state_use(fixtures, state=STATE)
    consumed |= finalised.read | finalised.required
    assert produced - consumed == set(), sorted(produced - consumed)


def test_no_shared_stage_touches_a_mock_gate():
    """A shared stage runs in a real lane too, whose driver has no gates and
    whose stack serves no mock routes.

    Read from each shared stage's own source: a gate reached through a helper
    the stage calls is beyond what this sees.
    """
    offending = {}
    for stage in SHARED_STAGES:
        used = set()
        for node in ast.walk(stage):
            if isinstance(node, ast.Attribute) and (
                node.attr in MOCK_GATES | {MOCK_TEST_CLIENT}
            ):
                used.add(node.attr)
            if isinstance(node, ast.arg) and node.arg == MOCK_TEST_CLIENT:
                used.add(MOCK_TEST_CLIENT)
            if isinstance(node, ast.Name) and node.id in {MOCK_TEST_CLIENT, "MockGates"}:
                used.add(node.id)
        if used:
            offending[stage.name] = sorted(used)
    assert offending == {}, offending


def test_each_stage_takes_the_driver_part_its_kind_may_use():
    wrong = {}
    for stage in STAGES:
        annotation = _driver_annotation(stage)
        if annotation is None:
            continue
        expected = "MockGates" if stage in MOCK_LANE_STAGES else "ComputeDealDriver"
        if annotation != expected:
            wrong[stage.name] = annotation
    assert wrong == {}, wrong


def test_the_shared_driver_part_names_no_mock_gate():
    assert MOCK_GATES, "MockGates declares no member"
    assert _members("ComputeDealDriver") & MOCK_GATES == set()


def test_settlement_skips_until_the_preflight_before_it_passes():
    """08b submits settlement, so a failed preflight must stop it, not let it
    submit onto a deal nothing checked."""
    storefront = MagicMock()
    provisioning = MagicMock()
    driver = MagicMock()
    state = ComputeDealState(
        domain_identity="compute", negotiation_id="negotiation", real_escrow_uid="0xescrow",
    )
    with pytest.raises(pytest.skip.Exception, match="_settle_preflight_passed"):
        Stage08b_SettlementSubmittedAndJobQueued().test_08b_settlement_submitted_and_provisioning_job_queued(
            storefront, provisioning, {"wallet_address": "0xbuyer"}, driver, state,
        )
    storefront.settle_evm.assert_not_called()
    driver.settle_dispatched.assert_not_called()


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_a_lane_state_extends_the_compute_state(lane: Lane):
    node = class_named(tree(lane.state_module), lane.state_class)
    assert "ComputeDealState" in base_names(node), base_names(node)


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_every_prerequisite_is_produced_by_an_earlier_stage(lane: Lane):
    """A stage requiring a field no earlier stage writes skips forever."""
    produced: set[str] = set()
    for name, use in _scenario(lane):
        missing = use.required - produced
        assert missing == set(), (
            f"{lane.name}'s {name} requires {sorted(missing)}, which no "
            "earlier stage produces"
        )
        produced |= use.written


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_every_field_read_is_produced_first(lane: Lane):
    produced: set[str] = set()
    for name, use in _scenario(lane):
        missing = use.read - produced - use.written - DOMAIN_DEAL_FIELDS
        assert missing == set(), (
            f"{lane.name}'s {name} reads {sorted(missing)} before any stage "
            "writes it"
        )
        produced |= use.written


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_each_compute_state_field_has_one_producer(lane: Lane):
    """A handoff written by two stages lets a consumer read the first
    producer's value when the second fails, instead of skipping."""
    producers: dict[str, list[str]] = {}
    for name, use in _scenario(lane):
        for field_name in use.written & COMPUTE_FIELDS:
            producers.setdefault(field_name, []).append(name)
    repeated = {name: stages for name, stages in producers.items() if len(stages) > 1}
    assert repeated == {}, repeated


@pytest.mark.parametrize("lane", MOCK_LANES, ids=lambda lane: lane.name)
def test_every_compute_state_field_is_consumed_after_it_is_produced(lane: Lane):
    """A field no later stage reads records nothing a later stage needs."""
    produced: set[str] = set()
    consumed: set[str] = set()
    for _name, use in _scenario(lane):
        consumed |= (use.read | use.required) & produced
        produced |= use.written
    unconsumed = COMPUTE_FIELDS - consumed
    assert unconsumed == set(), (
        f"{lane.name}: no stage after its producer reads {sorted(unconsumed)}"
    )


def test_the_stages_use_only_declared_fields():
    declared = COMPUTE_FIELDS | DOMAIN_DEAL_FIELDS
    used = STAGES_USE.written | STAGES_USE.required
    assert used - declared == set(), used - declared


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_a_lane_stage_uses_only_its_states_fields(lane: Lane):
    declared = (
        fields(class_named(tree(lane.state_module), lane.state_class))
        | COMPUTE_FIELDS
        | DOMAIN_DEAL_FIELDS
    )
    use = state_use(_lane_own_stages(lane), state=STATE)
    used = use.written | use.required
    assert used - declared == set(), used - declared
