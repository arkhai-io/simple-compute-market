"""Every loop the storefront registers acknowledges under that same name.

`test_lifecycle_registry.py` proves the gate mechanism against a synthetic loop.
It cannot prove that a production loop uses it, and for four of the five loops it
did not: they read the pause flag through a separate unacknowledged accessor, so
`await_quiescence` never saw them and every pause reported them as still
stopping, indefinitely. That defect passed the whole unit suite, three closeout
passes, and a plan note asserting "five gated loops".

The gap is a wiring one, so the check is a wiring one. It drives each loop's real
coroutine with its dependencies stubbed and asserts the acknowledgement arrives
under the name `startup.py` registers — which also catches a name that drifts
between the two, since an acknowledgement under a name nobody waits on leaves the
registered loop unacknowledged exactly as if it never gated.

The two loops whose bodies live in `core_storefront` are covered here through the
predicate the composition supplies, which is the seam that was wrong.
"""

from __future__ import annotations

import asyncio

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
    loop gates against a registry shaped like the running storefront's — a gate
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


class TestRegisteredNamesAreTheGatedNames:
    def test_startup_registers_exactly_the_named_loops(self):
        """The constants are the contract between registration and gating.

        If a loop is added without a constant, the two ends can disagree again
        and nothing else in this file will notice, because it only checks the
        loops it knows to check.
        """
        from market_storefront import startup

        source = (
            (startup.__file__ and open(startup.__file__).read()) or ""
        )
        for constant in (
            "NEGOTIATION_WATCHDOG",
            "CLAIMS_ENGINE",
            "FULFILLMENT_RESUME",
            "CAPACITY_EVENTS_POLLER",
            "SITE_PROJECTION_POLLER",
        ):
            assert f"name={constant}" in source, (
                f"{constant} is no longer used to register its loop; a literal "
                "name here can drift from the one the loop body gates under"
            )


