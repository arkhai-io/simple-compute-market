"""Every loop the storefront registers is held by a pause within its bound.

The kit controller's tests prove the mechanism against synthetic loops. They
cannot prove that a production loop uses it. Two properties have to hold for
each loop the storefront registers: it acknowledges its gate under the name
`startup.py` registers it as, and it waits between cycles through the
controller, so a pause requested during its interval reaches the gate at once.
A loop that reads the flag without acknowledging, gates under a drifted name,
or sleeps its interval instead fails the same observable way: a pause cannot
report it `paused` within the pause's bounded wait.

So each case drives a loop's real coroutine with its work stubbed and its
interval set far longer than any test would wait, and asserts the pause reports
it `paused` well inside the controller's own bound. Work is synchronized with
events; nothing here waits on time.

The negotiation watchdog and the settlement servicing sweep live in `kit/` and
are composed with an injected gate and wait, so they are covered through that
composition. Capacity polling's per-site fan-out lives in
`kit/capacity-publication`, so the storefront holds no task per site; the
per-site cases assert against declared gate names, and that each site
acknowledges for itself.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront import lifecycle

#: Far longer than any test waits. A loop that sleeps this instead of waiting
#: through the controller cannot be reported paused within `_PROMPTLY`.
_LONG_INTERVAL = 3600.0

#: Well inside the controller's own quiescence bound, so a loop that is only
#: reported paused once that bound expires fails here rather than passing late.
_PROMPTLY = 1.0


@pytest.fixture(autouse=True)
async def _clean_registry():
    lifecycle.reset_for_tests()
    yield
    handles = list(lifecycle.controller()._handles.values())
    lifecycle.reset_for_tests()
    await asyncio.gather(*handles, return_exceptions=True)


@asynccontextmanager
async def _registered(coro_factory, name: str):
    """Run a loop body as a registered loop under the name `startup.py` uses.

    Cancellation is how the loop ends in this test, never how a pause works:
    these loops are not cancelled in production. It is only the test's way of
    reclaiming a coroutine designed never to return.
    """
    task = lifecycle.start_registered_loop(
        StorefrontBackgroundTask(name=name, task_factory=coro_factory)
    )
    try:
        yield task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _paused_promptly() -> dict[str, str]:
    return await asyncio.wait_for(lifecycle.controller().pause(), timeout=_PROMPTLY)


class TestRegisteredNamesAreTheGatedNames:
    def test_startup_registers_exactly_the_named_loops(self):
        """The constants are the contract between registration and gating.

        If a loop is added without a constant, the two ends can disagree again
        and nothing else in this file will notice, because it only checks the
        loops it knows to check.
        """
        from market_storefront import startup

        source = (startup.__file__ and open(startup.__file__).read()) or ""
        for constant in (
            "NEGOTIATION_WATCHDOG",
            "SETTLEMENT_SERVICING",
            "FULFILLMENT_RESUME",
            "CAPACITY_EVENTS_POLLER",
            "SITE_PROJECTION_POLLER",
            "PUBLICATION",
        ):
            assert f"name={constant}" in source, (
                f"{constant} is no longer used to register its loop; a literal "
                "name here can drift from the one the loop body gates under"
            )


class TestEachProductionLoopIsHeldWithinItsInterval:
    async def test_negotiation_watchdog(self, monkeypatch):
        """Composed as `startup.py` composes it, and held during its startup
        delay as well as its interval.

        The delay holds the sweep, not the gate: a watchdog unobservable for its
        startup window would miss the first pause of an end-to-end run.
        """
        from market_storefront_kit import negotiation_watchdog as nw

        swept: list[int] = []

        async def _sweep(_repository, _policy, **_kwargs):
            swept.append(1)
            return 0

        monkeypatch.setattr(nw, "sweep_stale_negotiations", _sweep)
        policy = nw.NegotiationWatchdogPolicy(
            timeout_seconds=1800.0,
            interval_seconds=_LONG_INTERVAL,
            initial_delay_seconds=30.0,
        )
        name = lifecycle.NEGOTIATION_WATCHDOG
        async with _registered(
            partial(
                nw.run_negotiation_watchdog,
                object(),
                policy,
                paused=lifecycle.loop_gate(name),
                wait=lifecycle.idle,
            ),
            name,
        ):
            states = await _paused_promptly()

        assert states == {name: "paused"}
        assert not swept, "the startup delay no longer holds the sweep"

    async def test_settlement_servicing(self):
        from market_settlement_runtime.servicing import SettlementServicingWorker

        class _Repo:
            async def list_due_settlement_obligations(self, **_kwargs):
                return []

        worker = SettlementServicingWorker(
            runtime=object(),
            repository=_Repo(),
            worker_id="test",
            interval_seconds=_LONG_INTERVAL,
        )
        name = lifecycle.SETTLEMENT_SERVICING
        async with _registered(
            partial(worker.run, paused=lifecycle.loop_gate(name), wait=lifecycle.idle),
            name,
        ):
            states = await _paused_promptly()

        assert states == {name: "paused"}

    async def test_fulfillment_resume(self, monkeypatch):
        from market_storefront.services import fulfillment_resume_runtime as frr

        swept: list[int] = []
        first = asyncio.Event()

        async def _sweep(**_kwargs):
            swept.append(1)
            first.set()
            return 0

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _sweep)
        # A stand-in settings object rather than an attribute on the dynaconf
        # singleton: the loop reads its interval with a `getattr` default, so the
        # key is absent from the real settings, and monkeypatch restores an
        # absent attribute by deleting it -- which dynaconf rejects for a key it
        # never held.
        monkeypatch.setattr(
            "market_storefront.utils.config.settings",
            SimpleNamespace(fulfillment_resume_sweep_interval=_LONG_INTERVAL),
        )
        name = lifecycle.FULFILLMENT_RESUME
        async with _registered(partial(frr.fulfillment_resume_loop, object()), name):
            await asyncio.wait_for(first.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        assert states == {name: "paused"}
        assert swept == [1], "a held loop swept again"

    async def test_fulfillment_resume_survives_a_failing_sweep(self, monkeypatch):
        """A raising cycle must not end the loop.

        Nothing restarts one, so a single bad sweep would otherwise stop escrow
        convergence for the life of the process. Each pause and resume lets the
        loop through one more cycle, so the second failure is observed without
        waiting on its interval.
        """
        from market_storefront.services import fulfillment_resume_runtime as frr

        failures: list[int] = []
        failed = asyncio.Event()

        async def _always_fails(**_kwargs):
            failures.append(1)
            failed.set()
            raise RuntimeError("sweep failed")

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _always_fails)
        monkeypatch.setattr(
            "market_storefront.utils.config.settings",
            SimpleNamespace(fulfillment_resume_sweep_interval=_LONG_INTERVAL),
        )
        name = lifecycle.FULFILLMENT_RESUME
        async with _registered(partial(frr.fulfillment_resume_loop, object()), name):
            await asyncio.wait_for(failed.wait(), timeout=_PROMPTLY)
            await _paused_promptly()
            failed.clear()
            await lifecycle.controller().resume()
            await asyncio.wait_for(failed.wait(), timeout=_PROMPTLY)

        assert len(failures) == 2, "the loop stopped after a failing sweep"

    async def test_site_projection_poller(self, monkeypatch):
        from market_storefront.services import site_projection_cache as spc

        loads: list[int] = []
        first = asyncio.Event()

        async def _load(_client):
            loads.append(1)
            first.set()

        monkeypatch.setattr(spc, "load_site_projections", _load)
        monkeypatch.setattr(
            "market_storefront.utils.config.settings",
            SimpleNamespace(capacity=SimpleNamespace(poll_interval=_LONG_INTERVAL)),
        )
        name = lifecycle.SITE_PROJECTION_POLLER
        async with _registered(partial(spc.site_projection_poller_loop, object()), name):
            await asyncio.wait_for(first.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        assert states == {name: "paused"}
        assert loads == [1], "a held poller pulled projections again"

    async def test_publication_loop_gates_before_any_cycle(self):
        """Held from the start, the publication loop reaches its gate and runs no cycle."""
        from market_storefront.services.publication_loop import publication_loop

        cycles: list[bool] = []

        async def _cycle(*, dry_run):
            cycles.append(dry_run)
            return {}

        lifecycle.controller().request_pause(True)
        async with _registered(partial(publication_loop, _cycle), lifecycle.PUBLICATION):
            await asyncio.wait_for(lifecycle.await_quiescence(), timeout=_PROMPTLY)
            states = lifecycle.loop_states()

        assert states == {lifecycle.PUBLICATION: "paused"}
        assert cycles == []

    async def test_a_pause_during_the_idle_wait_reaches_the_gate(self):
        """A pause issued between cycles reaches the loop's gate at once.

        The pause wakes the idle wait, so it never waits on the loop's interval,
        which is far longer than any pause should take.
        """
        from market_storefront.services.publication_loop import publication_loop

        cycles: list[bool] = []
        first_cycle = asyncio.Event()

        async def _cycle(*, dry_run):
            cycles.append(dry_run)
            first_cycle.set()
            return {}

        async with _registered(partial(publication_loop, _cycle), lifecycle.PUBLICATION):
            await asyncio.wait_for(first_cycle.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        assert states[lifecycle.PUBLICATION] == "paused"
        assert cycles == [False]

    async def test_a_projection_change_wakes_the_idle_loop(self):
        """A site's declaration change starts the next cycle without its interval."""
        from market_storefront.services.publication_loop import (
            publication_loop,
            wake_publication_loop,
        )

        cycles: list[bool] = []
        ran = asyncio.Event()

        async def _cycle(*, dry_run):
            cycles.append(dry_run)
            ran.set()
            return {}

        async with _registered(partial(publication_loop, _cycle), lifecycle.PUBLICATION):
            await asyncio.wait_for(ran.wait(), timeout=_PROMPTLY)
            ran.clear()
            wake_publication_loop()
            await asyncio.wait_for(ran.wait(), timeout=_PROMPTLY)

        assert cycles == [False, False]

    async def test_capacity_events_poller(self, monkeypatch):
        """The aggregate keeps gating under its own name after starting its fan-out.

        It performs no polling itself -- the per-site pollers do that inside the
        kit -- but it stays registered so a storefront with no site configured
        still has a capacity loop to report, and so the admin advance route has
        a name to address. Its fan-out never returns, so an aggregate that
        awaited it would gate exactly once and never observe a pause.
        """
        from market_storefront.services import capacity_client as cc

        started = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        name = lifecycle.CAPACITY_EVENTS_POLLER
        async with _registered(partial(cc.capacity_events_poller_loop, object()), name):
            # The fan-out starts only once the aggregate has passed its first
            # gate, so being paused now requires a further gate read.
            await asyncio.wait_for(started.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        assert states == {name: "paused"}

    async def test_capacity_events_poller_declares_a_gate_per_site(self, monkeypatch):
        """Each site acknowledges for itself, through the wait it is given.

        The pollers fan out across configured sites. Sharing one gate between
        them means whichever site reaches its gate first satisfies the
        acknowledgement for every other, so a pause can return `paused` while a
        second site's cycle is still writing -- optimistic in the single
        direction the pause exists to rule out. Each site is a declared gate,
        which is what makes the pause wait for it.
        """
        from market_storefront.services import capacity_client as cc

        started = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                gates = [paused(site) for site in ("site-a", "site-b")]
                started.set()
                while True:
                    for gate in gates:
                        gate()
                    await wait(_LONG_INTERVAL)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        async with _registered(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
        ):
            await asyncio.wait_for(started.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        for site in ("site-a", "site-b"):
            name = lifecycle.capacity_site_loop_name(site)
            assert name in lifecycle.controller()._declared, (
                f"{site} has no declared gate, so it cannot be waited on"
            )
            assert states[name] == "paused", f"{site} did not acknowledge its own gate"

    async def test_a_second_site_still_working_is_not_reported_paused(self, monkeypatch):
        """The reason per-site gates exist.

        One site parks at its gate; the other never reaches one. A pause must
        report the capacity pollers as still stopping, because one of them is.
        """
        from market_storefront.services import capacity_client as cc

        site_a = lifecycle.capacity_site_loop_name("site-a")
        site_b = lifecycle.capacity_site_loop_name("site-b")
        declared = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                gate_a = paused("site-a")
                # site-b's gate is bound -- so it is declared and waited on --
                # but never consulted, standing in for a cycle still in flight.
                paused("site-b")
                declared.set()
                while True:
                    gate_a()
                    await wait(_LONG_INTERVAL)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        async with _registered(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
        ):
            await asyncio.wait_for(declared.wait(), timeout=_PROMPTLY)
            controller = lifecycle.controller()
            controller.request_pause(True)
            await asyncio.wait_for(controller._acked[site_a].wait(), timeout=_PROMPTLY)
            states = lifecycle.loop_states()

        assert states[site_a] == "paused"
        assert states[site_b] == "starting", (
            "a site that never reached its gate must not be reported as stopped "
            "on the strength of another site's acknowledgement"
        )
