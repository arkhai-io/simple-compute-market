"""A case filed after a once part's hold has paid out is dismissed with nothing held.

The deal is ended by lease expiry before lane time moves. The part's hold runs
from its stop, and a once part stops at its terms end, so lane time — every
party's, the doubles' among them — is set first past that end, when the signed
snapshot states the release instant, then past that instant: payments shows the
part paid out, and the buyer's filing is answered with the part ``not_held``,
``paid_out``, and the case dismissed with nothing held. On a wall-time run the
two stages are blocked skips: the instants are days ahead.
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
from tests.e2e.roles.helpers.lane_time import LaneTime
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
        "lane_doubles_evidence", "lane_double_rules",
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
    """The lane instants stages 20 and 21 set, for the stages after each."""
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


def _past(lane_time: LaneTime | None, instant: int) -> int:
    """Set lane time to a second past ``instant``, or leave it where it is past
    it; the lane instant. A blocked skip on wall time, which cannot reach it."""
    if lane_time is None:
        pytest.skip(f"blocked: reaching {instant} needs lane time, and the run has none")
    reached = lane_time.reach(instant + 1, fixed_by_agreement=False)
    assert reached > instant, reached
    return reached


class TestStage20_TimePassesTheTermsEnd:
    def test_20_lane_time_passes_the_part_s_terms_end_and_its_hold_starts(
        self, payments_config, lane_time, deal_state, dispute, advanced,
    ):
        """The part's hold runs from its stop, and a once part stops at its
        terms end, which the lease's ending does not move: lane time is set past
        the end the signed snapshot states, and the part's release instant is
        then stated, its money still held."""
        require_state(deal_state, "_teardown_job_completed")
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and "releaseAt" not in part, part
        now = _past(lane_time, part["end"]["at"])
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and part.get("releaseAt"), part
        advanced["terms_end"] = now
        log.info("[20] Lane time set past the terms end %s to %s; release at %s",
                 part["end"]["at"], now, part["releaseAt"])


class TestStage21_TimePassesTheHold:
    def test_21_lane_time_passes_the_part_s_release_and_it_pays_out(
        self, payments_config, lane_time, dispute, advanced,
    ):
        """Lane time is set past the release instant the part's signed snapshot
        states; the next read shows the part paid out."""
        if "terms_end" not in advanced:
            pytest.skip("blocked: stage 20 did not set lane time past the part's terms end")
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part.get("releaseAt"), "the part's hold has not started"
        release = int(datetime.fromisoformat(part["releaseAt"].replace("Z", "+00:00")).timestamp())
        advanced["now"] = _past(lane_time, release)
        part = snapshot_part(payments_config, transaction)
        assert int(part["released"]) > 0 and part["status"] in {"released", "settled"}, part
        log.info("[21] Lane time set past %s to %s; part paid out", release, advanced["now"])


class TestStage22_BuyerFilesAfterThePayout:
    def test_22_the_buyer_s_filing_reports_the_part_paid_out_and_is_dismissed(
        self, mediation_target, lane_double_rules, dispute, advanced,
    ):
        if "now" not in advanced:
            pytest.skip("blocked: stage 21 did not set lane time past the part's release")
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
