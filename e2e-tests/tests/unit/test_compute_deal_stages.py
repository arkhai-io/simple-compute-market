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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.e2e.roles.helpers.compute_deal_stages import (
    MAX_CLOCK_WAIT,
    ComputeDealState,
    Stage08b_SettlementSubmittedAndJobQueued,
    Stage09c_LeaseRecorded,
    wait_until,
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
    running_stages,
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
REAL_BM_LANE = Lane(
    "bare_metal_real",
    ROLES / "scenarios" / "bare_metal" / "test_real_provisioning_deal.py",
    ROLES / "scenarios" / "bare_metal" / "real_compute_deal_driver.py",
    "RealBareMetalDealState",
)
REAL_LANES = (REAL_LANE, REAL_BM_LANE)
#: The buyer purchases through the shipped buyer, which run the stages from
#: fulfillment onwards after the purchase stages of ``buyer_purchase_stages.py``
#: (held to their own order by ``test_buyer_purchase_stages.py``).
PURCHASE_LANES = (
    Lane(
        "bare_metal_purchase",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_payment_deal.py",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_payment_deal.py",
        "BareMetalPurchaseState",
    ),
    Lane(
        "vms_purchase",
        ROLES / "scenarios" / "vms" / "test_vm_payment_purchase.py",
        ROLES / "scenarios" / "vms" / "test_vm_payment_purchase.py",
        "VmPurchaseState",
    ),
    Lane(
        "vms_qualification",
        ROLES / "scenarios" / "vms" / "test_vm_qualification.py",
        ROLES / "scenarios" / "vms" / "test_vm_qualification.py",
        "VmQualificationState",
    ),
    Lane(
        "bare_metal_qualification",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_qualification.py",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_qualification.py",
        "BareMetalQualificationState",
    ),
)
ALL_LANES = (*LANES, *REAL_LANES, *PURCHASE_LANES)
#: Domain-own stages defined outside a scenario module, which a scenario
#: subclasses with an empty body; read from their own source.
DOMAIN_STAGES = [
    stage
    for module in (
        ROLES / "scenarios" / "bare_metal" / "publication_stages.py",
        ROLES / "scenarios" / "bare_metal" / "recovery_stages.py",
        ROLES / "scenarios" / "vms" / "lifecycle_deal.py",
        ROLES / "scenarios" / "vms" / "delivery_timing_deal.py",
    )
    for stage in classes(tree(module))
]
PURCHASE_TREE = tree(ROLES / "helpers" / "buyer_purchase_stages.py")
PURCHASE_STAGES = [node for node in classes(PURCHASE_TREE) if is_stage(node)]
PURCHASE_FIELDS = fields(class_named(PURCHASE_TREE, "PurchaseState"))

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
    "Stage09c1_LateSettlementKeepsTheWindow",
    "TestStage09c3_LeaseNamesTheCreateJob",
    # The access checks.
    "TestStage09d_BuyerReachesTheNegotiatedShape",
    "TestStage09e_UnrelatedKeyRefused",
    "TestStage09f_HeartbeatOpened",
    "TestStage09g_SecondDealAccepted",
    "TestStage09h_SecondEscrowCreated",
    "TestStage09i_SecondSettlementSubmitted",
    "TestStage09j_SecondGuestAccessible",
    "TestStage09k_HeartbeatSurvivedCreate",
    "TestStage09l_SecondLeaseCutShort",
    "TestStage09m_SecondGuestReleased",
    "TestStage09n_HeartbeatSurvivedRemoval",
    "Stage10a_LeaseExpirySetup",
    "Stage10b_LeaseCycleBeginsTeardown",
    "TestStage10b2_ManagementBeforeTeardown",
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
#: Every stage body a lane may declare by subclassing it.
DECLARABLE = [*STAGES, *DOMAIN_STAGES, *PURCHASE_STAGES]
COMPUTE_FIELDS = fields(class_named(STAGES_TREE, "ComputeDealState"))
DOMAIN_DEAL_FIELDS = fields(class_named(tree(DOMAIN_DEAL), "DomainDealState"))
STAGES_USE = state_use(STAGES, state=STATE)

#: The first stage of fulfillment. It and every stage defined after it take no
#: escrow from the deal's state, and those naming the deal's settlement read its
#: settlement reference, so a deal settled other than through an Alkahest escrow
#: runs their bodies unchanged.
FIRST_FULFILLMENT_STAGE = "Stage09a_FulfillmentConvergesToActive"
FULFILLMENT_STAGES = STAGES[STAGE_NAMES.index(FIRST_FULFILLMENT_STAGE):]
#: What the stages from fulfillment onwards are handed by a lane's earlier
#: stages: which stage writes each differs between ways of settling and ending a
#: deal, and the stage reading it is one body.
HANDOFF = (
    "fulfillment_id",
    "_create_job_completed",
    "expected_host_id",
    "agreement_start",
    "agreement_end",
    "teardown_fulfillment_id",
    "_teardown_job_completed",
    "settlement_ref",
)
#: Each handoff a stage compares with the deal's lease, by that stage: its
#: writer must not have read it from the lease, or the comparison cannot fail.
COMPARED_WITH_THE_LEASE = {"expected_host_id": "Stage09c_LeaseRecorded"}
#: What a stage reads the deal's lease through, in its own source: the driver's
#: lease view, the view a stage recorded, the provisioning service's lease read,
#: and the lease writes that return the lease. Matched as attribute names, so a
#: writer that names one for any purpose counts as reading the lease, which
#: errs towards refusing a handoff.
LEASE_READS = {"lease_view", "deal_lease", "get_lease", "backdate", "truncate_lease"}


def _members(protocol: str) -> set[str]:
    node = class_named(STAGES_TREE, protocol)
    return {
        item.name for item in node.body if isinstance(item, ast.FunctionDef)
    } | fields(node)


MOCK_GATES = _members("MockGates")


def _lane_own_stages(lane: Lane) -> list[ast.ClassDef]:
    shared = set(STAGE_NAMES) | {node.name for node in PURCHASE_STAGES}
    return [
        body for _name, body in running_stages(lane.scenario, DOMAIN_STAGES)
        if not set(base_names(body)) & shared
    ]


def _scenario(lane: Lane) -> list[tuple[str, StateUse]]:
    return run_order(lane.scenario, DECLARABLE, state=STATE)


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
    # A shared stage's field that only a mock-lane stage reads is produced for
    # the mock lanes, which run the same shared body.
    gates, shared = state_use(MOCK_LANE_STAGES, state=STATE), state_use(SHARED_STAGES, state=STATE)
    consumed |= (gates.read | gates.required) - shared.read - shared.required
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
    storefront_admin = MagicMock()
    provisioning = MagicMock()
    driver = MagicMock()
    state = ComputeDealState(
        domain_identity="compute", negotiation_id="negotiation", real_escrow_uid="0xescrow",
    )
    with pytest.raises(pytest.skip.Exception, match="_settle_preflight_passed"):
        Stage08b_SettlementSubmittedAndJobQueued().test_08b_settlement_submitted_and_provisioning_job_queued(
            storefront, storefront_admin, provisioning, {"wallet_address": "0xbuyer"}, driver, state,
        )
    storefront.settle_evm.assert_not_called()
    driver.settle_dispatched.assert_not_called()


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_a_lane_state_extends_the_compute_state(lane: Lane):
    """Directly, or through a buyer purchase's state, which extends it
    (``test_buyer_purchase_stages.py``)."""
    node = class_named(tree(lane.state_module), lane.state_class)
    expected = "PurchaseState" if lane in PURCHASE_LANES else "ComputeDealState"
    assert expected in base_names(node), base_names(node)


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
        | (PURCHASE_FIELDS if lane in PURCHASE_LANES else set())
    )
    use = state_use(_lane_own_stages(lane), state=STATE)
    used = use.written | use.required
    assert used - declared == set(), used - declared


