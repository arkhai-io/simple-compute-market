"""System status reports every lifecycle loop and its last cycle's outcome.

Driven through the canonical storefront client against the storefront's own
application instance, built by its app factory with every route and its
response signing and administrator authentication, over a real SQLite
database. The application's lifespan is not run, since composing the
storefront from configuration needs the credits service and a quota authority;
the test wires the container the lifespan would and starts the loops through
the storefront's own registrations, as startup does, over a settlement
servicing worker whose repository the test controls and a capacity runtime
standing in for the quota authority's feeds. The startup case runs the
storefront's own startup tasks instead, with its credits service refusing
connections.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

import httpx
import pytest
from market_alkahest import ALKAHEST_CHAIN_PROBE_LOOP, AlkahestChainProbe, ProbedChain
from market_capacity_publication import SiteEventCycle
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementServicingWorker
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
import apicredits_storefront.server as server
from apicredits_storefront import startup
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.listing_seed import (
    CREDITS_SERVICE_UNANSWERED,
    LISTING_SEED,
    WAITING,
    configured_listing_seed,
)
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
from apicredits_storefront.services.system_service import SystemService
from apicredits_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from apicredits_storefront.utils import config as storefront_config
from tests._settings_overrides import settings_overrides

# Deterministic development keys for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))
STOREFRONT_SIGNER = Ed25519Signer(bytes.fromhex("77" * 32))

#: Far longer than any test waits.
_LONG_INTERVAL = 3600

#: A quota authority's URL, as an unexpected error's text may carry one. A
#: development value on a reserved domain.
_AUTHORITY_URL = "http://quota-site.invalid:8082"

_SITE = "quota-site"

pytestmark = pytest.mark.asyncio


class _Obligations:
    """A settlement repository whose sweeps raise ``error`` when it is set."""

    def __init__(self) -> None:
        self.error: Exception | None = None

    async def list_due_settlement_obligations(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return []


class _QuotaSite:
    """One quota site's feed: it gates, reports each cycle, and waits, as the
    kit's poller does; ``error`` fails each cycle. ``cycled`` is set after a
    cycle is reported."""

    site_ids = (_SITE,)

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.cycled = asyncio.Event()

    async def poll_events(self, *, interval_seconds, paused=None, wait=None, record=None):
        gate, report = paused(_SITE), record(_SITE)
        while True:
            if gate():
                await asyncio.Event().wait()
            report(SiteEventCycle(site_name=_SITE, exception=self.error))
            self.cycled.set()
            await wait(_LONG_INTERVAL)


@pytest.fixture
async def storefront(db, monkeypatch):
    """The storefront's system and lifecycle routes over its started loops."""
    obligations = _Obligations()
    worker = SettlementServicingWorker(
        runtime=object(),
        repository=obligations,
        worker_id="test",
        interval_seconds=_LONG_INTERVAL,
    )
    loops = api_credit_loop_controller()
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_marketplace_signer", STOREFRONT_SIGNER)
    monkeypatch.setattr(container, "resolved_settlement_composition", None)
    monkeypatch.setattr(container, "resolved_settlement_worker", worker)
    monkeypatch.setattr(container, "resolved_loop_controller", loops)
    monkeypatch.setattr(
        container, "resolved_system_service", SystemService(sqlite_client=db)
    )
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
    )
    def start(site: _QuotaSite) -> None:
        register_api_credit_lifecycle_steps(loops)
        with settings_overrides(
            negotiation_watchdog_interval=_LONG_INTERVAL,
            settlement_servicing_interval_seconds=_LONG_INTERVAL,
        ):
            register_api_credit_loops(loops, capacity_runtime=site)
        loops.start_loops()

    app = server.build_api_credits_storefront_app(
        registry=server.build_api_credits_storefront_registry(
            domain=get_market_domain_contract()
        )
    )
    try:
        yield app, loops, obligations, start
    finally:
        await loops.stop_loops()


def _admin(app, *, raise_app_exceptions: bool = True) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
    )


async def test_every_loop_is_reported_with_its_state(storefront):
    """Held from the start: each loop startup registers, and the site's
    capacity-event poller, is reported paused with no cycle recorded."""
    app, loops, _obligations, start = storefront
    loops.request_pause(True)
    start(_QuotaSite())
    await asyncio.wait_for(loops.await_quiescence(), timeout=1.0)

    async with _admin(app) as admin:
        lifecycle = (await admin.get_system_status()).lifecycle

    for name in (
        NEGOTIATION_WATCHDOG,
        SETTLEMENT_SERVICING,
        CAPACITY_EVENTS_POLLER,
        capacity_site_loop_name(_SITE),
    ):
        assert lifecycle[name]["state"] == "paused", name
        assert lifecycle[name]["last_outcome"] is None, name


