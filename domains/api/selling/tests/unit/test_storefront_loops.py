"""The storefront's loops: each step refuses before its collaborators exist, and payments steps only when composed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_storefront_kit import LifecycleRouteError, NegotiationWatchdogPolicy

from arkhai_api_selling.lifecycle import (
    CAPACITY_EVENTS_POLLER,
    NEGOTIATION_WATCHDOG,
    PAYMENT_RECONCILIATION,
    SETTLEMENT_SERVICING,
    LoopSettings,
    StorefrontLoops,
    loop_controller,
)

SETTINGS = LoopSettings(
    watchdog=lambda: NegotiationWatchdogPolicy(timeout_seconds=60, interval_seconds=3600),
    settlement_servicing_interval=lambda: 3600,
    payment_reconciliation_interval=lambda: 3600,
    capacity_poll_interval=lambda: 3600,
)


def _loops(*, db=None, worker=None, payments=None) -> StorefrontLoops:
    return StorefrontLoops(
        sqlite_client=lambda: db,
        settlement_worker=lambda: worker,
        payment_service=lambda get_db: payments(get_db()) if payments else None,
        capacity=SimpleNamespace(configured_site_ids=lambda: ("quota",)),
        settings=SETTINGS,
    )


async def test_a_step_taken_before_the_services_start_is_refused():
    loops = _loops()

    with pytest.raises(LifecycleRouteError, match="persistence"):
        await loops.negotiation_watchdog_step()
    with pytest.raises(LifecycleRouteError, match="servicing worker"):
        await loops.settlement_servicing_step()


async def test_settlement_servicing_runs_the_workers_one_cycle():
    class Worker:
        async def run_once(self) -> int:
            return 2

    assert await _loops(worker=Worker()).settlement_servicing_step() == {
        "loop": SETTLEMENT_SERVICING,
        "processed": 2,
    }


async def test_payment_reconciliation_is_registered_and_stepped_only_while_payments_is_composed():
    class Payments:
        async def reconcile_once(self):
            return SimpleNamespace(attempted=3, failed=1)

    without = loop_controller()
    _loops().register_steps(without)
    assert PAYMENT_RECONCILIATION not in without.step_routes().values()
    assert await _loops().payment_reconciliation_step() == {
        "loop": PAYMENT_RECONCILIATION,
        "attempted": 0,
        "failed": 0,
    }

    composed = _loops(db=object(), payments=lambda _db: Payments())
    with_payments = loop_controller()
    composed.register_steps(with_payments)
    assert set(with_payments.step_routes().values()) == {
        NEGOTIATION_WATCHDOG,
        SETTLEMENT_SERVICING,
        PAYMENT_RECONCILIATION,
        CAPACITY_EVENTS_POLLER,
    }
    assert (await composed.payment_reconciliation_step())["attempted"] == 3


def test_registering_the_loops_declares_each_configured_sites_poller():
    loops = loop_controller()

    intervals = _loops().register_loops(loops)

    assert intervals == {
        NEGOTIATION_WATCHDOG: 3600,
        SETTLEMENT_SERVICING: 3600,
        CAPACITY_EVENTS_POLLER: 3600,
    }
    assert f"{CAPACITY_EVENTS_POLLER}:quota" in loops.states()
