"""A case filed after a once part's hold has paid out is dismissed with nothing held.

The deal is ended by lease expiry before any time moves, so no storefront step
follows the set. The part's hold runs from its stop, and a once part stops at
its terms end, so both doubles' injected time is set together first past that
end, when the signed snapshot states the release instant, then past that
instant: payments shows the part paid out, and the buyer's filing is answered with the part
``not_held``, ``paid_out``, and the case dismissed with nothing held.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime

import pytest
from lane_double_controls import ControlClient

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
from tests.e2e.roles.helpers.lane_doubles import DOUBLES, Double, lane_double_controls
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
def doubles_time() -> Iterator[dict[Double, ControlClient]]:
    """Both doubles' control clients, which set their injected time."""
    controls = lane_double_controls()
    try:
        yield controls
    finally:
        for client in controls.values():
            client.close()


@pytest.fixture(scope="module")
def advanced() -> dict:
    """Both doubles' instants once set past the release, for the filing stage."""
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


def _set_past(controls: dict[Double, ControlClient], instant: int) -> dict[Double, int]:
    """Set both doubles together to a second past ``instant``, or leave a double
    already past it; each double's instant."""
    nows: dict[Double, int] = {}
    for double in DOUBLES:
        now = controls[double].status().time.now
        assert now is not None, f"the {double} double's time is not injected"
        nows[double] = controls[double].set_time(max(now, instant + 1)).now or 0
    assert all(now > instant for now in nows.values()), nows
    return nows


class TestStage20_TimePassesTheTermsEnd:
    def test_20_both_doubles_pass_the_part_s_terms_end_and_its_hold_starts(
        self, payments_config, doubles_time, deal_state, dispute,
    ):
        """The part's hold runs from its stop, and a once part stops at its
        terms end, which the lease's ending does not move: both doubles are set
        past the end the signed snapshot states, and the part's release instant
        is then stated, its money still held."""
        require_state(deal_state, "_teardown_job_completed")
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and "releaseAt" not in part, part
        nows = _set_past(doubles_time, part["end"]["at"])
        part = snapshot_part(payments_config, transaction)
        assert part["released"] == "0" and part.get("releaseAt"), part
        log.info("[20] Both doubles set past the terms end %s to %s; release at %s",
                 part["end"]["at"], nows, part["releaseAt"])


class TestStage21_TimePassesTheHold:
    def test_21_both_doubles_pass_the_part_s_release_and_it_pays_out(
        self, payments_config, doubles_time, dispute, advanced,
    ):
        """Both doubles are set together past the release instant the part's
        signed snapshot states; the next read shows the part paid out."""
        transaction = dispute.deal.transaction
        part = snapshot_part(payments_config, transaction)
        assert part.get("releaseAt"), "the part's hold has not started"
        release = int(datetime.fromisoformat(part["releaseAt"].replace("Z", "+00:00")).timestamp())
        advanced.update(_set_past(doubles_time, release))
        part = snapshot_part(payments_config, transaction)
        assert int(part["released"]) > 0 and part["status"] in {"released", "settled"}, part
        log.info("[21] Both doubles set past %s to %s; part paid out", release, advanced)


class TestStage22_BuyerFilesAfterThePayout:
    def test_22_the_buyer_s_filing_reports_the_part_paid_out_and_is_dismissed(
        self, mediation_target, lane_double_rules, dispute, advanced,
    ):
        assert advanced, "time was not set past the release"
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