@pytest.mark.parametrize("lane", REAL_LANES, ids=lambda lane: lane.name)
def test_every_real_lane_reuses_all_shared_stages_without_mock_gates(lane):
    declared = []
    for node in domain_stages(lane.scenario):
        names = [name for name in base_names(node) if name in STAGE_NAMES]
        if names:
            (name,) = names
            assert name in SHARED_NAMES, f"{lane.name} uses mock stage {name}"
            assert len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            declared.append(name)
    assert declared == SHARED_NAMES


def _reads_the_lease(stage: ast.ClassDef) -> bool:
    return any(
        isinstance(node, ast.Attribute) and node.attr in LEASE_READS
        for node in ast.walk(stage)
    )


def handoff_faults(running: list[tuple[str, ast.ClassDef]]) -> list[str]:
    """Each handoff a stage from fulfillment onwards reads that no earlier stage
    of the lane writes, or that its writer read from the lease it is compared
    with.

    ``running`` is a lane's stages in run order, each with the body that runs
    (``running_stages``). Read from each stage's own source, as the mock-gate
    check is: a lease reached through a helper the writer calls is beyond what
    this sees.
    """
    faults = []
    for index, (name, body) in enumerate(running):
        if body not in FULFILLMENT_STAGES:
            continue
        use = state_use([body], state=STATE)
        for field_name in HANDOFF:
            if field_name not in use.read | use.required:
                continue
            writers = [
                (writer, writer_body) for writer, writer_body in running[:index]
                if field_name in state_use([writer_body], state=STATE).written
            ]
            if not writers:
                faults.append(f"{name} reads {field_name}, which no earlier stage writes")
            if COMPARED_WITH_THE_LEASE.get(field_name) == body.name:
                faults += [
                    f"{name} compares {field_name} with the lease {writer} read it from"
                    for writer, writer_body in writers if _reads_the_lease(writer_body)
                ]
    return faults


