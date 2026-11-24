"""An operator's partial reverse leaves a hosted VM deal delivering.

The buyer files on its delivering deal with no rule installed, so the mediation
double holds the part and rules nothing; a servicing step answers the case as
respondent, with an append of the seller's evidence; the
operator decides a partial reverse with no delivery end, closing the case; and a
servicing step finds delivery still active, no end recorded. The deal is then
ended by lease expiry, which files nothing.
"""

from __future__ import annotations

import logging

import pytest
from lane_double_controls import Ruling

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
    cases,
    lifecycle_read,
    scenario_driver,
    servicing_step,
    snapshot_part,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_DISCOUNT_HOST,
    E2E_DISPUTE_DISCOUNT_POOL_ID,
    E2E_DISPUTE_DISCOUNT_RESOURCE_ID,
)

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_dispute_discount,
]

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_DISCOUNT_HOST,
                           pool_id=E2E_DISPUTE_DISCOUNT_POOL_ID,
                           resource_id=E2E_DISPUTE_DISCOUNT_RESOURCE_ID)


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
    def test_02_the_buyer_s_filing_is_held_and_unruled(
        self, payments_config, mediation_target, lane_double_rules, dispute,
    ):
        """With no rule, the filing is accepted with each part held and the
        case stays open."""
        require_state(dispute, "deal")
        deal = dispute.deal
        outcome = file_as_buyer(mediation_target, negotiation_id=deal.negotiation_id,
                                transaction=deal.transaction, agreement=deal.agreement,
                                store=dispute.buyer_store)
        assert outcome.status == "accepted" and outcome.filing is not None, outcome
        assert outcome.filing.parts and all(
            part.status == "held" and part.extension_ref for part in outcome.filing.parts), outcome
        dispute.case_refs.append(outcome.filing.case_ref)
        (case,) = cases(lane_double_rules, deal.transaction)
        assert case.state == "open", case
        log.info("[02] Case %s filed by the buyer and held", case.case_ref)


class TestStage03_StorefrontAnswers:
    def test_03_a_servicing_step_answers_the_case_as_respondent(
        self, storefront_admin_client, dispute,
    ):
        """The storefront's servicing answers the buyer's case on the record:
        one append by the seller's account."""
        require_state(dispute, "case_refs")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        seller = str(payment_setting("SELLER_ACCOUNT"))
        answers = [event for event in view.authority.disputes
                   if event.kind == "appended" and event.case_ref == dispute.case_refs[0]]
        assert [event.actor for event in answers] == [seller], view
        assert view.delivery.progress == "active", view
        log.info("[03] The storefront answered case %s", dispute.case_refs[0])


class TestStage04_OperatorDiscount:
    def test_04_an_operator_s_partial_reverse_lands_and_closes_the_case(
        self, payments_config, lane_double_rules, dispute,
    ):
        """The operator rules a reverse of a quarter of part 0 with no delivery
        end, closing the case: the amount reversed, the extension lifted."""
        require_state(dispute, "case_refs")
        deal = dispute.deal
        amount = int(snapshot_part(payments_config, deal.transaction)["gross"]) // 4
        case = lane_double_rules.controls["mediation"].decide(dispute.case_refs[0], Ruling(
            basis="operator", delivery_end=False, close=True,
            effects=[{"kind": "reverse", "part": 0, "amount": str(amount)}],
        ))
        assert case.state == "closed", case
        dispute.amounts.append(amount)
        part = snapshot_part(payments_config, deal.transaction)
        assert int(part["reversed"]) == amount, part
        assert part["extensions"] == [], part
        log.info("[04] Operator reversed %s on case %s and closed it", amount, case.case_ref)


class TestStage05_DeliveryRunsOn:
    def test_05_a_servicing_step_finds_the_deal_still_delivering(
        self, storefront_admin_client, dispute,
    ):
        """The storefront reads the closed case and records no end: delivery
        stays active."""
        require_state(dispute, "amounts")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.delivery.progress == "active", view
        assert view.delivery.recorded_end is None, view
        assert [(case.case_ref, case.state) for case in view.authority.cases] == [
            (dispute.case_refs[0], "closed")], view
        log.info("[05] Deal %s still delivering after its discount", dispute.deal.negotiation_id)


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
