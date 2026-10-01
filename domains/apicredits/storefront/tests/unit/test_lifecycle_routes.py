"""The API-credit lifecycle routes, driven through the canonical storefront client.

A component test, not an integration test: it mounts only the lifecycle router,
with this storefront's response-signing middleware and administrator
authentication over a real SQLite replay store, on an application it assembles
itself, and starts the loops itself rather than through the storefront's
lifespan. The watchdog and settlement-servicing loops are the production
runners; the capacity fan-out is a stand-in that gates and waits like the kit's.
Production-application coverage requires the credits service and a capacity
authority, and is not provided by this component test.

Every interleaving is coordinated with events; nothing here waits on time.
"""

from __future__ import annotations

import asyncio
from functools import partial

import httpx
import pytest
from core_storefront.app_startup import StorefrontBackgroundTask
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_capacity_publication import run_capacity_event_pollers
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementServicingWorker
from market_storefront_kit import (
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    run_negotiation_watchdog,
)
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
from apicredits_storefront.controllers.lifecycle_controller import router
from apicredits_storefront.lifecycle_steps import (
    CAPACITY_EVENTS_POLLER,
    NEGOTIATION_WATCHDOG,
    SETTLEMENT_SERVICING,
    capacity_site_loop_name,
    register_api_credit_lifecycle_steps,
)
from apicredits_storefront.middleware import admin_auth
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.utils.sqlite_client import SQLiteClient

# Deterministic development keys for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))
STOREFRONT_SIGNER = Ed25519Signer(bytes.fromhex("77" * 32))


class _NothingDue:
    """A settlement repository with no due obligations, counting each sweep."""

    def __init__(self) -> None:
        self.sweeps = 0

    async def list_due_settlement_obligations(self, **_kwargs):
        self.sweeps += 1
        return []


async def _site_pollers(*, paused, wait):
    """One site poller, gating and waiting through the controller like the kit's."""
    gate = paused("quota-site")
    while True:
        if gate():
            await asyncio.Event().wait()
        await wait(3600)


@pytest.fixture
async def storefront(tmp_path, monkeypatch):
    db = SQLiteClient(db_path=str(tmp_path / "lifecycle.db"))
    loops = StorefrontLoopController()
    register_api_credit_lifecycle_steps(loops)
    repository = _NothingDue()
    worker = SettlementServicingWorker(
        runtime=object(), repository=repository, worker_id="test", interval_seconds=3600
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_marketplace_signer", STOREFRONT_SIGNER)
    monkeypatch.setattr(container, "resolved_settlement_worker", worker)
    monkeypatch.setattr(container, "resolved_loop_controller", loops)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
    )
    loops.start_loop(
        StorefrontBackgroundTask(
            name=NEGOTIATION_WATCHDOG,
            task_factory=partial(
                run_negotiation_watchdog,
                db,
                NegotiationWatchdogPolicy(timeout_seconds=1800, interval_seconds=3600),
                paused=loops.loop_gate(NEGOTIATION_WATCHDOG),
                wait=loops.idle,
            ),
        )
    )
    loops.start_loop(
        StorefrontBackgroundTask(
            name=SETTLEMENT_SERVICING,
            task_factory=partial(
                worker.run, paused=loops.loop_gate(SETTLEMENT_SERVICING), wait=loops.idle
            ),
        )
    )
    loops.start_loop(
        StorefrontBackgroundTask(
            name=CAPACITY_EVENTS_POLLER,
            task_factory=partial(
                run_capacity_event_pollers,
                _site_pollers,
                gate=loops.loop_gate(CAPACITY_EVENTS_POLLER),
                site_gate=lambda site: loops.declare(capacity_site_loop_name(site)),
                wait=loops.idle,
            ),
        )
    )
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(router)
    yield app, loops, repository
    handles = list(loops._handles.values())
    loops.clear_loops()
    await asyncio.gather(*handles, return_exceptions=True)


def _admin(app) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def test_the_pause_holds_every_loop_and_each_step_runs_while_held(storefront):
    app, loops, repository = storefront
    async with _admin(app) as admin:
        paused = await admin.admin_pause_lifecycle_loops()
        assert paused == {
            "paused": True,
            "loops": {
                NEGOTIATION_WATCHDOG: "paused",
                SETTLEMENT_SERVICING: "paused",
                CAPACITY_EVENTS_POLLER: "paused",
                capacity_site_loop_name("quota-site"): "paused",
            },
        }

        stepped = await admin.admin_run_lifecycle_cycle("settlement-servicing")
        assert stepped == {"loop": SETTLEMENT_SERVICING, "processed": 0}
        assert repository.sweeps == 1
        assert set(loops.states().values()) == {"paused"}

        resumed = await admin.admin_resume_lifecycle_loops()
        assert resumed["paused"] is False
        assert set(resumed["loops"].values()) == {"running"}


async def test_an_unknown_loop_is_not_found(storefront):
    app, _loops, _repository = storefront
    async with _admin(app) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_run_lifecycle_cycle("publication")
    assert refused.value.status_code == 404


async def test_a_loop_without_a_preview_offers_none(storefront):
    app, _loops, _repository = storefront
    async with _admin(app) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_dry_run_lifecycle_cycle("settlement-servicing")
    assert refused.value.status_code == 404


async def test_an_unsigned_pause_is_refused(storefront):
    app, loops, _repository = storefront
    # Rejection path: an unsigned request is refused before any loop is held.
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/lifecycle/pause")
    assert response.status_code == 401
    assert not loops.is_pause_requested()