def test_no_stage_from_fulfillment_onwards_reads_the_escrow():
    assert FULFILLMENT_STAGES and FULFILLMENT_STAGES[0].name == FIRST_FULFILLMENT_STAGE
    reading = [
        stage.name
        for stage in FULFILLMENT_STAGES
        for use in [state_use([stage], state=STATE)]
        if "real_escrow_uid" in use.read | use.required
    ]
    assert reading == [], reading


def test_the_handoff_is_what_the_stages_from_fulfillment_onwards_read():
    use = state_use(FULFILLMENT_STAGES, state=STATE)
    assert set(HANDOFF) <= use.read | use.required, sorted(set(HANDOFF) - use.read - use.required)
    for field_name, reader in COMPARED_WITH_THE_LEASE.items():
        stage = class_named(STAGES_TREE, reader)
        assert stage in FULFILLMENT_STAGES and _reads_the_lease(stage), reader
        assert field_name in state_use([stage], state=STATE).read, (field_name, reader)


@pytest.mark.parametrize("lane", ALL_LANES, ids=lambda lane: lane.name)
def test_each_handoff_is_written_earlier_and_independently_of_the_lease(lane: Lane):
    running = running_stages(lane.scenario, DECLARABLE)
    assert handoff_faults(running) == []


_CONSTRUCTED_LANE = '''
from tests.e2e.roles.helpers.compute_deal_stages import Stage09c_LeaseRecorded


class TestStage08z_Settled:
    def test_08z_settled(self, deal_driver, deal_state):
        deal_state.settlement_ref = "negotiation"
        deal_state.settlement_status = "ready"
        deal_state.fulfillment_id = "fulfillment"
        deal_state._create_job_completed = True
        deal_state.agreement_start = "start"
        deal_state.agreement_end = "end"


class TestStage08y_ExpectedHost:
    def test_08y_expected_host(self, deal_driver, deal_state):
        deal_state.expected_host_id = {source}


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass
'''


@pytest.mark.parametrize(
    ("source", "faults"),
    [
        ("deal_driver.declared_host_id", []),
        (
            'deal_driver.lease_view(deal_state).refresh()["host_id"]',
            ["TestStage09c_LeaseRecorded compares expected_host_id with the lease "
             "TestStage08y_ExpectedHost read it from"],
        ),
        (
            'deal_driver.provisioning_client.get_lease("reservation").host_id',
            ["TestStage09c_LeaseRecorded compares expected_host_id with the lease "
             "TestStage08y_ExpectedHost read it from"],
        ),
    ],
    ids=["declared host", "host from the lease view", "host from the lease read"],
)
def test_an_expected_host_read_from_the_lease_fails_the_handoff_check(tmp_path, source, faults):
    scenario = tmp_path / "test_constructed_lane.py"
    scenario.write_text(_CONSTRUCTED_LANE.format(source=source))
    assert handoff_faults(running_stages(scenario, STAGES)) == faults


