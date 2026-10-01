"""Each registered loop step reports a loop name the lifecycle controller knows.

A loop's name is spelled where `startup.py` registers it, where the loop body
gates on it, and in what its step reports. The first two are covered by
`test_loop_gate_wiring.py`; this covers the third, which had already drifted
once -- a route named an engine that no longer existed and reported a name
nothing used any more.

The response name is load-bearing, not cosmetic: a caller advances a loop and
then reads the loop states to see whether it is held, and a reported name that
is not a registered one cannot be found there.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# `server` first: it and the admin controller import each other, and importing
# the controller from a cold interpreter hits that cycle part-way. The app module
# resolves it, which is the order every other test here gets by importing
# through the app.
from market_storefront import lifecycle, server  # noqa: F401
from market_storefront.controllers import admin_controller  # noqa: F401 - registers the steps


def _loop_names() -> set[str]:
    """Every name the lifecycle module defines for a loop."""
    return {
        lifecycle.NEGOTIATION_WATCHDOG,
        lifecycle.SETTLEMENT_SERVICING,
        lifecycle.FULFILLMENT_RESUME,
        lifecycle.CAPACITY_EVENTS_POLLER,
        lifecycle.SITE_PROJECTION_POLLER,
        lifecycle.PUBLICATION,
    }


async def _advance(route: str):
    return await lifecycle.controller().run_cycle(route)


class TestStepsReportRegisteredNames:
    async def test_settlement_servicing(self, monkeypatch):
        swept = {"n": 0}

        class _Worker:
            async def run_once(self):
                swept["n"] += 1
                return 3

        import market_storefront.container as container

        monkeypatch.setattr(
            container, "resolved_settlement_composition",
            SimpleNamespace(worker=_Worker()), raising=False,
        )
        result = await _advance("settlement-servicing")

        assert result["loop"] == lifecycle.SETTLEMENT_SERVICING
        assert result["processed"] == 3, "the sweep's own count must reach the caller"
        assert swept["n"] == 1, "the advance must run exactly one cycle"

    async def test_settlement_servicing_before_composition_is_unavailable(self, monkeypatch):
        from market_storefront_kit import LifecycleRouteError

        import market_storefront.container as container

        monkeypatch.setattr(container, "resolved_settlement_composition", None, raising=False)
        with pytest.raises(LifecycleRouteError) as raised:
            await _advance("settlement-servicing")
        assert raised.value.status_code == 503

    async def test_fulfillment_resume(self, monkeypatch):
        calls = {"n": 0}

        async def _sweep(*, sqlite_client):
            calls["n"] += 1

        import market_storefront.container as container

        monkeypatch.setattr(container, "resolved_sqlite_client", object(), raising=False)
        monkeypatch.setattr(
            "market_storefront.lifecycle_steps.resume_incomplete_fulfillments_once",
            _sweep,
        )
        result = await _advance("fulfillment-resume")

        assert result["loop"] == lifecycle.FULFILLMENT_RESUME
        assert calls["n"] == 1

    async def test_site_projections(self, monkeypatch):
        async def _load(_client):
            return None

        import market_storefront.container as container

        monkeypatch.setattr(container, "resolved_sqlite_client", object(), raising=False)
        monkeypatch.setattr(
            "market_storefront.lifecycle_steps.load_site_projections",
            _load,
        )
        monkeypatch.setattr(
            "market_storefront.lifecycle_steps.projection_status_summary",
            lambda: {"default": {"capacity_buckets": {"state": "loaded"}}},
        )
        result = await _advance("site-projections")

        assert result["loop"] == lifecycle.SITE_PROJECTION_POLLER
        assert result["sites"], "the pull's per-site state is what proves it landed"

    async def test_negotiation_watchdog(self, monkeypatch):
        calls = {"n": 0}

        async def _sweep(repository, policy, **_kwargs):
            calls["n"] += 1
            return 2

        import market_storefront.container as container

        monkeypatch.setattr(container, "resolved_sqlite_client", object(), raising=False)
        monkeypatch.setattr(
            "market_storefront.lifecycle_steps.sweep_stale_negotiations", _sweep
        )
        result = await _advance("negotiation-watchdog")

        assert result == {"loop": lifecycle.NEGOTIATION_WATCHDOG, "abandoned": 2}
        assert calls["n"] == 1


class TestEveryRouteNamesARegisteredLoop:
    def test_every_loop_has_a_step(self):
        """A loop the pause holds that an operator cannot step stalls a scenario."""
        assert set(lifecycle.controller().step_routes().values()) == _loop_names()

    def test_routes_name_only_registered_loops(self):
        unknown = set(lifecycle.controller().step_routes().values()) - _loop_names()
        assert not unknown, f"steps report unregistered loop names: {sorted(unknown)}"

    def test_route_names_are_the_published_ones(self):
        """The route names are part of the wire contract callers already use."""
        assert set(lifecycle.controller().step_routes()) == {
            "negotiation-watchdog",
            "settlement-servicing",
            "fulfillment-resume",
            "site-projections",
            "capacity-events",
            "publication",
        }


class TestPublicationRoutes:
    @pytest.mark.parametrize("dry_run", [True, False])
    async def test_each_route_runs_exactly_the_timers_cycle(self, monkeypatch, dry_run):
        calls: list[bool] = []

        async def _cycle(*, dry_run):
            calls.append(dry_run)
            return {"loop": "publication", "dry_run": dry_run, "actions": [], "counts": {}}

        monkeypatch.setattr(
            "market_storefront.lifecycle_steps.run_publication_cycle_once",
            _cycle,
        )
        loops = lifecycle.controller()
        result = await (loops.dry_run("publication") if dry_run else loops.run_cycle("publication"))

        assert calls == [dry_run]
        assert result["loop"] == lifecycle.PUBLICATION
