"""Recurring purchases', rate servicing rows', the watchdog cases' and the
rate-dispute rows' stage sets are declared, ordered, and handed their inputs.

Read from source rather than collected, so a scenario module is checked without
its lane's settings or services. Each module is one entry of ``ORDERS``, with
the shared stages it declares in run order; a lane that runs another adds its
entry.

A recurring purchase, each rate servicing row, each watchdog module and each
rate-dispute row declares the shared stages it runs — the canonical deal's
readiness, delivery and teardown stages with the mock gates around them, the
purchase stages, the stages of ``recurring_purchase_stages.py`` and, for a rate
servicing row, those of ``rate_servicing_stages.py``, for a watchdog module those
of ``rate_watchdog_stages.py`` — once each, in one order, with an empty body, and
inserts only its listing stage, its stage closing the listing and, for a
rate-dispute row, its domain's dispute stages between them. A module setting
lane time past its part's first reservation, in a shared stage or its own,
declares the payments double's reservation before that stage, and one that sets
none declares no reservation.
A domain stage defined outside a scenario module, which a scenario subclasses,
is read from its own module, so the handoff check sees what it writes.
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
SCENARIOS = ROLES / "scenarios"
STATE = "deal_state"
COMPUTE_TREE = tree(HELPERS / "compute_deal_stages.py")
PURCHASE_TREE = tree(HELPERS / "buyer_purchase_stages.py")
RECURRING_TREE = tree(HELPERS / "recurring_purchase_stages.py")
RATE_TREE = tree(HELPERS / "rate_servicing_stages.py")
WATCHDOG_TREE = tree(HELPERS / "rate_watchdog_stages.py")
COMPUTE_STAGES = [node for node in classes(COMPUTE_TREE) if is_stage(node)]
PURCHASE_STAGES = [node for node in classes(PURCHASE_TREE) if is_stage(node)]
RECURRING_STAGES = [node for node in classes(RECURRING_TREE) if is_stage(node)]
RATE_STAGES = [node for node in classes(RATE_TREE) if is_stage(node)]
WATCHDOG_STAGES = [node for node in classes(WATCHDOG_TREE) if is_stage(node)]
SHARED = [*COMPUTE_STAGES, *PURCHASE_STAGES, *RECURRING_STAGES, *RATE_STAGES, *WATCHDOG_STAGES]
SHARED_NAMES = {node.name for node in SHARED}
#: Domain-own stages defined outside a scenario module, which a scenario
#: subclasses with an empty body; read from their own source for the handoff.
DOMAIN_STAGES = [
    node
    for path in (
        SCENARIOS / "bare_metal" / "publication_stages.py",
        SCENARIOS / "vms" / "rate_servicing" / "stages.py",
        SCENARIOS / "bare_metal" / "rate_servicing" / "stages.py",
        SCENARIOS / "vms" / "rate_dispute" / "stages.py",
    )
    for node in classes(tree(path))
    if is_stage(node)
]
RATE_DISPUTE_TREE = tree(SCENARIOS / "vms" / "rate_dispute" / "stages.py")
#: The domain's identity and the other fields a scenario's state is built
#: with, which a stage may read without any stage writing them.
DOMAIN_DEAL_FIELDS = fields(class_named(tree(HELPERS / "domain_deal.py"), "DomainDealState"))
#: Every field a recurring purchase's, a row's or a watchdog module's state
#: declares, through its bases.
STATE_FIELDS = (
    DOMAIN_DEAL_FIELDS
    | fields(class_named(COMPUTE_TREE, "ComputeDealState"))
    | fields(class_named(PURCHASE_TREE, "PurchaseState"))
    | fields(class_named(RECURRING_TREE, "RecurringPurchaseState"))
    | fields(class_named(RATE_TREE, "RateServicingState"))
    | fields(class_named(WATCHDOG_TREE, "RateWatchdogState"))
    | fields(class_named(RATE_DISPUTE_TREE, "RateDisputeState"))
)

#: The canonical deal's readiness, a mock lane's mode check among them.
READINESS = [
    "Stage00_LifecycleHeld",
    "Stage00a_StorefrontHealth",
    "Stage00b_RegistryReachable",
    "Stage00c_ProvisioningHealth",
    "Stage00c2_ProvisioningContractPins",
    "Stage00e_ProvisioningMockMode",
    "Stage00f1_ExecutorHostRegistry",
    "Stage00h_ProvisioningStorefrontLink",
]
#: The purchase through its correlation, the create gate armed before the buy
#: and released after it, and the mandate.
PURCHASE = [
    "Purchase01_PayerBalanceBefore",
    "Purchase02_ListingDiscovered",
    "Stage07a_ArmCreateGate",
    "Purchase03_Bought",
    "Purchase04_PurchaseCorrelated",
    "Stage08b2_ReleaseCreateGateAndDrain",
    "Recurring04_MandateApproved",
]
#: Convergence, delivery recovery at the Agreement's start, delivery, the rate
#: start, the purchase command's end and its accepted money, then the teardown
#: gate armed before the ending.
DELIVERY = [
    "Stage09a_FulfillmentConvergesToActive",
    "Recurring05_DeliveryRecoveredAtTheStart",
    "Stage09b_SettlementReadyAndCredentials",
    "Stage09c_LeaseRecorded",
    "Recurring06_RateStartedAfterActivation",
    "Purchase09_PurchaseRunEnded",
    "Recurring07_AcceptedMoneyShown",
    "Stage09c2_ArmTeardownGate",
]
#: The teardown gate released, and the teardown completed.
TEARDOWN = ["Stage11a2_ReleaseTeardownGateAndDrain", "Stage11b_TeardownCompletion"]

#: A recurring purchase: the buyer's end inside the teardown gate, the
#: teardown, the payer's balance and the seller's list.
RECURRING_ORDER = [
    *READINESS, *PURCHASE, *DELIVERY, "Recurring08_BuyerEnds", *TEARDOWN,
    "Recurring09_PayerChargedOnePeriod", "Recurring10_SellerListsTheDealEnded",
]
#: The payments double's further reservation, which a row declares before the
#: stage setting lane time past the part's first reservation.
RESERVATION = "Reservation06_ThroughTheAgreementsEnd"
#: Funds running out: the second payer funded before the purchase, the part
#: reserved as far as the balance pays, the deal stopped at its funded
#: boundary, and the buyer told after the teardown.
FUNDS_EXHAUSTED_ORDER = [
    *READINESS, "Exhaustion00_PayerFundedOnePeriodBeyondTheFirstReservation", *PURCHASE,
    *DELIVERY, RESERVATION, "Exhaustion07_FundsRunOut", *TEARDOWN,
    "Exhaustion08_BuyerToldANewDealIsNeeded",
]
#: A spot seller's preemption: the notice held, the stop taking effect inside
#: the part's first reservation, and the payer's return after the teardown.
PREEMPTION_ORDER = [
    *READINESS, *PURCHASE, *DELIVERY, "Preemption07_SellerNoticeHeld",
    "Preemption08_StopTakesEffect", *TEARDOWN, "Preemption09_UnstartedPeriodReturned",
]
#: The maximum term: the part reserved through the Agreement's end, ending
#: there, and the buyer's read after the teardown.
MAXIMUM_TERM_ORDER = [
    *READINESS, *PURCHASE, *DELIVERY, RESERVATION, "MaximumTerm07_TermEnds", *TEARDOWN,
    "MaximumTerm08_NotFundsRunningOut",
]
#: The watchdog's cases on one deal, delivered while the in-process ``buy``
#: waits at the harness's gate: monitored from available and into the first
#: period, killed and stale, resumed, then, inside the teardown gate, the access
#: lost, and the teardown. No instant passes the part's first reservation, and
#: the purchase command ends only at the watchdog's stop, so the module declares
#: neither the reservation nor the purchase command's end and accepted money.
WATCHDOG_ORDER = [
    *READINESS, *PURCHASE,
    "Stage09a_FulfillmentConvergesToActive",
    "Recurring05_DeliveryRecoveredAtTheStart",
    "Stage09b_SettlementReadyAndCredentials",
    "Stage09c_LeaseRecorded",
    "Recurring06_RateStartedAfterActivation",
    "Watchdog01_MonitoredFromAvailable",
    "Watchdog02_IntoTheFirstPeriod",
    "Watchdog03_KilledCommandGoesStale",
    "Watchdog04_ResumedRunMonitored",
    "Stage09c2_ArmTeardownGate",
    "Watchdog05_AccessLostStopsOnce",
    *TEARDOWN,
]
#: A rate-dispute row: the deal delivered, the teardown gate armed, its domain's
#: dispute stages, then the teardown. The seller's filing reserves the part
#: before its ruling falls past the first reservation; the buyer's contested
#: case is ruled inside it.
SELLER_FILING_ORDER = [*READINESS, *PURCHASE, *DELIVERY, RESERVATION, *TEARDOWN]
CONTESTED_CASE_ORDER = [*READINESS, *PURCHASE, *DELIVERY, *TEARDOWN]
#: Each stage, shared or a domain's own, that sets lane time past the part's
#: first reservation, which the reservation must precede in its module.
SETS_PAST_THE_FIRST_RESERVATION = (
    "Exhaustion07_FundsRunOut", "MaximumTerm07_TermEnds", "SellerFiling10_RulingApplied",
)

ORDERS = {
    SCENARIOS / "vms" / "test_vm_recurring_purchase.py": RECURRING_ORDER,
    SCENARIOS / "bare_metal" / "test_bare_metal_recurring_purchase.py": RECURRING_ORDER,
    **{
        SCENARIOS / domain / "rate_servicing" / module: order
        for domain in ("vms", "bare_metal")
        for module, order in (
            ("test_funds_exhausted.py", FUNDS_EXHAUSTED_ORDER),
            ("test_preemption.py", PREEMPTION_ORDER),
            ("test_maximum_term.py", MAXIMUM_TERM_ORDER),
        )
    },
    **{
        SCENARIOS / domain / "rate_watchdog" / "test_rate_watchdog.py": WATCHDOG_ORDER
        for domain in ("vms", "bare_metal")
    },
    SCENARIOS / "vms" / "rate_dispute" / "test_seller_filing.py": SELLER_FILING_ORDER,
    SCENARIOS / "vms" / "rate_dispute" / "test_buyer_contested_case.py": CONTESTED_CASE_ORDER,
}


def _label(path: Path) -> str:
    nested = path.parent.name in ("rate_servicing", "rate_watchdog", "rate_dispute")
    domain = path.parent.parent.name if nested else path.parent.name
    return f"{domain}/{path.stem}"


def order_faults(scenario: Path, expected: list[str]) -> list[str]:
    """What a module declares against the stage set's rules and its order."""
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
    if declared != expected:
        faults.append(f"declares the shared stages {declared}; expected {expected}")
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


