"""A lost answer to the storefront's filing is recovered by adopting the one case.

The filer is the storefront's operator end, which records the end, begins
teardown and files a delivery-end case. A mediation rule drops the filing's
response after the double commits it, so the storefront's outcome is unknown and
its filing stays pending; with the rule deleted, the storefront's next servicing
step dispatches the filing again, and the dispute adapter reads the authority's
record and adopts the case it finds rather than filing a second. The
storefront's lifecycle read and the double's case listing each show exactly one
case, and the deal is released through the mock teardown gate.
"""

from __future__ import annotations

import logging

import pytest
from lane_double_controls import Rule

from tests.e2e.roles.helpers.compute_deal_stages import (
    Stage00_LifecycleHeld,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c_ProvisioningHealth,
    Stage00h_ProvisioningStorefrontLink,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.vms.dispute.stages import (
    DisputeStage01_HostedDealCommitted,
    cases,
    lifecycle_read,
    scenario_driver,
    servicing_step,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_LOST_FILING_HOST,
    E2E_DISPUTE_LOST_FILING_POOL_ID,
    E2E_DISPUTE_LOST_FILING_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.lifecycle_deal import Stage12c_CapacityReleasedOnce

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_dispute_lost_filing,
]

log = logging.getLogger(__name__)

RULE_ID = "vm-dispute-lost-filing"
REASON = "development hosted VM reclaim, filing answer lost"


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_LOST_FILING_HOST,
                           pool_id=E2E_DISPUTE_LOST_FILING_POOL_ID,
                           resource_id=E2E_DISPUTE_LOST_FILING_RESOURCE_ID)


@pytest.fixture(scope="module")
def operator_end() -> dict:
    """What the first operator end answered, for the stages after it."""
    return {}


class TestStage00_LifecycleHeld(Stage00_LifecycleHeld):
    pass


class TestStage00a_StorefrontHealth(Stage00a_StorefrontHealth):
    pass


class TestStage00b_RegistryReachable(Stage00b_RegistryReachable):
    pass


class TestStage00c_ProvisioningHealth(Stage00c_ProvisioningHealth):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage01_HostedDealCommitted(DisputeStage01_HostedDealCommitted):
    pass


class TestStage02_FilingAnswerDropped:
    def test_02_a_rule_drops_the_answer_to_the_deal_s_filing(self, lane_double_rules, dispute):
        require_state(dispute, "deal")
        view = lane_double_rules.install("mediation", Rule(
            rule_id=RULE_ID, drop_response_after_commit=True,
            match={"operation": "file", "transaction": dispute.deal.transaction},
        ))
        assert view.matched == 0, view
        log.info("[02] Rule %s drops the answer to transaction %s's filing",
                 RULE_ID, dispute.deal.transaction)


class TestStage02b_ArmTeardownGate:
    def test_02b_the_mock_teardown_gate_is_armed(self, deal_driver, dispute):
        """The teardown the operator end begins is held at the mock gate until
        the release stage opens it."""
        require_state(dispute, "deal")
        deal_driver.arm_teardown_gate()


class TestStage03_OperatorEndLosesItsAnswer:
    def test_03_the_operator_end_records_the_end_and_its_filing_is_unknown(
        self, storefront_admin_client, lane_double_rules, dispute, operator_end,
    ):
        """The operator end records the end and begins teardown; the double
        commits the filing but its answer is lost, so the outcome is unknown."""
        assert lane_double_rules.view("mediation", RULE_ID).matched == 0, "the rule is not installed"
        first = storefront_admin_client.admin_interrupt_deal(dispute.deal.negotiation_id,
                                                             reason=REASON)
        assert first["settlement_action"] == "delivery_end_filing", first
        assert first["lifecycle_outcome"]["status"] == "unknown", first
        assert first["delivery"]["recorded_end"], first
        assert first["delivery"]["progress"] == "tearing_down", first
        assert lane_double_rules.view("mediation", RULE_ID).matched == 1
        operator_end.update(first)
        log.info("[03] Operator end recorded; its filing's answer was lost")


class TestStage04_RuleDeleted:
    def test_04_the_drop_rule_is_deleted(self, lane_double_rules, operator_end):
        assert operator_end, "the operator end did not run"
        lane_double_rules.delete("mediation", RULE_ID)
        assert all(view.rule.rule_id != RULE_ID
                   for view in lane_double_rules.controls["mediation"].rules().rules)


class TestStage05_ServicingAdoptsTheCase:
    def test_05_the_servicing_retry_adopts_the_one_filed_case(
        self, storefront_admin_client, lane_double_rules, dispute, operator_end,
    ):
        """The storefront's servicing dispatches its pending filing again; the
        dispute adapter reads the authority's record and adopts the case it
        committed, filing no second, and the end stays as recorded."""
        assert operator_end, "the operator end did not run"
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        (filing,) = view.filings
        assert filing.outcome.status == "accepted" and filing.outcome.filing is not None, view
        (case,) = cases(lane_double_rules, dispute.deal.transaction)
        assert case.case_ref == filing.outcome.filing.case_ref, case
        assert view.delivery.recorded_end is not None, view
        assert view.delivery.recorded_end.model_dump(mode="json") == (
            operator_end["delivery"]["recorded_end"]), view
        dispute.case_refs.append(case.case_ref)
        log.info("[05] The servicing retry adopted case %s", case.case_ref)


class TestStage06_OneCase:
    def test_06_the_storefront_and_the_double_each_show_one_case(
        self, storefront_admin_client, lane_double_rules, deal_state, dispute,
    ):
        require_state(dispute, "case_refs")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.authority.outcome.status == "accepted", view
        assert [case.case_ref for case in view.authority.cases] == dispute.case_refs, view
        assert [case.case_ref for case in cases(lane_double_rules, dispute.deal.transaction)] == (
            dispute.case_refs)
        assert view.delivery.progress == "tearing_down", view
        assert view.delivery.recorded_end is not None and view.delivery.site_reports, view
        purchase = deal_state.lifecycle_purchase
        purchase.receipt = {"selected_end": view.delivery.recorded_end.model_dump(mode="json")}
        purchase.reports = [item.model_dump(mode="json") for item in view.delivery.site_reports]
        log.info("[06] One case, %s, at the storefront and the double", dispute.case_refs[0])


class TestStage07_CapacityReleasedOnce(Stage12c_CapacityReleasedOnce):
    pass
