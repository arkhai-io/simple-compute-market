"""A VM deal's settlement waits for its own dispatch, not an earlier deal's.

08b settles and the VM driver waits for the storefront's ``provision/
job_submitted`` event before it reads the settle status's fulfillment. A
listing a rerun adopts already logs an earlier deal's event, so the wait is
filtered by the deal's negotiation and counted from a mark 08b takes before it
settles. 08b's body runs here with the VM drivers' shared base over fakes of
the storefront's event log, its settlement, and the provisioning service.
"""

from __future__ import annotations

from types import SimpleNamespace

from storefront_client.models import StageEvent, StageEventListResponse

from tests.e2e.roles.helpers.compute_deal import latest_stage_event_id
from tests.e2e.roles.helpers.compute_deal_stages import (
    ComputeDealState,
    Stage08b_SettlementSubmittedAndJobQueued,
)
from tests.e2e.roles.scenarios.vms.compute_deal_driver import VmDealDriverBase

LISTING = "listing-1"
EARLIER = "negotiation-earlier"
THIS = "negotiation-this"


def _event(event_id: int, event: str, negotiation_id: str, stage: str = "provision") -> StageEvent:
    return StageEvent(
        id=event_id, stage=stage, event=event, negotiation_id=negotiation_id, listing_id=LISTING,
    )


class FakeEventLog:
    """The storefront's stage-event log, read and waited on as the storefront
    filters it: events after ``since_id``, oldest first, on every filter given.

    Events in ``arriving`` are not logged yet; a wait that finds nothing logs
    them, as time passing would, and looks once more before it times out.
    """

    def __init__(self, *events: StageEvent, arriving: tuple[StageEvent, ...] = ()) -> None:
        self.events = list(events)
        self.arriving = list(arriving)
        self.calls: list[tuple[str, dict]] = []

    def _matching(self, since_id, stage, listing_id, negotiation_id) -> list[StageEvent]:
        return [
            event for event in self.events
            if event.id > since_id
            and stage in (None, event.stage)
            and listing_id in (None, event.listing_id)
            and negotiation_id in (None, event.negotiation_id)
        ]

    def get_events(
        self, *, since_id=0, limit=100, stage=None, listing_id=None, negotiation_id=None,
    ) -> StageEventListResponse:
        self.calls.append(("get_events", {"since_id": since_id, "negotiation_id": negotiation_id}))
        found = self._matching(since_id, stage, listing_id, negotiation_id)
        return StageEventListResponse(
            events=found[:limit], count=len(found[:limit]), truncated=len(found) > limit,
        )

    def wait_for_stage_event(
        self, stage, event, *, listing_id=None, negotiation_id=None, since_id=0, timeout=30.0,
    ) -> StageEvent:
        self.calls.append(("wait", {
            "listing_id": listing_id, "negotiation_id": negotiation_id, "since_id": since_id,
        }))
        for _ in range(2):
            for found in self._matching(since_id, stage, listing_id, negotiation_id):
                if found.event == event:
                    return found
            self.events += self.arriving
            self.arriving = []
        raise TimeoutError(f"{stage}/{event} not seen within {timeout}s")


class FakeSettlement:
    """The buyer's settle and its status, which names this deal's fulfillment
    once its dispatch is logged."""

    def __init__(self, log: FakeEventLog) -> None:
        self.log = log

    def settle_evm(self, escrow_uid, *, negotiation_id, buyer_evm_address):
        self.log.calls.append(("settle", {"negotiation_id": negotiation_id}))
        return SimpleNamespace(status="provisioning")

    def get_settle_status(self, escrow_uid):
        dispatched = any(
            event.event == "job_submitted" and event.negotiation_id == THIS
            for event in self.log.events
        )
        return SimpleNamespace(status="provisioning", fulfillment_id="f-this" if dispatched else None)


class FakeProvisioning:
    def get_fulfillment_status(self, fulfillment_id):
        return SimpleNamespace(model_dump=lambda mode: {"fulfillment_id": fulfillment_id, "state": "dispatching"})


def _driver(log: FakeEventLog) -> VmDealDriverBase:
    return VmDealDriverBase(
        provisioning_client=None, storefront_client=FakeSettlement(log), storefront_admin_client=log,
        storefront_service_client=None, site_capacity_admin_client=None, site_capacity=None,
        site_id="site",
    )


def _state() -> ComputeDealState:
    return ComputeDealState(
        domain_identity="vms.compute", negotiation_id=THIS, real_escrow_uid="0xescrow",
        seller_listing_id=LISTING, _settle_preflight_passed=True,
    )


def test_an_earlier_deals_dispatch_on_the_listing_is_not_this_deals():
    """The adopted listing's log holds an earlier deal's ``job_submitted``.
    Counted from the start of the log, the wait still passes over it for this
    deal's, and the fulfillment read is this deal's."""
    log = FakeEventLog(
        _event(1, "job_submitted", EARLIER),
        arriving=(_event(2, "job_submitted", THIS),),
    )
    fulfillment = _driver(log).settle_dispatched(
        SimpleNamespace(status="provisioning"), _state(), events_since=0
    )
    assert fulfillment == "f-this"


def test_08b_waits_for_the_deals_own_dispatch_from_a_mark_taken_before_settling():
    log = FakeEventLog(
        _event(1, "job_submitted", EARLIER),
        _event(4, "negotiation_started", THIS, stage="negotiation"),
        _event(5, "job_submitted", EARLIER),
        arriving=(_event(6, "job_submitted", THIS),),
    )
    driver = _driver(log)
    state = _state()
    Stage08b_SettlementSubmittedAndJobQueued().test_08b_settlement_submitted_and_provisioning_job_queued(
        driver.storefront_client, log, FakeProvisioning(), {"wallet_address": "0xbuyer"}, driver, state,
    )
    assert state.fulfillment_id == "f-this"
    order = [name for name, _ in log.calls]
    assert order.index("get_events") < order.index("settle") < order.index("wait"), order
    (wait,) = [arguments for name, arguments in log.calls if name == "wait"]
    assert wait == {"listing_id": LISTING, "negotiation_id": THIS, "since_id": 4}


def test_the_mark_is_read_past_a_full_page():
    log = FakeEventLog(*(_event(n, "noted", THIS, stage="negotiation") for n in range(1, 1202)))
    assert latest_stage_event_id(log, negotiation_id=THIS) == 1201
    assert [arguments["since_id"] for _name, arguments in log.calls] == [0, 500, 1000]


def test_a_deal_with_no_event_yet_is_marked_from_the_start():
    assert latest_stage_event_id(FakeEventLog(_event(1, "job_submitted", EARLIER)), negotiation_id=THIS) == 0
