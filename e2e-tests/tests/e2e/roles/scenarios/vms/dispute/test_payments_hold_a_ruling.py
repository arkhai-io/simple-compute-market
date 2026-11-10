"""Payments holds an operator's ruling twice before it completes, with no duplicate.

The payments double's rules cannot tell a ruling's two reverses on one part
apart, so the scenario stops the ruling the way a lane can: a drop-after-commit
rule on the authority's reverses for the deal lets payments commit the first
reverse and lose its answer, so the mediation double stops before the second;
then payments *unavailable* fails the first reverse's resend; once payments
answers, repeating the decision resends the first, which payments answers from
its stored event, and applies the second. Between them servicing steps show the
storefront the ruling unapplied and the case open, delivery active. Each
reverse lands exactly once. The deal is then ended by lease expiry, which files
nothing.
"""

from __future__ import annotations

import logging

import pytest
from lane_double_controls import Rule, Ruling

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
    snapshot_events,
    snapshot_part,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_PAYMENTS_HOLD_HOST,
    E2E_DISPUTE_PAYMENTS_HOLD_POOL_ID,
    E2E_DISPUTE_PAYMENTS_HOLD_RESOURCE_ID,
)

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_dispute_payments_hold,
]

log = logging.getLogger(__name__)

DROP_RULE_ID = "vm-dispute-payments-hold-drop"
OUTAGE_RULE_ID = "vm-dispute-payments-hold-unavailable"


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_PAYMENTS_HOLD_HOST,
                           pool_id=E2E_DISPUTE_PAYMENTS_HOLD_POOL_ID,
                           resource_id=E2E_DISPUTE_PAYMENTS_HOLD_RESOURCE_ID)


def _decide(lane_double_rules, dispute, amounts: list[int]):
    """The operator's ruling, two reverses on part 0 closing the case, decided
    or repeated."""
    return lane_double_rules.controls["mediation"].decide(dispute.case_refs[0], Ruling(
        basis="operator", delivery_end=False, close=True,
        effects=[{"kind": "reverse", "part": 0, "amount": str(amount)} for amount in amounts],
    ))


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
        assert [(part.part, part.status) for part in outcome.filing.parts] == [("0", "held")], outcome
        dispute.case_refs.append(outcome.filing.case_ref)
        log.info("[02] Case %s filed by the buyer", outcome.filing.case_ref)


class TestStage03_StorefrontAnswers:
    def test_03_a_servicing_step_answers_the_case(self, storefront_admin_client, dispute):
        require_state(dispute, "case_refs")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert [event.actor for event in view.authority.disputes
                if event.kind == "appended" and event.case_ref == dispute.case_refs[0]] == [
            str(payment_setting("SELLER_ACCOUNT"))], view


class TestStage04_ReverseAnswerDropped:
    def test_04_a_payments_rule_drops_the_answer_to_the_authority_s_reverse(
        self, mediation_target, lane_double_rules, dispute,
    ):
        require_state(dispute, "case_refs")
        view = lane_double_rules.install("payments", Rule(
            rule_id=DROP_RULE_ID, drop_response_after_commit=True, match={
                "route": "events", "account": mediation_target.account, "event": "reverse",
                "transaction": dispute.deal.transaction,
            },
        ))
        assert view.matched == 0, view