class TestEachProductionLoopAcknowledges:
    async def test_negotiation_watchdog(self, monkeypatch):
        from market_storefront import negotiation_watchdog as nw

        monkeypatch.setattr(nw, "SQLiteClient", lambda **_: object())
        monkeypatch.setattr(nw.settings, "negotiation_watchdog_interval", 0.01)
        # The sweep is separately covered; this asserts the gate is reached, and
        # a sweep that ran would only add I/O this test has no need of.
        async def _no_sweep(_client):
            return 0

        monkeypatch.setattr(nw, "_watchdog_tick", _no_sweep)

        await _run_briefly(nw.watchdog_loop, lifecycle.NEGOTIATION_WATCHDOG)

        assert _acknowledged(lifecycle.NEGOTIATION_WATCHDOG)

    async def test_negotiation_watchdog_gates_before_its_startup_delay_elapses(
        self, monkeypatch
    ):
        """The delay holds the sweep, not the gate.

        Its purpose is to avoid measuring freshly created threads against a clock
        that has not caught up, which constrains when a sweep may run. Holding the
        gate as well made the loop unobservable for the whole window — and the
        first pause of an end-to-end run lands inside it.
        """
        from market_storefront import negotiation_watchdog as nw

        swept: list[int] = []

        async def _sweep(_client):
            swept.append(1)
            return 0

        monkeypatch.setattr(nw, "SQLiteClient", lambda **_: object())
        monkeypatch.setattr(nw.settings, "negotiation_watchdog_interval", 0.01)
        monkeypatch.setattr(nw, "_watchdog_tick", _sweep)
        monkeypatch.setattr(nw, "STARTUP_SWEEP_DELAY_SECONDS", 30.0)

        await _run_briefly(nw.watchdog_loop, lifecycle.NEGOTIATION_WATCHDOG)

        assert _acknowledged(lifecycle.NEGOTIATION_WATCHDOG), (
            "the watchdog did not reach its gate during its startup delay, so a "
            "pause requested in that window cannot be observed"
        )
        assert not swept, "the startup delay no longer holds the sweep"

    async def test_fulfillment_resume(self, monkeypatch):
        from market_storefront.services import fulfillment_resume_runtime as frr

        monkeypatch.setattr(frr, "SQLiteClient", lambda _path: object())
        monkeypatch.setattr(
            frr, "get_sqlite_client", lambda: type("_S", (), {"db_path": ":memory:"})()
        )

        async def _no_sweep(**_kwargs):
            return 0

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _no_sweep)

        await _run_briefly(frr.fulfillment_resume_loop, lifecycle.FULFILLMENT_RESUME)

        assert _acknowledged(lifecycle.FULFILLMENT_RESUME)

    async def test_fulfillment_resume_survives_a_failing_sweep(self, monkeypatch):
        """A raising cycle must not end the loop.

        Nothing restarts one, so a single bad sweep would otherwise stop escrow
        convergence for the life of the process — and, after this change, fail
        liveness and replace the pod for a transient error.
        """
        from market_storefront.services import fulfillment_resume_runtime as frr

        monkeypatch.setattr(frr, "SQLiteClient", lambda _path: object())
        monkeypatch.setattr(
            frr, "get_sqlite_client", lambda: type("_S", (), {"db_path": ":memory:"})()
        )
        calls: list[int] = []

        async def _always_fails(**_kwargs):
            calls.append(1)
            raise RuntimeError("sweep failed")

        monkeypatch.setattr(frr, "resume_incomplete_fulfillments_once", _always_fails)

        # A stand-in settings object rather than an attribute on the dynaconf
        # singleton: the loop reads its interval with a `getattr` default, so the
        # key is absent from the real settings, and monkeypatch restores an
        # absent attribute by deleting it — which dynaconf rejects for a key it
        # never held.
        class _Intervals:
            fulfillment_resume_sweep_interval = 0.01

        monkeypatch.setattr(
            "market_storefront.utils.config.settings", _Intervals()
        )

        await _run_briefly(frr.fulfillment_resume_loop, lifecycle.FULFILLMENT_RESUME)

        assert len(calls) > 1, (
            "the loop stopped after a failing sweep instead of continuing"
        )

    async def test_claims_engine(self, monkeypatch):
        """Covers the `paused` predicate the core engine is composed with.

        The engine's loop body is in `core_storefront` and cannot name a loop this
        package registers, so the binding is supplied at composition — which is
        precisely the seam that read the flag without acknowledging.
        """
        from market_storefront.services import claims_runtime as cr

        class _Engine:
            async def run(self, interval_seconds=30.0, *, paused=None):
                while True:
                    if paused is not None and paused():
                        await asyncio.sleep(interval_seconds)
                        continue
                    await asyncio.sleep(interval_seconds)

        monkeypatch.setattr(cr, "SQLiteClient", None, raising=False)
        monkeypatch.setattr(cr, "build_claims_engine", lambda _db: _Engine())
        monkeypatch.setattr(
            "market_storefront.utils.sqlite_client.SQLiteClient",
            lambda **_: object(),
        )

        await _run_briefly(cr.claims_engine_loop, lifecycle.CLAIMS_ENGINE)

        assert _acknowledged(lifecycle.CLAIMS_ENGINE)

    async def test_capacity_events_poller(self, monkeypatch):
        """Covers the other core-bodied predicate, through the no-sites path.

        With no site configured the loop gates and idles rather than returning —
        `gather()` over nothing would end the loop, and an ended loop now fails
        liveness, which a storefront with no site authority does not deserve.
        """
        from market_storefront.services import capacity_client as cc

        monkeypatch.setattr(cc, "build_capacity_client", lambda _f: object())
        monkeypatch.setattr(cc, "remote_site_clients", lambda _a: {})

        await _run_briefly(cc.capacity_events_poller_loop, lifecycle.CAPACITY_EVENTS_POLLER)

        assert _acknowledged(lifecycle.CAPACITY_EVENTS_POLLER)

    async def test_capacity_events_poller_registers_a_loop_per_site(
        self, monkeypatch
    ):
        """Each site acknowledges for itself, or one can answer for another.

        The pollers fan out across configured sites. Sharing one gate between
        them means whichever site reaches its gate first satisfies the
        acknowledgement for every other, so a pause can return `paused` while a
        second site's cycle is still writing — optimistic in the single direction
        the pause exists to rule out.
        """
        from market_storefront.services import capacity_client as cc

        polled: list[str] = []

        async def _fake_site_poller(
            _aggregate, name, _client, _interval, *, full_reconcile=None,
            paused=None,
        ):
            while True:
                polled.append(name)
                if paused is not None:
                    paused()
                await asyncio.sleep(0.01)

        monkeypatch.setattr(cc, "build_capacity_client", lambda _f: object())
        monkeypatch.setattr(
            cc, "remote_site_clients",
            lambda _a: {"site-a": object(), "site-b": object()},
        )
        monkeypatch.setattr(cc, "site_events_poller", _fake_site_poller)

        await _run_briefly(
            cc.capacity_events_poller_loop, lifecycle.CAPACITY_EVENTS_POLLER
        )

        for site in ("site-a", "site-b"):
            name = lifecycle.capacity_site_loop_name(site)
            assert name in lifecycle._HANDLES, (
                f"{site} has no registered loop, so it cannot be waited on"
            )
            assert _acknowledged(name), (
                f"{site} never acknowledged its own gate"
            )

    async def test_a_second_site_still_working_is_not_reported_paused(
        self, monkeypatch
    ):
        """The reviewer's case, and the reason per-site registration exists.

        One site parks at its gate; the other never reaches one. A pause must
        report the capacity pollers as still stopping, because one of them is.
        """
        from market_storefront.services import capacity_client as cc

        async def _fake_site_poller(
            _aggregate, name, _client, _interval, *, full_reconcile=None,
            paused=None,
        ):
            while True:
                if name == "site-a" and paused is not None:
                    paused()
                await asyncio.sleep(0.01)

        monkeypatch.setattr(cc, "build_capacity_client", lambda _f: object())
        monkeypatch.setattr(
            cc, "remote_site_clients",
            lambda _a: {"site-a": object(), "site-b": object()},
        )
        monkeypatch.setattr(cc, "site_events_poller", _fake_site_poller)

        task = asyncio.create_task(cc.capacity_events_poller_loop())
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

    async def test_site_projection_poller(self, monkeypatch):
        from market_storefront.services import site_projection_cache as spc

        async def _noop():
            return None

        monkeypatch.setattr(spc, "load_site_projections", _noop)

        await _run_briefly(spc.site_projection_poller_loop, lifecycle.SITE_PROJECTION_POLLER)

        assert _acknowledged(lifecycle.SITE_PROJECTION_POLLER)
