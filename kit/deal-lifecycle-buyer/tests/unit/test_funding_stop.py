"""What the buyer is told when a rate deal stopped because its funds ran out.

A real ``BuyerLifecycle`` over mocked ports: its payment adapter returns the
authority's view, and the domain's stop classifier is injected, here splitting
``terms`` stops at a term ending at 1000 as the compute classifier does.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector
from market_deal_lifecycle_buyer import (
    FUNDING_STOP, BuyerDeal, BuyerLifecycle, EndTarget, WatchdogSettings, WatchdogState, run_monitor,
)
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DeliveryView, LifecycleRead, PaymentEvent, PaymentPartObservation,
)

TERM_END = 1000


def stop(at):
    return PaymentEvent(
        negotiation_id="deal", commitment_ref="commitment", part="0", kind="stop", actor="terms",
        at=at, cause="terms", sequence=1, authority_record_ref="commitment:events:1",
    )


def classify(event):
    return "exhaustion" if event.at < TERM_END else "terms"


class Journal:
    """The watchdog journal's interface, in memory, with one opt-in."""

    def __init__(self):
        self.states = {"deal": WatchdogState(WatchdogSettings(1, 1, 1))}

    def state(self, negotiation_id):
        return self.states.get(negotiation_id)

    def record_probe(self, negotiation_id, at):
        pass


def buyer(final_stop, *, classifier=classify):
    """The buyer's lifecycle of a rate deal whose payment authority shows ``final_stop``."""
    view = AuthorityView(outcome=Accepted(), state="ended", parts=[
        PaymentPartObservation(part="0", final_stop=final_stop, evidence_ref="snapshot"),
    ])
    deal = BuyerDeal(
        negotiation_id="deal", commitment_ref="commitment",
        payment=PaymentBinding("deal", PaymentSelector("fixture.payment.v1")), rate=True,
    )
    payment = SimpleNamespace(read=AsyncMock(return_value=view))
    peer = SimpleNamespace(read=AsyncMock(return_value=LifecycleRead(
        negotiation_id="deal", commitment_ref="commitment", authority=AuthorityView(outcome=Accepted()),
        delivery=DeliveryView(progress="released"),
    )))
    return BuyerLifecycle(
        deal=lambda _: deal, payments=PaymentAdapterTable([(deal.payment.selector, lambda _: payment)]),
        disputes=DisputeAdapterTable([]), operations=MagicMock(), peer=peer, watchdog=Journal(),
        clock=lambda: 2000, classify_payment_stop=classifier,
    )


@pytest.mark.asyncio
async def test_a_read_of_a_deal_whose_funds_ran_out_says_why_the_stop_is_final():
    read = await buyer(stop(TERM_END - 900)).buyer_read("deal")
    assert read["funding_stop"] == FUNDING_STOP
    assert "could not reserve the next period" in FUNDING_STOP
    assert "a top-up cannot revive it" in FUNDING_STOP and "a new deal is needed" in FUNDING_STOP


@pytest.mark.asyncio
@pytest.mark.parametrize(("final_stop", "classifier"), [
    (stop(TERM_END), classify),
    (stop(TERM_END - 900), None),
    (None, classify),
])
async def test_a_read_of_a_deal_that_reached_its_term_or_runs_says_nothing_of_funds(final_stop, classifier):
    assert (await buyer(final_stop, classifier=classifier).buyer_read("deal"))["funding_stop"] is None


def monitor(lifecycle):
    @asynccontextmanager
    async def context():
        yield lifecycle

    return EndTarget(negotiation_id="deal", lifecycle=context())


@pytest.mark.parametrize(("at", "said"), [(TERM_END - 900, True), (TERM_END, False)])
def test_the_watchdog_exit_says_a_deal_ended_because_its_funds_ran_out(at, said):
    lines = []
    # The authority shows the part's final stop, so the deal ended by another path.
    outcome = run_monitor(monitor(buyer(stop(at))), probe=AsyncMock(return_value=True), echo=lines.append)
    assert (outcome.reason, outcome.funding_stop) == ("ended", said)
    assert lines[-1] == "Watchdog exited: the deal ended by another path." + (" " + FUNDING_STOP if said else "")