class TestStage05_FirstReverseCommittedAndLost:
    def test_05_the_decision_stops_after_its_first_reverse(
        self, payments_config, lane_double_rules, dispute,
    ):
        """Payments commits the first reverse and loses its answer; the second
        is never sent, and the case stays applying."""
        assert lane_double_rules.view("payments", DROP_RULE_ID), "the drop rule is not installed"
        gross = int(snapshot_part(payments_config, dispute.deal.transaction)["gross"])
        amounts = [gross // 8, gross // 4]
        case = _decide(lane_double_rules, dispute, amounts)
        dispute.amounts.extend(amounts)
        assert case.state == "applying", case
        assert lane_double_rules.view("payments", DROP_RULE_ID).matched == 1
        part = snapshot_part(payments_config, dispute.deal.transaction)
        assert int(part["reversed"]) == dispute.amounts[0], part
        log.info("[05] First reverse of %s committed, its answer lost; case %s applying",
                 dispute.amounts[0], case.case_ref)


class TestStage06_StorefrontSeesTheRulingUnapplied:
    def test_06_servicing_shows_the_ruling_unapplied_and_the_case_open(
        self, storefront_admin_client, dispute,
    ):
        require_state(dispute, "amounts")
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        case_ref = dispute.case_refs[0]
        ruled = [event for event in view.authority.disputes
                 if event.kind == "ruled" and event.case_ref == case_ref]
        assert ruled, view
        effects = [effect for effect in ruled[-1].outcome if effect.kind == "reverse"]
        assert len(effects) == 2 and not any(effect.applied for effect in effects), view
        assert not any(event.kind == "closed" and event.case_ref == case_ref
                       for event in view.authority.disputes), view
        assert view.delivery.progress == "active", view


class TestStage07_DropRuleDeleted:
    def test_07_the_drop_rule_is_deleted(self, lane_double_rules, dispute):
        require_state(dispute, "amounts")
        lane_double_rules.delete("payments", DROP_RULE_ID)
        assert lane_double_rules.controls["payments"].rules().rules == []


class TestStage07b_PaymentsUnavailable:
    def test_07b_the_payments_double_becomes_unavailable(self, lane_double_rules):
        view = lane_double_rules.install("payments", Rule(
            rule_id=OUTAGE_RULE_ID, match={}, unavailable=True,
        ))
        assert view.matched == 0, view


class TestStage08_DecisionRepeatedUnderTheOutage:
    def test_08_the_repeated_decision_fails_at_the_first_reverse_s_resend(
        self, lane_double_rules, dispute,
    ):
        assert lane_double_rules.view("payments", OUTAGE_RULE_ID), "the outage is not installed"
        case = _decide(lane_double_rules, dispute, dispute.amounts)
        assert case.state == "applying", case
        assert lane_double_rules.view("payments", OUTAGE_RULE_ID).matched >= 1


class TestStage09_StorefrontDuringTheOutage:
    def test_09_servicing_keeps_delivery_active_and_the_case_open(
        self, storefront_admin_client, lane_double_rules, dispute,
    ):
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.delivery.progress == "active", view
        assert view.delivery.recorded_end is None, view
        assert not any(case.state == "closed" for case in view.authority.cases), view
        (case,) = cases(lane_double_rules, dispute.deal.transaction)
        assert case.state == "applying", case


class TestStage10_OutageRemoved:
    def test_10_the_outage_is_removed(self, lane_double_rules):
        lane_double_rules.delete("payments", OUTAGE_RULE_ID)
        assert lane_double_rules.controls["payments"].rules().rules == []


class TestStage11_DecisionCompletes:
    def test_11_the_repeated_decision_completes_with_one_reverse_per_effect(
        self, payments_config, lane_double_rules, dispute,
    ):
        """The first reverse's resend is answered from payments' stored event,
        the second is applied, the extension lifted and the case closed."""
        require_state(dispute, "amounts")
        case = _decide(lane_double_rules, dispute, dispute.amounts)
        assert case.state == "closed", case
        part = snapshot_part(payments_config, dispute.deal.transaction)
        assert int(part["reversed"]) == sum(dispute.amounts), part
        assert part["extensions"] == [], part
        reverses = snapshot_events(payments_config, dispute.deal.transaction, "reverse")
        assert [int(event["event"]["amount"]) for event in reverses] == dispute.amounts, reverses
        effect_ids = [event["event"]["payload"]["effect_id"] for event in reverses]
        assert len(set(effect_ids)) == 2, reverses
        log.info("[11] Case %s closed; reverses %s, one per effect", case.case_ref, effect_ids)


class TestStage12_StorefrontSeesTheCaseClosed:
    def test_12_servicing_shows_the_case_closed(self, storefront_admin_client, dispute):
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.authority.outcome.status == "accepted", view
        assert [(case.case_ref, case.state) for case in view.authority.cases] == [
            (dispute.case_refs[0], "closed")], view
        assert view.delivery.progress == "active", view


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
