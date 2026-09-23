"""Every loop the storefront registers acknowledges under that same name.

`test_lifecycle_registry.py` proves the gate mechanism against a synthetic loop.
It cannot prove that a production loop uses it, and for four of the five loops it
once did not: they read the pause flag through a separate unacknowledged
accessor, so `await_quiescence` never saw them and every pause reported them as
still stopping, indefinitely. That defect passed the whole unit suite, three
closeout passes, and a plan note asserting "five gated loops".

The gap is a wiring one, so the check is a wiring one. It drives each loop's real
coroutine with its dependencies stubbed and asserts the acknowledgement arrives
under the name `startup.py` registers -- which also catches a name that drifts
between the two, since an acknowledgement under a name nobody waits on leaves the
registered loop unacknowledged exactly as if it never gated.

Adapted from the original: two loop bodies moved out of this package since it was
written. The negotiation watchdog and the settlement servicing sweep now live in
`kit/` and are driven by an injected predicate, so they are covered through that
predicate -- which is the same seam the original covered for the core-bodied
loops, and the seam that was wrong. Capacity polling's per-site fan-out also
moved into `kit/capacity-publication`, so the storefront holds no task per site;
the per-site cases assert against declared gate names instead of task handles.
The property asserted is unchanged: each site acknowledges for itself, and one
cannot answer for another.
"""

from __future__ import annotations

import asyncio
from functools import partial

import pytest

from market_storefront import lifecycle, server


@pytest.fixture(autouse=True)
async def _clean_registry():
    server._LOOPS_PAUSED = False
    lifecycle.reset_for_tests()
    yield
    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False
    await asyncio.sleep(0)


async def _run_briefly(coro_factory, name: str, *, seconds: float = 0.2) -> None:
    """Run a loop body as a registered loop, then cancel it.

    The handle is placed in the registry under the name `startup.py` uses, so the
    loop gates against a registry shaped like the running storefront's -- a gate
    call naming something unregistered is a distinct failure this file also
    tests for, and it should not be the ambient condition of every case here.

    Cancellation is how the loop ends in this test, never how a pause works:
    these loops are not cancelled in production. It is only the test's way of
    reclaiming a coroutine designed never to return.
    """
    task = asyncio.create_task(coro_factory())
    lifecycle._HANDLES[name] = task
    try:
        await asyncio.sleep(seconds)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _acknowledged(name: str) -> bool:
    """Whether this exact name reached its gate at least once."""
    return bool(lifecycle._GATE_CALLS.get(name))


def _gate_calls(name: str) -> int:
    """How many times this name reached its gate.

    Reaching a gate once is enough to be acknowledged and not enough to ever
    observe a pause: a loop that gates and then blocks forever inside a call
    reports `running` and never comes back, so every pause reports it
    `pausing` until the bounded wait expires. Both loops below did exactly
    that -- one awaited a call that never returns, the other slept its startup
    delay after gating.
    """
    return int(lifecycle._GATE_CALLS.get(name, 0))


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


