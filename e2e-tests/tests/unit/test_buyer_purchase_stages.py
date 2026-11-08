"""A buyer purchase's stage set is declared, ordered, and ended once.

Read from source rather than collected, so a scenario module is checked without
its lane's settings or services. Each scenario buying through the shipped buyer
is one row of ``PURCHASES``; a scenario that buys this way adds its row.

A purchase declares the shared stages it runs — the purchase stages of
``buyer_purchase_stages.py`` and the canonical deal's stages it shares from
``compute_deal_stages.py`` — once each, in one order, with an empty body, and
inserts only its own stages between them. Its lease ends one way: by the buyer's
teardown, or by the canonical deal's expiry stages, never both. A mock lane adds
the canonical deal's mock-lane stages around the purchase and its ending. That
the stages from fulfillment onwards receive their inputs from the purchase is
``test_compute_deal_stages.py``'s handoff check, where each purchase is a row
too.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.stage_sources import (
    base_names,
    class_named,
    classes,
    domain_stages,
    is_stage,
    tree,
)

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
PURCHASE_TREE = tree(ROLES / "helpers" / "buyer_purchase_stages.py")
COMPUTE_TREE = tree(ROLES / "helpers" / "compute_deal_stages.py")
PURCHASE_STAGES = [node for node in classes(PURCHASE_TREE) if is_stage(node)]
COMPUTE_STAGES = [node for node in classes(COMPUTE_TREE) if is_stage(node)]
SHARED_NAMES = {node.name for node in (*PURCHASE_STAGES, *COMPUTE_STAGES)}
MOCK_LANE_MARKER = "MockLaneStage"
MOCK_TEST_CLIENT = "provisioning_test_client"


#: The two endings a purchase's lease may end by, each a run of shared stages.
BUYER_TEARDOWN = ("Purchase10_BuyerTeardown",)
EXPIRY = (
    "Stage10a_LeaseExpirySetup",
    "Stage10b_LeaseCycleBeginsTeardown",
    "Stage11a_TeardownDispatch",
)


@dataclass(frozen=True)
class Purchase:
    name: str
    scenario: Path
    #: Whether the purchase delivers through the provisioning mock profile.
    mock: bool
    #: The ending its lease ends by.
    ending: tuple[str, ...]


PURCHASES = (
    Purchase(
        "bare_metal",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_payment_deal.py",
        mock=True,
        ending=BUYER_TEARDOWN,
    ),
    Purchase(
        "vms",
        ROLES / "scenarios" / "vms" / "test_vm_payment_purchase.py",
        mock=True,
        ending=EXPIRY,
    ),
    Purchase(
        "vms_qualification",
        ROLES / "scenarios" / "vms" / "test_vm_qualification.py",
        mock=False,
        ending=EXPIRY,
    ),
    Purchase(
        "bare_metal_qualification",
        ROLES / "scenarios" / "bare_metal" / "test_bare_metal_qualification.py",
        mock=False,
        ending=BUYER_TEARDOWN,
    ),
)


def expected_order(*, mock: bool, ending: tuple[str, ...]) -> list[str]:
    """The shared stages a purchase declares, in run order.

    The canonical deal's readiness, the purchase stages, the stages from
    fulfillment onwards, one ending, and teardown completion; a mock lane arms
    and releases each job's gate around the stage that dispatches it.
    """
    def gate(name: str) -> list[str]:
        return [name] if mock else []

    return [
        "Stage00_LifecycleHeld",
        "Stage00a_StorefrontHealth",
        "Stage00b_RegistryReachable",
        "Stage00c_ProvisioningHealth",
        "Stage00c2_ProvisioningContractPins",
        *gate("Stage00e_ProvisioningMockMode"),
        "Stage00f1_ExecutorHostRegistry",
        "Stage00h_ProvisioningStorefrontLink",
        "Purchase01_PayerBalanceBefore",
        "Purchase02_ListingDiscovered",
        *gate("Stage07a_ArmCreateGate"),
        "Purchase03_Bought",
        "Purchase04_PurchaseCorrelated",
        *gate("Stage08b2_ReleaseCreateGateAndDrain"),
        "Purchase05_PaymentRecordsChecked",
        "Stage09a_FulfillmentConvergesToActive",
        "Stage09b_SettlementReadyAndCredentials",
        "Stage09c_LeaseRecorded",
        "Purchase09_PurchaseRunEnded",
        *gate("Stage09c2_ArmTeardownGate"),
        *ending,
        *gate("Stage11a2_ReleaseTeardownGateAndDrain"),
        "Stage11b_TeardownCompletion",
    ]


def purchase_faults(
    scenario: Path, *, mock: bool, ending: tuple[str, ...] | None = None,
) -> list[str]:
    """What a purchase module declares against the stage set's rules: with
    ``ending``, the ending its lease must end by too."""
    faults = []
    declared = []
    for node in domain_stages(scenario):
        shared = [name for name in base_names(node) if name in SHARED_NAMES]
        if not shared:
            continue
        (base,) = shared
        if node.name != "Test" + base:
            faults.append(f"{base} is declared as {node.name}")
        if not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)):
            faults.append(f"{node.name} replaces the body of {base}")
        declared.append(base)
    endings = [ending for ending in (BUYER_TEARDOWN, EXPIRY) if set(ending) & set(declared)]
    if len(endings) != 1:
        faults.append(
            "runs both the buyer-teardown ending and the expiry stages" if endings
            else "runs no ending"
        )
        return faults
    if ending is not None and endings[0] != ending:
        faults.append(f"ends by {list(endings[0])}; its lease ends by {list(ending)}")
        return faults
    expected = expected_order(mock=mock, ending=endings[0])
    if declared != expected:
        faults.append(f"declares the shared stages {declared}; expected {expected}")
    return faults


def test_the_purchase_stages_are_not_collected_where_they_are_defined():
    assert PURCHASE_STAGES, "the purchase module defines no stage"
    collected = [node.name for node in classes(PURCHASE_TREE) if node.name.startswith("Test")]
    assert collected == [], collected


def test_the_purchase_state_extends_the_compute_state():
    assert "ComputeDealState" in base_names(class_named(PURCHASE_TREE, "PurchaseState"))


def test_every_purchase_stage_is_in_the_purchase_order():
    """A purchase stage no order names is one no purchase runs."""
    ordered = set(expected_order(mock=True, ending=BUYER_TEARDOWN))
    assert {node.name for node in PURCHASE_STAGES} <= ordered


def test_no_purchase_stage_touches_a_mock_gate():
    """A purchase stage runs in a real lane too, whose driver has no gates."""
    gates = {
        item.name for item in class_named(COMPUTE_TREE, "MockGates").body
        if isinstance(item, ast.FunctionDef)
    } | {MOCK_TEST_CLIENT, "MockGates", MOCK_LANE_MARKER}
    def names(stage: ast.ClassDef) -> set[str]:
        found = set()
        for node in ast.walk(stage):
            if isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.arg):
                found.add(node.arg)
            elif isinstance(node, ast.Name):
                found.add(node.id)
        return found

    touching = {stage.name: sorted(names(stage) & gates) for stage in PURCHASE_STAGES}
    assert {name: used for name, used in touching.items() if used} == {}


def test_each_purchase_stage_takes_the_purchase_driver():
    wrong = {}
    for stage in PURCHASE_STAGES:
        for item in stage.body:
            if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                for arg in item.args.args:
                    if arg.arg == "deal_driver" and not (
                        isinstance(arg.annotation, ast.Name)
                        and arg.annotation.id == "PurchaseDriver"
                    ):
                        wrong[stage.name] = ast.unparse(arg.annotation) if arg.annotation else None
    assert wrong == {}, wrong


@pytest.mark.parametrize("purchase", PURCHASES, ids=lambda purchase: purchase.name)
def test_a_purchase_declares_the_shared_stages_once_in_order_with_its_ending(purchase: Purchase):
    assert purchase_faults(purchase.scenario, mock=purchase.mock, ending=purchase.ending) == []


def _constructed(names: list[str], *, replaced: str | None = None, own: str = "") -> str:
    lines = []
    for name in names:
        body = "    def test_x(self):\n        pass\n" if name == replaced else "    pass\n"
        lines.append(f"class Test{name}({name}):\n{body}")
        if name == "Purchase02_ListingDiscovered" and own:
            lines.append(own)
    return "\n\n".join(lines)


_OWN_STAGE = "class TestStage03_OwnListing:\n    def test_03(self, deal_state):\n        pass\n"


@pytest.mark.parametrize(
    ("names", "replaced", "faults"),
    [
        (expected_order(mock=True, ending=BUYER_TEARDOWN), None, []),
        (expected_order(mock=True, ending=EXPIRY), None, []),
        (
            expected_order(mock=True, ending=BUYER_TEARDOWN),
            "Stage09b_SettlementReadyAndCredentials",
            ["TestStage09b_SettlementReadyAndCredentials replaces the body of "
             "Stage09b_SettlementReadyAndCredentials"],
        ),
        (
            expected_order(mock=True, ending=(*BUYER_TEARDOWN, *EXPIRY)),
            None,
            ["runs both the buyer-teardown ending and the expiry stages"],
        ),
    ],
    ids=["buyer teardown", "expiry", "a replaced body", "both endings"],
)
def test_a_constructed_purchase_is_held_to_the_rules(tmp_path, names, replaced, faults):
    scenario = tmp_path / "test_constructed_purchase.py"
    scenario.write_text(_constructed(names, replaced=replaced, own=_OWN_STAGE))
    assert purchase_faults(scenario, mock=True) == faults


def test_a_purchase_ending_other_than_its_lease_ends_is_refused(tmp_path):
    scenario = tmp_path / "test_constructed_purchase.py"
    scenario.write_text(_constructed(expected_order(mock=True, ending=BUYER_TEARDOWN)))
    assert purchase_faults(scenario, mock=True, ending=EXPIRY) == [
        f"ends by {list(BUYER_TEARDOWN)}; its lease ends by {list(EXPIRY)}"
    ]


def test_a_shared_stage_out_of_order_is_refused(tmp_path):
    names = expected_order(mock=False, ending=BUYER_TEARDOWN)
    bought = names.index("Purchase03_Bought")
    names[bought], names[bought + 1] = names[bought + 1], names[bought]
    scenario = tmp_path / "test_constructed_purchase.py"
    scenario.write_text(_constructed(names))
    (fault,) = purchase_faults(scenario, mock=False)
    assert fault.startswith("declares the shared stages"), fault
