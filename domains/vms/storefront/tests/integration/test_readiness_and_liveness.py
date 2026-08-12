"""Readiness, liveness, and diagnosis are three answers, not one.

A storefront serves its routes as soon as they are mounted, which is earlier than
its timer loops begin cycling. Pointing every probe at one route made those two
states indistinguishable from outside the process, and a scenario could pause a
storefront whose loops had not started and be told they had stopped.

The split these tests pin:

* `/health` — is this process worth keeping. Fails only for a loop that ended on
  its own, because nothing restarts one and replacing the pod is the only
  recovery available.
* `/ready` — can it be relied on. Also fails while a loop has not begun cycling,
  which resolves by itself and should drain traffic rather than restart anything.
* `/api/v1/system/status` — never fails, and reports per-loop state, because it
  is read precisely when one of the other two is failing.

Driven through the real lifecycle registry rather than an injected provider: the
question here is whether the routes react to what the loops are actually doing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
import market_storefront.server as _server
from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront import lifecycle
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient

LOOP = "claims_engine"


@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "readiness_test.db"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_registry() -> AsyncIterator[None]:
    _server._LOOPS_PAUSED = False
    lifecycle.reset_for_tests()
    yield
    lifecycle.reset_for_tests()
    _server._LOOPS_PAUSED = False
    await asyncio.sleep(0)


@pytest_asyncio.fixture
async def http(db) -> AsyncIterator[httpx.AsyncClient]:
    _container.resolved_sqlite_client = db
    _container.resolved_system_service = SystemService(sqlite_client=db)

    app = FastAPI()
    app.include_router(system_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client

    _container.resolved_sqlite_client = None
    _container.resolved_system_service = None


async def _slow_to_start_loop() -> None:
    """A registered loop that has not reached its gate yet.

    Sleeps long enough that it cannot gate during a request: any `await` in the
    handler hands control back to the event loop, so a loop that gates on its
    first step is already `running` by the time a probe reads its state, and the
    starting window cannot be observed at all.
    """
    await asyncio.sleep(30)
    while True:
        lifecycle.gate(LOOP)
        await asyncio.sleep(0.001)


async def _cycling_loop() -> None:
    while True:
        if lifecycle.gate(LOOP):
            await asyncio.sleep(0.001)
            continue
        await asyncio.sleep(0.001)


def _register(factory) -> None:
    lifecycle.start_registered_loop(
        StorefrontBackgroundTask(name=LOOP, task_factory=factory)
    )


class TestAStorefrontThatHasNotFinishedStarting:
    async def test_readiness_fails_while_a_loop_has_not_begun_cycling(self, http):
        _register(_slow_to_start_loop)

        resp = await http.get("/ready")

        assert resp.status_code == 503
        assert resp.json()["status"] == "starting", (
            "an unready storefront that is merely still starting must be "
            "distinguishable from a faulty one; an operator reading a probe "
            "failure needs to tell 'wait' from 'investigate'"
        )

    async def test_liveness_still_passes_while_starting(self, http):
        """A slow start must not restart the pod.

        Liveness is reserved for conditions no further running resolves, and a
        loop that has not begun cycling resolves by beginning to cycle.
        """
        _register(_slow_to_start_loop)

        resp = await http.get("/health")

        assert resp.status_code == 200

    async def test_readiness_passes_once_every_loop_has_gated(self, http):
        _register(_cycling_loop)
        await asyncio.sleep(0.05)

        resp = await http.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["loops"] == {LOOP: "running"}

    async def test_readiness_fails_when_no_loop_is_registered(self, http):
        """An empty registry is not a healthy storefront.

        It is what a lifespan that has not run — or one that failed before
        starting anything — looks like, and reporting it ready would let traffic
        reach a storefront that will never do its background work.
        """
        resp = await http.get("/ready")

        assert resp.status_code == 503
        assert resp.json()["status"] == "starting"


class TestAStorefrontWithADeadLoop:
    async def test_both_probes_fail(self, http):
        """Liveness too, because nothing will restart the loop.

        Readiness alone would drain traffic and leave the process running with
        its background work permanently stopped. If loop supervision is ever
        added this becomes a readiness-only condition.
        """
        async def _ends() -> None:
            return None

        _register(_ends)
        await asyncio.sleep(0.01)

        assert (await http.get("/health")).status_code == 503
        assert (await http.get("/ready")).status_code == 503

    async def test_diagnosis_still_answers(self, http):
        """The status surface is read when the probes are failing.

        A diagnostic route that failed alongside them would remove the only way
        to find out which loop died.
        """
        async def _ends() -> None:
            return None

        _register(_ends)
        await asyncio.sleep(0.01)

        resp = await http.get("/api/v1/system/status")

        assert resp.status_code == 200
        assert resp.json()["loops"] == {LOOP: "exited"}


class TestAPausedStorefrontIsReady:
    async def test_a_lifecycle_pause_does_not_fail_readiness(self, http):
        """Pause is an operator control, not a fault.

        The storefront still serves and still trades with its loops idle. Failing
        readiness on it would make every scenario's container unhealthy the
        moment it paused, and would make an operator control indistinguishable
        from a failure.
        """
        _register(_cycling_loop)
        await asyncio.sleep(0.05)
        await _server._set_loops_paused(True)

        resp = await http.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["loops"] == {LOOP: "paused"}


class TestTheLoopsCheckIsReportedEverywhere:
    async def test_status_carries_the_loops_check(self, http):
        _register(_cycling_loop)
        await asyncio.sleep(0.05)

        body = (await http.get("/api/v1/system/status")).json()

        assert body["checks"]["loops"] == "ok"

    async def test_a_starting_loop_shows_in_the_checks_map(self, http):
        """Present on the liveness surface too, though it does not fail it.

        Whether the background work is running is part of whether a storefront is
        healthy, and a caller diagnosing a failing probe reads the checks map.
        """
        _register(_slow_to_start_loop)

        body = (await http.get("/health")).json()

        assert body["checks"]["loops"].startswith("starting:")
