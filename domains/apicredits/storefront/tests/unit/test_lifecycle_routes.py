"""The API-credit lifecycle routes, driven through the canonical storefront client.

A component test, not an integration test: it mounts only the lifecycle router,
with this storefront's response-signing middleware and administrator
authentication over a real SQLite replay store, on an application it assembles
itself, and starts the loops itself rather than through the storefront's
lifespan. The loops are the storefront's own registrations -- each sweep's
timer on the controller over the step its route runs, and the capacity-event
pollers' fan-out over the production poller loop -- with the collaborators the steps
read injected through the container and the capacity runtime the pollers drain
standing in for the quota authority. Production-application coverage requires
the credits service and a capacity authority, and is not provided by this
component test.

Every interleaving is coordinated with events; nothing here waits on time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_capacity_publication import SiteEventCycle
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementServicingWorker
from market_storefront_kit import StorefrontLoopController
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
from apicredits_storefront.controllers.lifecycle_controller import router
from apicredits_storefront.lifecycle_steps import (
    CAPACITY_EVENTS_POLLER,
    NEGOTIATION_WATCHDOG,
    SETTLEMENT_SERVICING,
    api_credit_loop_controller,
    capacity_site_loop_name,
    register_api_credit_lifecycle_steps,
    register_api_credit_loops,
)
from apicredits_storefront.middleware import admin_auth
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

# Deterministic development keys for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))
STOREFRONT_SIGNER = Ed25519Signer(bytes.fromhex("77" * 32))

#: Far longer than any test waits.
_LONG_INTERVAL = 3600

#: A quota authority's URL, as an unexpected error's text may carry one. A
#: development value on a reserved domain.
_AUTHORITY_URL = "http://quota-site.invalid:8082"


class _Obligations:
    """A settlement repository with no due obligations, marking each sweep.

    ``error``, when set, is what the next sweep raises instead.
    """

    def __init__(self) -> None:
        self.sweeps = 0
        self.swept = asyncio.Event()
        self.error: Exception | None = None

    async def list_due_settlement_obligations(self, **_kwargs):
        self.sweeps += 1
        self.swept.set()
        if self.error is not None:
            raise self.error
        return []


class _QuotaSites:
    """The capacity runtime the pollers drain: two sites whose feeds are stood in.

    Each site's poller gates through the gate it is given and reports each
    cycle through its recorder, as the kit's pollers do; ``fail`` names the
    site whose cycles fail. ``cycled`` is set after each round of cycles.
    """

    SITES = ("quota-east", "quota-west")
    site_ids = SITES

    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.cycled = asyncio.Event()

    async def poll_events(self, *, interval_seconds, paused=None, wait=None, record=None):
        gates = {site: paused(site) for site in self.SITES}
        recorders = {site: record(site) for site in self.SITES}
        while True:
            for site in self.SITES:
                if gates[site]():
                    continue
                error = (
                    ConnectionError(f"{_AUTHORITY_URL} refused the connection")
                    if site == self.fail
                    else None
                )
                recorders[site](SiteEventCycle(site_name=site, exception=error))
            self.cycled.set()
            await wait(_LONG_INTERVAL)


@dataclass(frozen=True)
class _Storefront:
    app: FastAPI
    loops: StorefrontLoopController
    obligations: _Obligations
    #: The capacity-event aggregate loop's task.
    capacity_aggregate: asyncio.Task


@pytest.fixture
async def start_storefront(tmp_path, monkeypatch):
    """Start the storefront's loops over injected collaborators, as startup does.

    Returns a factory taking the servicing interval and the capacity runtime;
    every other interval is far longer than any test waits.
    """
    db = SQLiteClient(db_path=str(tmp_path / "lifecycle.db"))
    obligations = _Obligations()
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_marketplace_signer", STOREFRONT_SIGNER)
    monkeypatch.setattr(container, "resolved_settlement_composition", None)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
    )
    started: list = []

    def start(*, servicing_interval: float = _LONG_INTERVAL, sites: _QuotaSites | None = None):
        loops = api_credit_loop_controller()
        worker = SettlementServicingWorker(
            runtime=object(),
            repository=obligations,
            worker_id="test",
            interval_seconds=servicing_interval,
        )
        monkeypatch.setattr(container, "resolved_settlement_worker", worker)
        monkeypatch.setattr(container, "resolved_loop_controller", loops)
        register_api_credit_lifecycle_steps(loops)
        with settings_overrides(
            negotiation_watchdog_interval=_LONG_INTERVAL,
            settlement_servicing_interval_seconds=servicing_interval,
        ):
            register_api_credit_loops(loops, capacity_runtime=sites or _QuotaSites())
        capacity_aggregate = loops.start_loops()[CAPACITY_EVENTS_POLLER]
        started.append(loops)
        app = FastAPI()
        app.middleware("http")(authenticate_response)
        app.include_router(router)
        return _Storefront(app, loops, obligations, capacity_aggregate)

    yield start
    for loops in started:
        await loops.stop_loops()


@pytest.fixture
async def storefront(start_storefront):
    return start_storefront()


def _admin(app, *, raise_app_exceptions: bool = True) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
    )


async def test_the_pause_holds_every_loop_and_each_step_runs_while_held(storefront):
    app, loops, repository = storefront.app, storefront.loops, storefront.obligations
    async with _admin(app) as admin:
        paused = await admin.admin_pause_lifecycle_loops()
        assert paused == {
            "paused": True,
            "loops": {
                NEGOTIATION_WATCHDOG: "paused",
                SETTLEMENT_SERVICING: "paused",
                CAPACITY_EVENTS_POLLER: "paused",
                capacity_site_loop_name("quota-east"): "paused",
                capacity_site_loop_name("quota-west"): "paused",
            },
        }

        stepped = await admin.admin_run_lifecycle_cycle("settlement-servicing")
        assert stepped == {"loop": SETTLEMENT_SERVICING, "processed": 0}
        assert repository.sweeps == 1
        assert set(loops.states().values()) == {"paused"}
        outcome = loops.last_outcome(SETTLEMENT_SERVICING)
        assert (outcome.trigger, outcome.completed) == ("step", True)

        resumed = await admin.admin_resume_lifecycle_loops()
        assert resumed["paused"] is False
        assert set(resumed["loops"].values()) == {"running"}


async def test_an_unknown_loop_is_not_found(storefront):
    app = storefront.app
    async with _admin(app) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_run_lifecycle_cycle("publication")
    assert refused.value.status_code == 404


async def test_a_loop_without_a_preview_offers_none(storefront):
    app = storefront.app
    async with _admin(app) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_dry_run_lifecycle_cycle("settlement-servicing")
    assert refused.value.status_code == 404


async def test_an_unsigned_pause_is_refused(storefront):
    app, loops = storefront.app, storefront.loops
    # Rejection path: an unsigned request is refused before any loop is held.
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/lifecycle/pause")
    assert response.status_code == 401
    assert not loops.is_pause_requested()


async def test_the_servicing_timer_runs_its_step_and_records_the_cycle(start_storefront):
    """The controller's timer runs the step the route runs, through the one
    cycle boundary, and records the cycle as the timer's."""
    started = start_storefront(servicing_interval=0.01)
    loops, repository = started.loops, started.obligations
    await asyncio.wait_for(repository.swept.wait(), timeout=1.0)
    await asyncio.wait_for(loops.pause(), timeout=1.0)

    snapshot = loops.snapshot()[SETTLEMENT_SERVICING]
    assert snapshot.state == "paused"
    assert snapshot.last_outcome is not None
    assert (snapshot.last_outcome.trigger, snapshot.last_outcome.completed) == ("timer", True)
    assert loops.last_outcome(NEGOTIATION_WATCHDOG) is None, "a sweep ran before its interval"