def test_the_recurring_rate_and_watchdog_stages_are_not_collected_where_they_are_defined():
    assert RECURRING_STAGES and RATE_STAGES and WATCHDOG_STAGES
    collected = [node.name
                 for node in classes(RECURRING_TREE) + classes(RATE_TREE) + classes(WATCHDOG_TREE)
                 if node.name.startswith("Test")]
    assert collected == [], collected


def test_the_recurring_state_extends_the_purchase_state():
    assert "PurchaseState" in base_names(class_named(RECURRING_TREE, "RecurringPurchaseState"))
    assert "RecurringPurchaseState" in base_names(class_named(RATE_TREE, "RateServicingState"))
    assert "RecurringPurchaseState" in base_names(class_named(WATCHDOG_TREE, "RateWatchdogState"))


def test_every_recurring_rate_and_watchdog_stage_is_in_an_order():
    """A stage no order names is one no module runs."""
    ordered = {name for order in ORDERS.values() for name in order}
    assert {node.name for node in RECURRING_STAGES + RATE_STAGES + WATCHDOG_STAGES} <= ordered


@pytest.mark.parametrize("scenario", ORDERS, ids=_label)
def test_a_module_declares_the_shared_stages_once_in_order(scenario: Path):
    assert order_faults(scenario, ORDERS[scenario]) == []


