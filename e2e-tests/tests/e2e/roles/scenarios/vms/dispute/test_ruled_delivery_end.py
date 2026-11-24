"""A programmed ruling with a delivery end and a reverse ends a hosted VM deal.

The scenario installs, on the mediation double, a ruling rule matching its own
deal's filing and held at its gate, then files as the buyer, so each side effect
has its own stage: the filing (the case filed, its part held, the ruling
recorded and waiting), the resume (the reverse at the payments double, the
extension lifted, the case closed), and only then a storefront servicing step,
which records the end with cause ``ruling`` and begins teardown, and a second,
which reads the site's signed end report. No servicing step runs while the
ruling waits at its gate. The deal is released through the mock teardown gate,
as ``lifecycle_deal.py``'s release stage proves it.
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
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.mediation import file_as_buyer
from tests.e2e.roles.scenarios.vms.dispute.stages import (
    DisputeStage01_HostedDealCommitted,
    cases,
    lifecycle_read,
    scenario_driver,
    servicing_step,
    snapshot_events,
    snapshot_part,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_RULED_END_HOST,
    E2E_DISPUTE_RULED_END_POOL_ID,
    E2E_DISPUTE_RULED_END_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.lifecycle_deal import Stage12c_CapacityReleasedOnce

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules",
    ),
    pytest.mark.e2e_vm_dispute_ruled_end,
]

log = logging.getLogger(__name__)

RULE_ID = "vm-dispute-ruled-end"


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_RULED_END_HOST,
                           pool_id=E2E_DISPUTE_RULED_END_POOL_ID,
                           resource_id=E2E_DISPUTE_RULED_END_RESOURCE_ID)


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


class TestStage02_GatedRulingInstalled:
    def test_02_a_gated_ruling_on_the_deal_s_filing_is_installed(
        self, payments_config, lane_double_rules, dispute,
    ):
        """A rule on the deal's own filing: an operator-basis ruling ending
        delivery and reversing a quarter of part 0, closing the case, held at
        its gate before any effect."""
        require_state(dispute, "deal")
        amount = int(snapshot_part(payments_config, dispute.deal.transaction)["gross"]) // 4
        view = lane_double_rules.install("mediation", Rule(
            rule_id=RULE_ID,
            match={"operation": "file", "transaction": dispute.deal.transaction},
            ruling=Ruling(basis="operator", delivery_end=True, close=True,
                          effects=[{"kind": "reverse", "part": 0, "amount": str(amount)}]),
            pause_before_effects=True,
        ))
        assert (view.matched, view.waiting) == (0, 0), view
        dispute.amounts.append(amount)
        log.info("[02] Gated ruling %s installed, reversing %s", RULE_ID, amount)


class TestStage03_BuyerFilesAtTheGate:
    def test_03_the_buyer_s_filing_is_held_and_its_ruling_waits(
        self, payments_config, mediation_target, lane_double_rules, dispute,
    ):
        """The buyer's filing is accepted with part 0 held by an extension; the
        ruling is recorded and waits at its gate, nothing reversed."""
        require_state(dispute, "amounts")
        deal = dispute.deal
        outcome = file_as_buyer(mediation_target, negotiation_id=deal.negotiation_id,
                                transaction=deal.transaction, agreement=deal.agreement,
                                store=dispute.buyer_store)
        assert outcome.status == "accepted" and outcome.filing is not None, outcome
        assert [(part.part, part.status) for part in outcome.filing.parts] == [("0", "held")], outcome
        assert outcome.filing.parts[0].extension_ref, outcome
        dispute.case_refs.append(outcome.filing.case_ref)
        (case,) = cases(lane_double_rules, deal.transaction)
        assert (case.case_ref, case.state) == (outcome.filing.case_ref, "applying"), case
        view = lane_double_rules.view("mediation", RULE_ID)
        assert (view.matched, view.waiting) == (1, 1), view
        assert snapshot_part(payments_config, deal.transaction)["reversed"] == "0"
        log.info("[03] Case %s filed by the buyer; its ruling waits at the gate",
                 outcome.filing.case_ref)


class TestStage04_RulingResumed:
    def test_04_resuming_applies_the_reverse_once_and_closes_the_case(
        self, payments_config, lane_double_rules, dispute,
    ):
        """Resumed, the ruling reverses exactly its amount once, lifts the
        case's extension and closes the case."""
        require_state(dispute, "case_refs")
        deal = dispute.deal
        view = lane_double_rules.resume(RULE_ID)
        assert view.waiting == 0, view
        (case,) = cases(lane_double_rules, deal.transaction)
        assert case.state == "closed", case
        part = snapshot_part(payments_config, deal.transaction)
        assert int(part["reversed"]) == dispute.amounts[0], part
        assert part["extensions"] == [], part
        reverses = snapshot_events(payments_config, deal.transaction, "reverse")
        assert len(reverses) == 1, reverses
        log.info("[04] Ruling resumed: %s reversed, case %s closed",
                 dispute.amounts[0], case.case_ref)


