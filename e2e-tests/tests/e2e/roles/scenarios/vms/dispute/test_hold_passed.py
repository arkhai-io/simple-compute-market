"""A case filed after a once part's hold has paid out is dismissed with nothing held.

The deal is ended by lease expiry before any clock moves, so no storefront step
follows the advance. The part's hold runs from its stop, and a once part stops
at its terms end, so both doubles' perceived clocks are advanced together first
past that end, when the signed snapshot states the release instant, then past
that instant: payments shows the part paid out, and the buyer's filing is answered with the part
``not_held``, ``paid_out``, and the case dismissed with nothing held. The clock
fixture resets both doubles when the module ends, whatever its outcome, so no
later module meets the advance.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

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
from tests.e2e.roles.scenarios.vms.dispute.stages import (
    DisputeStage01_HostedDealCommitted,
    DisputeStageZ_NoFurtherCase,
    cases,
    scenario_driver,
    snapshot_part,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DISPUTE_HOLD_PASSED_HOST,
    E2E_DISPUTE_HOLD_PASSED_POOL_ID,
    E2E_DISPUTE_HOLD_PASSED_RESOURCE_ID,
)

pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence", "lane_double_rules", "lane_double_clock",
    ),
    pytest.mark.e2e_vm_dispute_hold_passed,
]

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    return scenario_driver(deal_driver, host=E2E_DISPUTE_HOLD_PASSED_HOST,
                           pool_id=E2E_DISPUTE_HOLD_PASSED_POOL_ID,
                           resource_id=E2E_DISPUTE_HOLD_PASSED_RESOURCE_ID)


@pytest.fixture(scope="module")
def advanced() -> dict:
    """Both doubles' perceived nows once advanced past the release, for the
    filing stage."""
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


def _advance_past(lane_double_clock, instant: int) -> dict:
    """Advance both doubles together to a second past ``instant``."""
    now = lane_double_clock.controls["payments"].status().perceived_now
    nows = lane_double_clock.advance(max(instant - now, 0) + 1)
    assert all(perceived > instant for perceived in nows.values()), nows
    return nows


class TestStage20_ClocksPassTheTermsEnd:
    def test_20_both_clocks_pass_the_part_s_terms_end_and_its_hold_starts(
        self, payments_config, lane_double_clock, deal_state, dispute,
    ):
        """The part's hold runs from its stop, and a once part stops at its
        terms end, which the lease's ending does not move: both doubles advance
        past the end the signed snapshot states, and the part's release instant
        is then stated, its money still held."""
        require_state(deal_state, "_teardown_job_completed")
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and "releaseAt" not in part, part
        nows = _advance_past(lane_double_clock, part["end"]["at"])
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and part.get("releaseAt"), part
        log.info("[20] Both doubles advanced past the terms end %s to %s; release at %s",
                 part["end"]["at"], nows, part["releaseAt"])


class TestStage21_ClocksPassTheHold:
    def test_21_both_clocks_pass_the_part_s_release_and_it_pays_out(
        self, payments_config, lane_double_clock, dispute, advanced,
    ):
        """Both doubles advance together past the release instant the part's
        signed snapshot states; the next read shows the part paid out."""
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part.get("releaseAt"), "the part's hold has not started"
        release = int(datetime.fromisoformat(part["releaseAt"].replace("Z", "+00:00")).timestamp())
        advanced.update(_advance_past(lane_double_clock, release))
        part = snapshot_part(payments_config, transaction)
        assert int(part["released"]) > 0 and part["status"] in {"released", "settled"}, part
        log.info("[21] Both doubles advanced past %s to %s; part paid out", release, advanced)


class TestStage22_BuyerFilesAfterThePayout:
    def test_22_the_buyer_s_filing_reports_the_part_paid_out_and_is_dismissed(
        self, mediation_target, lane_double_rules, dispute, advanced,
    ):
        assert advanced, "the clocks were not advanced"
        deal = dispute.deal
        outcome = file_as_buyer(mediation_target, negotiation_id=deal.negotiation_id,
                                transaction=deal.transaction, agreement=deal.agreement,
                                store=dispute.buyer_store)
        assert outcome.status == "accepted" and outcome.filing is not None, outcome
        assert [(part.part, part.status, part.reason) for part in outcome.filing.parts] == [
            ("0", "not_held", "paid_out")], outcome
        dispute.case_refs.append(outcome.filing.case_ref)
        (case,) = cases(lane_double_rules, deal.transaction)
        assert (case.case_ref, case.state) == (outcome.filing.case_ref, "closed"), case
        log.info("[22] Case %s dismissed with nothing held: part 0 paid out", case.case_ref)