@pytest.mark.parametrize("scenario", ORDERS, ids=_label)
def test_each_stage_is_handed_what_it_reads_by_an_earlier_stage(scenario: Path):
    assert handoff_faults(scenario) == []


def run_names(scenario: Path) -> list[str]:
    """Every stage the module declares, in run order, each by the stage whose
    body it runs: a shared or domain stage it subclasses, else its own."""
    names = []
    for node in domain_stages(scenario):
        bases = base_names(node)
        names.append(bases[0] if bases else node.name)
    return names


@pytest.mark.parametrize("scenario", ORDERS, ids=_label)
def test_a_row_reserves_before_it_sets_lane_time_past_the_first_reservation(scenario: Path):
    """A row's stage setting lane time past the part's first reservation, shared
    or its domain's own, comes after the double's reservation, so the part is
    still funded there; a module with no such stage declares no reservation."""
    order = run_names(scenario)
    setters = [order.index(name) for name in SETS_PAST_THE_FIRST_RESERVATION if name in order]
    if not setters:
        assert RESERVATION not in order
        return
    assert RESERVATION in order and order.index(RESERVATION) < min(setters), order


def test_a_recurring_stage_out_of_order_is_refused(tmp_path):
    names = list(RECURRING_ORDER)
    started = names.index("Recurring06_RateStartedAfterActivation")
    names[started], names[started + 1] = names[started + 1], names[started]
    scenario = tmp_path / "test_constructed_recurring_purchase.py"
    scenario.write_text("\n\n".join(f"class Test{name}({name}):\n    pass\n" for name in names))
    (fault,) = order_faults(scenario, RECURRING_ORDER)
    assert fault.startswith("declares the shared stages"), fault


def test_a_stage_reading_what_no_earlier_stage_wrote_is_refused(tmp_path):
    scenario = tmp_path / "test_constructed_recurring_purchase.py"
    scenario.write_text(
        "class TestRecurring06_RateStartedAfterActivation("
        "Recurring06_RateStartedAfterActivation):\n    pass\n"
    )
    (fault,) = handoff_faults(scenario)
    assert fault.startswith("TestRecurring06_RateStartedAfterActivation reads"), fault
