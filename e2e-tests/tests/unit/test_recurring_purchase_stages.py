"""A recurring purchase's stage set is declared, ordered, and handed its inputs.

Read from source rather than collected, so a scenario module is checked without
its lane's settings or services. Each recurring purchase module is one row of
``RECURRING_PURCHASES``; a lane that runs one adds its row.

A recurring purchase declares the shared stages it runs — the canonical deal's
readiness, delivery and teardown stages with the mock gates around them, the
purchase stages, and the stages of ``recurring_purchase_stages.py`` — once
each, in one order, with an empty body, and inserts only its own listing stage
and its stage closing the listing between them. A stage closing the listing
that a domain shares between its scenarios is read from its own module, so the
handoff check sees what it writes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.unit.stage_sources import (
    base_names,
    class_named,
    classes,
    domain_stages,
    fields,
    is_stage,
    run_order,
    tree,
)

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
HELPERS = ROLES / "helpers"
STATE = "deal_state"
COMPUTE_TREE = tree(HELPERS / "compute_deal_stages.py")
PURCHASE_TREE = tree(HELPERS / "buyer_purchase_stages.py")
RECURRING_TREE = tree(HELPERS / "recurring_purchase_stages.py")
COMPUTE_STAGES = [node for node in classes(COMPUTE_TREE) if is_stage(node)]
PURCHASE_STAGES = [node for node in classes(PURCHASE_TREE) if is_stage(node)]
RECURRING_STAGES = [node for node in classes(RECURRING_TREE) if is_stage(node)]
SHARED = [*COMPUTE_STAGES, *PURCHASE_STAGES, *RECURRING_STAGES]
SHARED_NAMES = {node.name for node in SHARED}
#: Domain-own stages defined outside a scenario module, which a scenario
#: subclasses with an empty body; read from their own source for the handoff.
DOMAIN_STAGES = [
    node for node in classes(tree(ROLES / "scenarios" / "bare_metal" / "publication_stages.py"))
    if is_stage(node)
]
#: The domain's identity and the other fields a scenario's state is built
#: with, which a stage may read without any stage writing them.
DOMAIN_DEAL_FIELDS = fields(class_named(tree(HELPERS / "domain_deal.py"), "DomainDealState"))
#: Every field a recurring purchase's state declares, through its bases.
STATE_FIELDS = (
    DOMAIN_DEAL_FIELDS
    | fields(class_named(COMPUTE_TREE, "ComputeDealState"))
    | fields(class_named(PURCHASE_TREE, "PurchaseState"))
    | fields(class_named(RECURRING_TREE, "RecurringPurchaseState"))
)

RECURRING_PURCHASES = (
    ROLES / "scenarios" / "vms" / "test_vm_recurring_purchase.py",
    ROLES / "scenarios" / "bare_metal" / "test_bare_metal_recurring_purchase.py",
)

#: The shared stages a recurring purchase declares, in run order: the canonical
#: deal's readiness, a mock lane's mode check among them; the purchase through
#: its correlation, the create gate armed before the buy and released after
#: it, and the mandate; delivery, the rate start and the purchase command's
#: end; and the buyer's end inside the teardown gate, the teardown's
#: completion and the payer's balance.
EXPECTED_ORDER = [
    "Stage00_LifecycleHeld",
    "Stage00a_StorefrontHealth",
    "Stage00b_RegistryReachable",
    "Stage00c_ProvisioningHealth",
    "Stage00c2_ProvisioningContractPins",
    "Stage00e_ProvisioningMockMode",
    "Stage00f1_ExecutorHostRegistry",
    "Stage00h_ProvisioningStorefrontLink",
    "Purchase01_PayerBalanceBefore",
    "Purchase02_ListingDiscovered",
    "Stage07a_ArmCreateGate",
    "Purchase03_Bought",
    "Purchase04_PurchaseCorrelated",
    "Stage08b2_ReleaseCreateGateAndDrain",
    "Recurring04_MandateApproved",
    "Stage09a_FulfillmentConvergesToActive",
    "Stage09b_SettlementReadyAndCredentials",
    "Stage09c_LeaseRecorded",
    "Recurring05_RateStartedAfterActivation",
    "Purchase09_PurchaseRunEnded",
    "Recurring06_AcceptedMoneyShown",
    "Stage09c2_ArmTeardownGate",
    "Recurring07_BuyerEnds",
    "Stage11a2_ReleaseTeardownGateAndDrain",
    "Stage11b_TeardownCompletion",
    "Recurring08_PayerChargedOnePeriod",
]


def recurring_faults(scenario: Path) -> list[str]:
    """What a recurring purchase module declares against the stage set's rules."""
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
    if declared != EXPECTED_ORDER:
        faults.append(f"declares the shared stages {declared}; expected {EXPECTED_ORDER}")
    return faults


