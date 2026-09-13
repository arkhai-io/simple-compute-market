"""Each advance route reports a loop name the lifecycle registry knows.

A loop's name is spelled in three places: the registration in `startup.py`, the
gate call in the loop body, and the advance route's response. The first two are
covered by `test_loop_gate_wiring.py`; this covers the third, which had already
drifted -- the route was called `claims` and returned `claims_engine` after the
claims engine became settlement servicing, so a caller advancing that loop
asserted against a name nothing used any more.

The response name is load-bearing, not cosmetic: a caller advances a loop and
then reads `loop_states()` to see whether it is held, and a reported name that
is not a registered one cannot be found there.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# `server` first: it and `admin_controller` import each other, and importing
# the controller from a cold interpreter hits that cycle part-way. The app
# module resolves it, which is the order every other test here gets for free by
# importing through the app.
from market_storefront import lifecycle, server  # noqa: F401
from market_storefront.controllers import admin_controller as ac


def _registered_names() -> set[str]:
    """Every name the lifecycle module defines for a loop."""
    return {
        lifecycle.NEGOTIATION_WATCHDOG,
        lifecycle.SETTLEMENT_SERVICING,
        lifecycle.FULFILLMENT_RESUME,
        lifecycle.CAPACITY_EVENTS_POLLER,
        lifecycle.SITE_PROJECTION_POLLER,
    }


class TestAdvanceRoutesReportRegisteredNames:
    async def test_settlement_servicing(self, monkeypatch):
        swept = {"n": 0}

        class _Worker:
            async def run_once(self):
                swept["n"] += 1
                return 3

        # Patched on the container module, not on the controller: the handler
        # imports it inside the function, so a name bound on the controller is
        # never consulted.
        import market_storefront.container as container

        monkeypatch.setattr(
            container, "resolved_settlement_composition",
            SimpleNamespace(worker=_Worker()), raising=False,
        )
        controller = object.__new__(ac.AdminController)
        result = await ac.AdminController.run_settlement_servicing_cycle(controller)

        assert result["loop"] in _registered_names(), (
            f"{result['loop']!r} is not a registered loop name, so a caller "
            "cannot find it in loop_states() after advancing it"
        )
        assert result["loop"] == lifecycle.SETTLEMENT_SERVICING
        assert result["processed"] == 3, "the sweep's own count must reach the caller"
        assert swept["n"] == 1, "the advance must run exactly one cycle"

    async def test_fulfillment_resume(self, monkeypatch):
        calls = {"n": 0}

        async def _sweep(*, sqlite_client):
            calls["n"] += 1

        monkeypatch.setattr(
            "market_storefront.services.fulfillment_resume_runtime."
            "resume_incomplete_fulfillments_once",
            _sweep,
        )
        controller = object.__new__(ac.AdminController)
        controller._db = object()
        result = await ac.AdminController.run_fulfillment_resume_cycle(controller)

        assert result["loop"] in _registered_names()
        assert result["loop"] == lifecycle.FULFILLMENT_RESUME
        assert calls["n"] == 1

    async def test_site_projections(self, monkeypatch):
        async def _load(_client):
            return None

        monkeypatch.setattr(
            "market_storefront.services.site_projection_cache.load_site_projections",
            _load,
        )
        monkeypatch.setattr(
            "market_storefront.services.site_projection_cache."
            "projection_status_summary",
            lambda: {"default": {"capacity_buckets": {"state": "loaded"}}},
        )
        controller = object.__new__(ac.AdminController)
        controller._db = object()
        result = await ac.AdminController.run_site_projection_cycle(controller)

        assert result["loop"] in _registered_names()
        assert result["loop"] == lifecycle.SITE_PROJECTION_POLLER
        assert result["sites"], "the pull's per-site state is what proves it landed"


class TestTheRouteAliasNamesTheLoop:
    def test_every_advance_route_is_in_the_declared_mapping(self):
        """A route path is a fourth spelling, and it drifted once already.

        `claims` named an engine that no longer existed, which is how the
        mismatch survived a rename. The mapping is the one declaration both the
        routes and the responses read, so this checks the routes have not grown
        past it.
        """
        source = (ac.__file__ and open(ac.__file__).read()) or ""
        prefix = '"/lifecycle/'
        aliases = {
            line.strip()[len(prefix):-len('/run-cycle",')]
            for line in source.splitlines()
            if line.strip().startswith(prefix)
            and line.strip().endswith('/run-cycle",')
        }
        assert aliases, "no advance routes found; this test looks in the wrong place"
        undeclared = aliases - set(ac.ADVANCE_LOOP_NAMES)
        assert not undeclared, (
            f"these advance routes are not in ADVANCE_LOOP_NAMES: "
            f"{sorted(undeclared)}. A route that names no loop is how `claims` "
            "outlived the claims engine."
        )

    def test_the_mapping_only_names_registered_loops(self):
        """Every mapped value must be a name `loop_states()` can report.

        A caller advances a loop and then reads its state; a name the registry
        does not know cannot be found there.
        """
        unknown = set(ac.ADVANCE_LOOP_NAMES.values()) - _registered_names()
        assert not unknown, (
            f"ADVANCE_LOOP_NAMES maps to unregistered names: {sorted(unknown)}"
        )
