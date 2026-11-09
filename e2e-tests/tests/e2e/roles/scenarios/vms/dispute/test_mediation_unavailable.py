"""An unavailable mediation double leaves a delivering VM deal running.

The buyer files with no rule, and a servicing step answers the case, so the
authority already knows the deal's Agreement: a storefront's read of a record
the authority does not yet know is refused even when nothing is wrong. With
mediation *unavailable*, every API response abandoned, a servicing step reports
the authority unreachable while delivery stays active; with the outage removed,
the next step reads the authority, and the case, again. The deal is then ended
by lease expiry, which files nothing.
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
    Stage09c2_ArmTeardownGate,
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a2_ReleaseTeardownGateAndDrain,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.mediation import file_as_buyer
from tests.e2e.roles.helpers.payments import payment_setting
from tests.e2e.roles.scenarios.vms.dispute.stages import (
    DisputeStage01_HostedDealCommitted,
    DisputeStageZ_NoFurtherCase,
    lifecycle_read,
    scenario_driver,
    servicing_step,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_MEDIATION_UNAVAILABLE_HOST,
    E2E_DISPUTE_MEDIATION_UNAVAILABLE_POOL_ID,
    E2E_DISPUTE_MEDIATION_UNAVAILABLE_RESOURCE_ID,
)

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_dispute_mediation_unavailable,
]

log = logging.getLogger(__name__)

RULE_ID = "vm-dispute-mediation-unavailable"


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_MEDIATION_UNAVAILABLE_HOST,
                           pool_id=E2E_DISPUTE_MEDIATION_UNAVAILABLE_POOL_ID,
                           resource_id=E2E_DISPUTE_MEDIATION_UNAVAILABLE_RESOURCE_ID)


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


class TestStage02_BuyerFiles:
    def test_02_the_buyer_s_filing_is_held(self, mediation_target, dispute):
        require_state(dispute, "deal")
        deal = dispute.deal
        outcome = file_as_buyer(mediation_target, negotiation_id=deal.negotiation_id,
                                transaction=deal.transaction, agreement=deal.agreement,
                                store=dispute.buyer_store)
        assert outcome.status == "accepted" and outcome.filing is not None, outcome
        assert outcome.filing.parts and all(
            part.status == "held" for part in outcome.filing.parts), outcome
        dispute.case_refs.append(outcome.filing.case_ref)
        log.info("[02] Case %s filed by the buyer", outcome.filing.case_ref)


class TestStage03_StorefrontAnswers:
    def test_03_a_servicing_step_answers_the_case(self, storefront_admin_client, dispute):
        require_state(dispute, "case_refs")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.authority.outcome.status == "accepted", view
        assert [event.actor for event in view.authority.disputes
                if event.kind == "appended" and event.case_ref == dispute.case_refs[0]] == [
            str(payment_setting("SELLER_ACCOUNT"))], view
        log.info("[03] The storefront answered case %s", dispute.case_refs[0])


class TestStage04_MediationUnavailable:
    def test_04_the_mediation_double_becomes_unavailable(self, lane_double_rules, dispute):
        require_state(dispute, "case_refs")
        view = lane_double_rules.install("mediation", Rule(
            rule_id=RULE_ID, match={}, unavailable=True,
        ))
        assert view.matched == 0, view
        log.info("[04] The mediation double is unavailable")


class TestStage05_AuthorityUnreachable:
    def test_05_servicing_reports_the_authority_unreachable_and_delivery_runs_on(
        self, storefront_admin_client, lane_double_rules, dispute,
    ):
        """The storefront's dispute read fails at the transport, which the
        adapter reports as the authority unreachable, an unknown outcome;
        nothing ends delivery."""
        assert lane_double_rules.view("mediation", RULE_ID), "the outage is not installed"
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.authority.outcome.status == "unknown", view
        assert view.delivery.progress == "active", view
        assert view.delivery.recorded_end is None, view
        assert lane_double_rules.view("mediation", RULE_ID).matched >= 1
        log.info("[05] Authority reported %s while unavailable; delivery active",
                 view.authority.outcome.status)


class TestStage06_OutageRemoved:
    def test_06_the_outage_is_removed(self, lane_double_rules):
        lane_double_rules.delete("mediation", RULE_ID)
        assert all(view.rule.rule_id != RULE_ID
                   for view in lane_double_rules.controls["mediation"].rules().rules)


class TestStage07_AuthorityReadAgain:
    def test_07_the_next_servicing_step_reads_the_authority_again(
        self, storefront_admin_client, dispute,
    ):
        require_state(dispute, "case_refs")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.authority.outcome.status == "accepted", view
        assert [case.case_ref for case in view.authority.cases] == dispute.case_refs, view
        assert view.delivery.progress == "active", view
        log.info("[07] The authority read again: case %s", dispute.case_refs[0])


class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStageZ_NoFurtherCase(DisputeStageZ_NoFurtherCase):
    pass