async def test_a_stepped_cycle_failing_on_an_unexpected_error_is_reported_by_type(storefront):
    """Spec scenarios "A stepped cycle fails" and "A cycle fails on an
    unexpected exception": status reports the step's failure with its stage and
    the error's type, never its text, which names a URL."""
    app, loops, obligations, start = storefront
    start(_QuotaSite())
    obligations.error = ConnectionError(f"{_AUTHORITY_URL} refused the connection")

    async with _admin(app, raise_app_exceptions=False) as admin:
        await admin.admin_pause_lifecycle_loops()
        with pytest.raises(StorefrontClientError) as failed:
            await admin.admin_run_lifecycle_cycle("settlement-servicing")
        status = await admin.get_system_status()

    assert failed.value.status_code == 500
    servicing = status.lifecycle[SETTLEMENT_SERVICING]
    assert servicing["state"] == "paused"
    outcome = servicing["last_outcome"]
    assert outcome["trigger"] == "step"
    assert outcome["completed"] is False
    assert outcome["stage"] == "run"
    assert outcome["error"] == {"type": "ConnectionError", "message": None}
    assert _AUTHORITY_URL not in str(status)


async def test_a_sites_failing_capacity_event_feed_is_reported_under_its_loop(storefront):
    """Spec scenario "One site's capacity-event feed fails": the site's poller
    reports its timer cycle failed by type, and the aggregate loop, which runs
    no cycle, reports none."""
    app, _loops, _obligations, start = storefront
    site = _QuotaSite(error=ConnectionError(f"{_AUTHORITY_URL} refused the connection"))
    start(site)
    await asyncio.wait_for(site.cycled.wait(), timeout=1.0)

    async with _admin(app) as admin:
        status = await admin.get_system_status()

    poller = status.lifecycle[capacity_site_loop_name(_SITE)]
    assert poller["state"] == "running"
    assert poller["last_outcome"]["trigger"] == "timer"
    assert poller["last_outcome"]["completed"] is False
    assert poller["last_outcome"]["error"] == {"type": "ConnectionError", "message": None}
    assert status.lifecycle[CAPACITY_EVENTS_POLLER]["last_outcome"] is None
    assert _AUTHORITY_URL not in str(status)