class TestStage04b_ArmTeardownGate:
    def test_04b_the_mock_teardown_gate_is_armed(self, deal_driver, dispute):
        """The teardown the ruled end begins is held at the mock gate until the
        release stage opens it."""
        require_state(dispute, "case_refs", "amounts")
        deal_driver.arm_teardown_gate()


class TestStage05_ServicingRecordsTheRuledEnd:
    def test_05_the_storefront_records_the_ruled_end_and_tears_down(
        self, storefront_admin_client, deal_state, dispute,
    ):
        """One servicing step reads the ruled entry with its delivery end,
        records the end with cause ``ruling`` and begins teardown, held at the
        mock teardown gate."""
        require_state(dispute, "case_refs", "amounts")
        deal = dispute.deal
        servicing_step(storefront_admin_client)
        view = lifecycle_read(deal.negotiation_id)
        ruled = [event for event in view.authority.disputes
                 if event.kind == "ruled" and event.case_ref == dispute.case_refs[0]]
        assert ruled and any(effect.kind == "delivery_end" for effect in ruled[0].outcome), view
        assert view.delivery.recorded_end is not None, view
        assert view.delivery.recorded_end.cause == "ruling", view
        assert view.delivery.progress == "tearing_down", view
        purchase = deal_state.lifecycle_purchase
        purchase.receipt = {"selected_end": view.delivery.recorded_end.model_dump(mode="json")}
        log.info("[05] Deal %s ended by ruling at %s; tearing down",
                 deal.negotiation_id, view.delivery.recorded_end.ended_at)


class TestStage05b_ServicingReadsTheSiteReport:
    def test_05b_the_next_servicing_step_reads_the_site_s_signed_end_report(
        self, storefront_admin_client, deal_state, dispute,
    ):
        """The next servicing step ingests the site's signed end report, with
        teardown still held and the end as recorded. A servicing step reads the
        site's lease before its authority watch, so the step that recorded the
        ruled end read the lease before teardown began; the report the site
        pushes as teardown begins is not relied on to arrive within that step."""
        require_state(dispute, "case_refs", "amounts")
        purchase = deal_state.lifecycle_purchase
        assert purchase.receipt, "the servicing step did not record the ruled end"
        servicing_step(storefront_admin_client)
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.delivery.progress == "tearing_down", view
        assert view.delivery.recorded_end is not None, view
        assert view.delivery.recorded_end.model_dump(mode="json") == (
            purchase.receipt["selected_end"]), view
        assert view.delivery.site_reports, view
        purchase.reports = [item.model_dump(mode="json") for item in view.delivery.site_reports]
        log.info("[05b] Site end report read for deal %s", dispute.deal.negotiation_id)


class TestStage06_CapacityReleasedOnce(Stage12c_CapacityReleasedOnce):
    pass