async def test_a_stepped_cycle_failing_on_an_unexpected_error_is_recorded_by_type(storefront):
    """Spec scenarios "A stepped cycle fails" and "A cycle fails on an
    unexpected exception": recorded as a timer's cycle would be, naming its
    stage and the error's type and not its text, which names a URL."""
    app, loops, repository = storefront.app, storefront.loops, storefront.obligations
    repository.error = ConnectionError(f"{_AUTHORITY_URL} refused the connection")
    async with _admin(app, raise_app_exceptions=False) as admin:
        await admin.admin_pause_lifecycle_loops()
        with pytest.raises(StorefrontClientError) as failed:
            await admin.admin_run_lifecycle_cycle("settlement-servicing")
    assert failed.value.status_code == 500
    assert _AUTHORITY_URL not in str(failed.value)

    outcome = loops.last_outcome(SETTLEMENT_SERVICING).to_dict()
    assert outcome["trigger"] == "step"
    assert outcome["completed"] is False
    assert outcome["stage"] == "run"
    assert outcome["error"] == {"type": "ConnectionError", "message": None}


async def test_each_sites_capacity_event_cycles_are_recorded_under_its_own_name(
    start_storefront,
):
    """Spec scenario "One site's capacity-event feed fails": the failing site's
    loop reports its cycle failed, by its error's type, and the other site's
    its own outcome; the aggregate loop, which runs no cycle, records none."""
    sites = _QuotaSites(fail="quota-west")
    loops = start_storefront(sites=sites).loops
    await asyncio.wait_for(sites.cycled.wait(), timeout=1.0)

    east = loops.last_outcome(capacity_site_loop_name("quota-east"))
    west = loops.last_outcome(capacity_site_loop_name("quota-west"))
    assert (east.trigger, east.completed, east.error) == ("timer", True, None)
    assert (west.trigger, west.completed) == ("timer", False)
    assert west.error.to_dict() == {"type": "ConnectionError", "message": None}
    assert loops.last_outcome(CAPACITY_EVENTS_POLLER) is None


async def test_once_the_capacity_aggregate_ends_its_sites_report_its_end(start_storefront):
    """Each site is declared as the aggregate loop's child, so once the
    aggregate's task has ended nothing runs the site's cycles either, and the
    site reports the aggregate's end rather than the state its gate last left."""
    sites = _QuotaSites()
    started = start_storefront(sites=sites)
    loops, aggregate = started.loops, started.capacity_aggregate
    await asyncio.wait_for(sites.cycled.wait(), timeout=1.0)
    aggregate.cancel()
    await asyncio.gather(aggregate, return_exceptions=True)

    states = loops.states()
    assert states[CAPACITY_EVENTS_POLLER] == "cancelled"
    assert states[capacity_site_loop_name("quota-east")] == "cancelled"
    assert states[capacity_site_loop_name("quota-west")] == "cancelled"


def test_every_sites_poller_is_listed_before_its_first_cycle(monkeypatch):
    """The fan-out declares each site's poller when it registers, so status
    lists every site before the fan-out has started, let alone polled."""
    monkeypatch.setattr(container, "resolved_settlement_composition", None)
    loops = api_credit_loop_controller()

    register_api_credit_loops(loops, capacity_runtime=_QuotaSites())

    assert loops.states() == {
        capacity_site_loop_name("quota-east"): "starting",
        capacity_site_loop_name("quota-west"): "starting",
    }