class _Rpc:
    """The chain's JSON-RPC endpoint, the boundary the probe calls: refusing
    connections until ``answering`` is set."""

    def __init__(self) -> None:
        self.answering = False

    def __call__(self, rpc_url, method, params, timeout):
        if not self.answering:
            raise ConnectionRefusedError("connection refused")
        return hex(31337) if method == "eth_chainId" else "0x6080"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _AlkahestReadiness:
    """The settlement composition's readiness, through the storefront's own
    registry and the real Alkahest preflight, over the probe the container
    holds, as the composition hands it its resources."""

    def __init__(self, probe: AlkahestChainProbe) -> None:
        self._registry = build_storefront_settlement_registry()
        self._config = self._registry.resolve(
            {"schema_version": 1, "priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
            role="seller",
        )
        self._probe = probe

    def payment_service(self, _db):
        # Arkhai payments is not composed, so no reconciliation loop runs.
        return None

    async def readiness(self):
        return await self._registry.ordered_readiness(
            self._config,
            role="seller",
            resources={
                # A deterministic development address, never for a public network.
                "wallet": {"address": "0x" + "33" * 20},
                "chains": {"anvil": {"rpc_url": "http://anvil.test"}},
                "default_chain": "anvil",
                "chain_probe": self._probe,
            },
        )


async def test_the_chain_probe_loop_steps_alkahest_from_unreachable_to_ready(
    storefront, monkeypatch
):
    """Spec scenario "A storefront starts with its chain down": the
    ``alkahest-chain-probe`` loop is listed and steppable, and Alkahest is
    unready with the reachability blocker until a stepped probe reaches the
    chain, then ready, without a restart."""
    app, loops, _obligations, start = storefront
    rpc, clock = _Rpc(), _Clock()
    probe = AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", chain_id=31337)],
        json_rpc=rpc,
        required_addresses=lambda _chain: {"escrow": "0x" + "11" * 20},
        clock=clock,
    )
    monkeypatch.setattr(container, "resolved_alkahest_chain_probe", probe)
    monkeypatch.setattr(
        container, "resolved_settlement_composition", _AlkahestReadiness(probe)
    )
    loops.request_pause(True)
    start(_QuotaSite())
    await asyncio.wait_for(loops.await_quiescence(), timeout=1.0)

    def alkahest(status) -> dict:
        (item,) = [m for m in status.settlement if m["mechanism"] == "alkahest.v1"]
        return item

    async with _admin(app) as admin:
        held = await admin.get_system_status()
        await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
        refused = alkahest(await admin.get_system_status())
        # A step probes at once, with no interval to wait out.
        rpc.answering = True
        await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
        ready = alkahest(await admin.get_system_status())

    assert held.lifecycle[ALKAHEST_CHAIN_PROBE_LOOP]["state"] == "paused"
    assert [(b["code"], b["kind"]) for b in alkahest(held)["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]
    assert refused["public_details"]["chain_probe"]["anvil"]["result"] == (
        "alkahest.chain_unreachable"
    )
    assert ready["ready"] is True
    assert ready["public_details"]["chain_probe"]["anvil"]["result"] == "reachable"


#: Nothing listens on the discard port, so every connection to it is refused.
_REFUSED = "http://127.0.0.1:9"

@contextmanager
def _capacity_sites(sites):
    """Replace `[capacity.sites]` whole, restoring `[capacity]` afterwards: a
    dotted override would merge into the configuration's own table, and its
    restore would leave the sites behind for later tests."""
    settings = storefront_config.settings
    saved = deepcopy(settings.get("capacity"))
    try:
        settings.unset("capacity", force=True)
        settings.set("capacity", {**(saved or {}), "sites": sites})
        yield
    finally:
        settings.unset("capacity", force=True)
        if saved is not None:
            settings.set("capacity", saved)


#: The quota site, at the refused credits service: a deterministic development
#: principal, never used on any network.
_REFUSED_QUOTA_SITE = {
    _SITE: {
        "url": _REFUSED,
        "expected_authorities": {
            "identities": [
                Ed25519Signer(bytes.fromhex("88" * 32)).identity.model_dump(mode="json")
            ]
        },
    }
}


async def test_startup_does_not_wait_for_an_unreachable_credits_service(
    storefront, db, monkeypatch
):
    """The start of spec scenario "A storefront starts before its site or
    service": startup runs to its loops while the credits service, which hosts
    the quota ledger at the configured capacity site, refuses connections; the
    storefront answers its health check, and the ``listing-seed`` step waits for
    the service rather than giving up. The seed is the one the configuration
    states, built as the composition builds it, registering its quota through
    the real capacity-administration client at the configured site. That a call
    succeeds once the service answers is not shown here."""
    app, loops, _obligations, _start = storefront
    domain = get_market_domain_contract()
    monkeypatch.setattr(container, "resolved_market_domain", domain)
    monkeypatch.setattr(container, "resolved_settlement_runtime", None)
    register_api_credit_lifecycle_steps(loops)
    # Held from the start, so the seed's cycles are the steps this test runs.
    loops.request_pause(True)
    with _capacity_sites(_REFUSED_QUOTA_SITE), settings_overrides(
        **{"credits.service_url": _REFUSED, "seed": {"resource_id": "demo-quota"}}
    ):
        seed = configured_listing_seed(listing_service=None, signer=STOREFRONT_SIGNER, db=db)
        monkeypatch.setattr(container, "resolved_listing_seed", seed)
        await startup._startup_tasks(domain=domain, capacity_runtime=_QuotaSite())
        await asyncio.wait_for(loops.await_quiescence(), timeout=1.0)

        async with _admin(app) as admin:
            health = await admin.get_health()
            first = await admin.admin_run_lifecycle_cycle("listing-seed")
            second = await admin.admin_run_lifecycle_cycle("listing-seed")
            status = await admin.get_system_status()

    assert health.checks["database"] == "ok"
    assert first["state"] == WAITING
    assert first["reason"] == CREDITS_SERVICE_UNANSWERED
    # Still waiting, and still trying: waiting does not give the seed up.
    assert (second["state"], second["attempts"]) == (WAITING, 2)
    outcome = status.lifecycle[LISTING_SEED]["last_outcome"]
    assert (outcome["trigger"], outcome["completed"]) == ("step", True)
    assert _REFUSED not in str(status)


async def test_an_unsigned_status_read_is_refused(storefront):
    # Rejection path: system status is the administrator's signed read.
    app = storefront[0]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://seller"
    ) as client:
        response = await client.get("/api/v1/system/status")
    assert response.status_code == 401