def handoff_faults(scenario: Path) -> list[str]:
    """Each field a stage requires or reads that no earlier stage of the module
    writes, and each field a stage writes or requires that the state does not
    declare: ``require_state`` reads through ``getattr``, so an undeclared
    field skips its dependents forever."""
    faults = []
    written: set[str] = set()
    for name, use in run_order(scenario, [*SHARED, *DOMAIN_STAGES], state=STATE):
        undeclared = (use.written | use.required) - STATE_FIELDS
        if undeclared:
            faults.append(f"{name} uses undeclared fields {sorted(undeclared)}")
        # A stage may read back what it wrote itself, as a correlation does.
        missing = (use.required - written) | (use.read - written - use.written - DOMAIN_DEAL_FIELDS)
        if missing:
            faults.append(f"{name} reads {sorted(missing)} before any stage writes them")
        written |= use.written
    return faults


def test_the_recurring_stages_are_not_collected_where_they_are_defined():
    assert RECURRING_STAGES, "the recurring purchase module defines no stage"
    collected = [node.name for node in classes(RECURRING_TREE) if node.name.startswith("Test")]
    assert collected == [], collected


def test_the_recurring_state_extends_the_purchase_state():
    assert "PurchaseState" in base_names(class_named(RECURRING_TREE, "RecurringPurchaseState"))


def test_every_recurring_stage_is_in_the_order():
    """A recurring stage no order names is one no recurring purchase runs."""
    assert {node.name for node in RECURRING_STAGES} <= set(EXPECTED_ORDER)


@pytest.mark.parametrize("scenario", RECURRING_PURCHASES, ids=lambda path: path.stem)
def test_a_recurring_purchase_declares_the_shared_stages_once_in_order(scenario: Path):
    assert recurring_faults(scenario) == []


@pytest.mark.parametrize("scenario", RECURRING_PURCHASES, ids=lambda path: path.stem)
def test_each_stage_is_handed_what_it_reads_by_an_earlier_stage(scenario: Path):
    assert handoff_faults(scenario) == []


def test_a_recurring_stage_out_of_order_is_refused(tmp_path):
    names = list(EXPECTED_ORDER)
    started = names.index("Recurring05_RateStartedAfterActivation")
    names[started], names[started + 1] = names[started + 1], names[started]
    scenario = tmp_path / "test_constructed_recurring_purchase.py"
    scenario.write_text("\n\n".join(f"class Test{name}({name}):\n    pass\n" for name in names))
    (fault,) = recurring_faults(scenario)
    assert fault.startswith("declares the shared stages"), fault


def test_a_stage_reading_what_no_earlier_stage_wrote_is_refused(tmp_path):
    scenario = tmp_path / "test_constructed_recurring_purchase.py"
    scenario.write_text(
        "class TestRecurring05_RateStartedAfterActivation("
        "Recurring05_RateStartedAfterActivation):\n    pass\n"
    )
    (fault,) = handoff_faults(scenario)
    assert fault.startswith("TestRecurring05_RateStartedAfterActivation reads"), fault