def test_real_bare_metal_orders_physical_effects_and_observations():
    names = [name for name, _use in _scenario(REAL_BM_LANE)]
    ordered = ["TestStage00e1_BareMetalExecutionIsReal", "TestStage00f1_ExecutorHostRegistry",
               "TestStage03a_PublicationDryRun", "TestStage03b_PublicationStepPublishes",
               "TestStage08a2_SettlementPreviewChoseTheTarget", "TestStage08b_SettlementSubmittedAndJobQueued",
               "TestStage08b3_GrantJobSucceeded", "TestStage09a_FulfillmentConvergesToActive",
               "TestStage09a2_PublicationClosesTheListing", "TestStage09bb_EvidencePublishedForTheFulfilledEscrow",
               "TestStage09d_BuyerConnectsWithPinnedHostKey", "TestStage09e_UnrelatedKeyRefused",
               "TestStage10b2_ManagementBeforeReclaim", "TestStage11a_TeardownDispatch",
               "TestStage11a3_ReclaimJobSucceeded", "TestStage11b_TeardownCompletion",
               "TestStage11c_DeliveredAccessEnded"]
    assert [names.index(name) for name in ordered] == sorted(names.index(name) for name in ordered)


class _Clock:
    """A wall clock a sleep advances, by less than it was asked to when told to."""

    def __init__(self, start: datetime, *, shortfall: timedelta = timedelta(0)):
        self.at, self.shortfall, self.sleeps = start, shortfall, []

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.at += timedelta(seconds=seconds) - self.shortfall
        self.shortfall = timedelta(0)


def test_waiting_for_an_instant_repeats_a_sleep_that_returned_early():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = _Clock(start, shortfall=timedelta(milliseconds=2))

    reached = wait_until(start + timedelta(seconds=3), now=clock.now, sleep=clock.sleep)

    assert reached >= start + timedelta(seconds=3)
    assert len(clock.sleeps) == 2 and clock.sleeps[1] == pytest.approx(0.002)


def test_an_instant_already_past_is_not_waited_for():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = _Clock(start)

    assert wait_until(start - timedelta(seconds=1), now=clock.now, sleep=clock.sleep) == start
    assert clock.sleeps == []


def test_an_instant_beyond_the_bound_is_refused_without_waiting():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = _Clock(start)

    with pytest.raises(AssertionError, match="refusing to wait"):
        wait_until(start + MAX_CLOCK_WAIT + timedelta(seconds=1), now=clock.now, sleep=clock.sleep)
    assert clock.sleeps == []


@pytest.mark.parametrize("activation_offset", [-2.0, -0.5, 0.0, 60.0, 3601.0])
def test_shared_lease_activation_is_within_the_independent_agreement_window(activation_offset):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    lease = {
        "id": "lease", "negotiation_id": "negotiation", "host_id": "example-host",
        "create_job_id": "create-job", "status": "active",
        "lease_start_utc": start.isoformat(), "lease_end_utc": end.isoformat(),
        "activated_at_utc": (start + timedelta(seconds=activation_offset)).isoformat(),
    }
    view = SimpleNamespace(deal_field="negotiation_id", deal_value="negotiation",
                           refresh=lambda: lease, is_ledger=True)
    driver = SimpleNamespace(lease_view=lambda state: view, reserved_resource_id="example-resource")
    state = ComputeDealState(domain_identity="vms.compute", negotiation_id="negotiation", settlement_ref="negotiation",
                             settlement_status="ready", fulfillment_id="fulfillment",
                             expected_host_id="example-host", agreement_start=start, agreement_end=end)
    if activation_offset < -1 or activation_offset >= 3600:
        with pytest.raises(AssertionError):
            Stage09c_LeaseRecorded().test_09c_provisioning_lease_recorded(driver, state)
    else:
        Stage09c_LeaseRecorded().test_09c_provisioning_lease_recorded(driver, state)
        assert state.deal_lease is view
