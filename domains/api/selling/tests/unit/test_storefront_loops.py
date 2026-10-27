"""The storefront's loops: each step refuses before its collaborators exist, and a mechanism's loops are only the ones it contributes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_storefront_kit import LifecycleRouteError, NegotiationWatchdogPolicy, StorefrontLoopController

from arkhai_api_selling.lifecycle import (
    CAPACITY_EVENTS_POLLER,
    NEGOTIATION_WATCHDOG,
    SETTLEMENT_SERVICING,
    ContributedLoop,
    LoopSettings,
    StorefrontLoops,
    loop_controller,
    start_background_tasks,
)

SETTINGS = LoopSettings(
    watchdog=lambda: NegotiationWatchdogPolicy(timeout_seconds=60, interval_seconds=3600),
    settlement_servicing_interval=lambda: 3600,
    capacity_poll_interval=lambda: 3600,
)
BASE_LOOPS = {NEGOTIATION_WATCHDOG, SETTLEMENT_SERVICING, CAPACITY_EVENTS_POLLER}


async def _reconcile() -> dict:
    return {"loop": "example_reconciliation"}


RECONCILIATION = ContributedLoop(
    "example_reconciliation", route="example-reconciliation", step=_reconcile, interval_seconds=60
)


def _loops(*, db=None, worker=None, contributed=()) -> StorefrontLoops:
    return StorefrontLoops(
        sqlite_client=lambda: db,
        settlement_worker=lambda: worker,
        capacity=SimpleNamespace(configured_site_ids=lambda: ("quota",)),
        settings=SETTINGS,
        contributed_loops=lambda: contributed,
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


def test_a_storefront_composing_no_mechanism_loop_registers_only_its_own():
    steps, timers = loop_controller(), loop_controller()
    loops = _loops()

    loops.register_steps(steps)
    intervals = loops.register_loops(timers)

    assert set(steps.step_routes().values()) == BASE_LOOPS
    assert set(intervals) == BASE_LOOPS
    assert f"{CAPACITY_EVENTS_POLLER}:quota" in timers.states()


def test_a_contributed_loop_is_registered_and_timed_like_the_storefronts_own():
    steps, timers = loop_controller(), loop_controller()
    loops = _loops(contributed=(RECONCILIATION,))

    loops.register_steps(steps)
    intervals = loops.register_loops(timers)

    assert set(steps.step_routes().values()) == {*BASE_LOOPS, "example_reconciliation"}
    assert intervals["example_reconciliation"] == 60


async def test_startup_runs_only_the_composed_startup_steps():
    ran: list[str] = []

    async def step(name: str) -> None:
        ran.append(name)

    class Loops(StorefrontLoopController):
        def start_loops(self, **_options):
            ran.append("loops")
            return {}

    async def backfill() -> None:
        await step("backfill")

    await start_background_tasks(
        _loops(),
        Loops(),
        sqlite_client=None,
        storefront_url="https://seller.example",
        preflight=lambda: step("preflight"),
        seed=lambda: step("seed"),
        open_thread_store=lambda **_store: None,
    )
    assert ran == ["preflight", "seed", "loops"]

    ran.clear()
    await start_background_tasks(
        _loops(),
        Loops(),
        sqlite_client=None,
        storefront_url="https://seller.example",
        preflight=lambda: step("preflight"),
        seed=lambda: step("seed"),
        startup_steps=(backfill,),
        open_thread_store=lambda **_store: None,
    )
    assert ran == ["backfill", "preflight", "seed", "loops"]