class TestEachProductionLoopAcknowledges:
    async def test_negotiation_watchdog(self, monkeypatch):
        """Covers the predicate the watchdog is composed with.

        Its body is in `kit/storefront` and cannot name a loop this package
        registers, so the binding is supplied at composition -- precisely the
        kind of seam that read the flag without acknowledging.
        """
        from market_storefront_kit import negotiation_watchdog as nw

        async def _no_sweep(_repository, _policy, **_kwargs):
            return 0

        monkeypatch.setattr(nw, "sweep_stale_negotiations", _no_sweep)
        policy = nw.NegotiationWatchdogPolicy(
            timeout_seconds=1800.0, interval_seconds=0.01
        )

        await _run_briefly(
            partial(
                nw.run_negotiation_watchdog,
                object(),
                policy,
                paused=lifecycle.loop_gate(lifecycle.NEGOTIATION_WATCHDOG),
            ),
            lifecycle.NEGOTIATION_WATCHDOG,
        )

        assert _acknowledged(lifecycle.NEGOTIATION_WATCHDOG)

    async def test_negotiation_watchdog_gates_before_its_startup_delay_elapses(
        self, monkeypatch
    ):
        """The delay holds the sweep, not the gate.

        Its purpose is to avoid measuring freshly created threads against a
        clock that has not caught up, which constrains when a sweep may run.
        Holding the gate as well made the loop unobservable for the whole
        window -- and the first pause of an end-to-end run lands inside it.
        """
        from market_storefront_kit import negotiation_watchdog as nw

        swept: list[int] = []

        async def _sweep(_repository, _policy, **_kwargs):
            swept.append(1)
            return 0

        monkeypatch.setattr(nw, "sweep_stale_negotiations", _sweep)
        policy = nw.NegotiationWatchdogPolicy(
            timeout_seconds=1800.0,
            interval_seconds=0.01,
            initial_delay_seconds=30.0,
        )

        await _run_briefly(
            partial(
                nw.run_negotiation_watchdog,
                object(),
                policy,
                paused=lifecycle.loop_gate(lifecycle.NEGOTIATION_WATCHDOG),
            ),
            lifecycle.NEGOTIATION_WATCHDOG,
        )

        assert _acknowledged(lifecycle.NEGOTIATION_WATCHDOG), (
            "the watchdog did not reach its gate during its startup delay, so "
            "a pause requested in that window cannot be observed"
        )
        assert _gate_calls(lifecycle.NEGOTIATION_WATCHDOG) > 1, (
            "the watchdog reached its gate once and then stopped cycling for "
            "the length of its startup delay; a pause requested after that "
            "first gate call is not observed until the delay elapses"
        )
        assert not swept, "the startup delay no longer holds the sweep"

    async def test_settlement_servicing(self, monkeypatch):
        """Covers the settlement sweep's predicate.

        The claims engine this replaced carried the same `paused` parameter;
        the sweep is the same periodic work under the name the neutrality
        redesign gave it.
        """
        from market_settlement_runtime.servicing import SettlementServicingWorker

        class _Repo:
            async def list_due_settlement_obligations(self, **_kwargs):
                return []

        worker = SettlementServicingWorker(
            runtime=object(),
            repository=_Repo(),
            worker_id="test",
            interval_seconds=0.01,
        )

        await _run_briefly(
            partial(
                worker.run,
                paused=lifecycle.loop_gate(lifecycle.SETTLEMENT_SERVICING),
            ),
            lifecycle.SETTLEMENT_SERVICING,
        )

        assert _acknowledged(lifecycle.SETTLEMENT_SERVICING)

    async def test_fulfillment_resume(self, monkeypatch):
        from market_storefront.services import fulfillment_resume_runtime as frr

        async def _no_sweep(**_kwargs):
            return 0

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _no_sweep)

        class _Intervals:
            fulfillment_resume_sweep_interval = 0.01

        monkeypatch.setattr("market_storefront.utils.config.settings", _Intervals())

        await _run_briefly(
            partial(frr.fulfillment_resume_loop, object()),
            lifecycle.FULFILLMENT_RESUME,
        )

        assert _acknowledged(lifecycle.FULFILLMENT_RESUME)

    async def test_fulfillment_resume_survives_a_failing_sweep(self, monkeypatch):
        """A raising cycle must not end the loop.

        Nothing restarts one, so a single bad sweep would otherwise stop escrow
        convergence for the life of the process -- and fail liveness, replacing
        the pod for a transient error.
        """
        from market_storefront.services import fulfillment_resume_runtime as frr

        calls: list[int] = []

        async def _always_fails(**_kwargs):
            calls.append(1)
            raise RuntimeError("sweep failed")

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _always_fails)

        # A stand-in settings object rather than an attribute on the dynaconf
        # singleton: the loop reads its interval with a `getattr` default, so the
        # key is absent from the real settings, and monkeypatch restores an
        # absent attribute by deleting it -- which dynaconf rejects for a key it
        # never held.
        class _Intervals:
            fulfillment_resume_sweep_interval = 0.01

        monkeypatch.setattr("market_storefront.utils.config.settings", _Intervals())

        await _run_briefly(
            partial(frr.fulfillment_resume_loop, object()),
            lifecycle.FULFILLMENT_RESUME,
        )

        assert len(calls) > 1, (
            "the loop stopped after a failing sweep instead of continuing"
        )

    async def test_site_projection_poller(self, monkeypatch):
        from market_storefront.services import site_projection_cache as spc

        async def _noop(_client):
            return None

        monkeypatch.setattr(spc, "load_site_projections", _noop)

        await _run_briefly(
            partial(spc.site_projection_poller_loop, object()),
            lifecycle.SITE_PROJECTION_POLLER,
        )

        assert _acknowledged(lifecycle.SITE_PROJECTION_POLLER)

    async def test_publication_loop_gates_before_any_cycle(self):
        """Held, the publication loop reaches its gate and runs no cycle."""
        from market_storefront.services.publication_loop import publication_loop

        cycles: list[bool] = []

        async def _cycle(*, dry_run):
            cycles.append(dry_run)
            return {}

        server._LOOPS_PAUSED = True
        await _run_briefly(
            partial(publication_loop, _cycle),
            lifecycle.PUBLICATION,
        )

        assert _acknowledged(lifecycle.PUBLICATION)
        assert cycles == []

    async def test_publication_loop_runs_real_cycles_when_not_held(self):
        from market_storefront.services.publication_loop import publication_loop

        cycles: list[bool] = []

        async def _cycle(*, dry_run):
            cycles.append(dry_run)
            return {}

        await _run_briefly(
            partial(publication_loop, _cycle),
            lifecycle.PUBLICATION,
        )

        assert cycles and set(cycles) == {False}

    async def test_capacity_events_poller(self, monkeypatch):
        """The aggregate loop gates under its own name.

        It performs no polling itself -- the per-site pollers do that inside the
        kit -- but it stays registered so a storefront with no site configured
        still has a capacity loop to report, and so the admin advance route has
        a name to address.
        """
        from market_storefront.services import capacity_client as cc

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None):
                while True:
                    await asyncio.sleep(interval_seconds)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())

        # Run past one aggregate cadence: the loop does no work, so its gate
        # interval is longer than the other loops' and a shorter window would
        # only ever see the first call.
        await _run_briefly(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
            seconds=cc._AGGREGATE_GATE_SECONDS * 2.5,
        )

        assert _acknowledged(lifecycle.CAPACITY_EVENTS_POLLER)
        assert _gate_calls(lifecycle.CAPACITY_EVENTS_POLLER) > 1, (
            "the aggregate gated once and then sat inside poll_events, which "
            "never returns; it must run the fan-out as a task and keep gating"
        )

    async def test_capacity_events_poller_declares_a_gate_per_site(
        self, monkeypatch
    ):
        """Each site acknowledges for itself, or one can answer for another.

        The pollers fan out across configured sites. Sharing one gate between
        them means whichever site reaches its gate first satisfies the
        acknowledgement for every other, so a pause can return `paused` while a
        second site's cycle is still writing -- optimistic in the single
        direction the pause exists to rule out.

        The fan-out lives in the kit now, so each site is a *declared* gate
        rather than a registered task. Declaring is what makes
        `await_quiescence` wait for it; the guarantee is the same.
        """
        from market_storefront.services import capacity_client as cc

        polled: list[str] = []

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None):
                gates = {
                    site: (paused(site) if paused is not None else None)
                    for site in ("site-a", "site-b")
                }
                while True:
                    for site, gate in gates.items():
                        polled.append(site)
                        if gate is not None:
                            gate()
                    await asyncio.sleep(0.01)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())

        await _run_briefly(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
        )

        for site in ("site-a", "site-b"):
            name = lifecycle.capacity_site_loop_name(site)
            assert name in lifecycle._DECLARED, (
                f"{site} has no declared gate, so it cannot be waited on"
            )
            assert _acknowledged(name), f"{site} never acknowledged its own gate"

    async def test_a_second_site_still_working_is_not_reported_paused(
        self, monkeypatch
    ):
        """The reason per-site gates exist.

        One site parks at its gate; the other never reaches one. A pause must
        report the capacity pollers as still stopping, because one of them is.
        """
        from market_storefront.services import capacity_client as cc

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None):
                gate_a = paused("site-a") if paused is not None else None
                # site-b's gate is bound -- so it is declared and waited on --
                # but never consulted, standing in for a cycle still in flight.
                if paused is not None:
                    paused("site-b")
                while True:
                    if gate_a is not None:
                        gate_a()
                    await asyncio.sleep(0.01)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())

        task = asyncio.create_task(cc.capacity_events_poller_loop(object()))
        lifecycle._HANDLES[lifecycle.CAPACITY_EVENTS_POLLER] = task
        try:
            await asyncio.sleep(0.1)
            server._LOOPS_PAUSED = True
            await lifecycle.await_quiescence(0.05)
            states = lifecycle.loop_states()
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        assert states[lifecycle.capacity_site_loop_name("site-a")] == "paused"
        assert states[lifecycle.capacity_site_loop_name("site-b")] == "starting", (
            "a site that never reached its gate must not be reported as stopped "
            "on the strength of another site's acknowledgement"
        )
