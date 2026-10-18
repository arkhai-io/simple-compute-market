from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest
from compute_provisioning_contracts import COMPUTE_PROVISIONING_CONTRACT_VERSION
from core_storefront.multi_registry_client import RegistryAuthorityTrust
from fastapi.testclient import TestClient
from market_identity import Eip191Signer, Identity, TrustedIdentitySet

from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError
from storefront_client.models import HealthResponse

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.lifecycle_steps import (
    PUBLICATION,
    PublicationWake,
    bare_metal_loop_controller,
)
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.publication_service import BareMetalRegistryConfiguration
from arkhai_bare_metal_storefront.runtime import (
    BareMetalStorefrontRuntime,
    _status_check_healthy,
)
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from held_loops import held_loop_controller
from settlement_compositions import alkahest_composition
from site_trust import seeded_sites
from test_publication_cycle import (
    REGISTRY_URL,
    RecordingRegistries,
    Site,
    Terms,
    member,
    pool,
    projections_over,
)


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )

SELLER_SECRET_HEX = "11" * 32
SELLER_SIGNER = Eip191Signer(bytes.fromhex(SELLER_SECRET_HEX))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))

def _runtime(path: str) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(
            identities=(ADMIN_SIGNER.identity,),
        ),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address="0x3333333333333333333333333333333333333333",
    )


def test_runtime_repr_does_not_serialize_signer_secret(tmp_path) -> None:
    rendered = repr(_runtime(str(tmp_path / "storefront.db")))
    assert SELLER_SECRET_HEX not in rendered
    assert "marketplace_signer" not in rendered


async def _insert_listing(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[],
    )


async def test_listing_routes_return_exact_validated_domain_payload(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            listing = await public.get_listing("listing-1")
            listing_list = await public.list_listings()
            with pytest.raises(StorefrontClientError) as missing:
                await public.get_listing("missing")

    assert listing.listing_resource == {
        "capacity_backing": "backed",
        **LISTING_HARDWARE,
        "kind": "bare_metal.v2",
        "offering_mode": "bare_metal",
        "host_id": "machine-1",
        "physical_host_id": "physical-host-1",
        "access_methods": ["ssh"],
        "max_duration_seconds": 7200,
    }
    assert listing_list.count == 1
    assert listing_list.listings[0].listing_id == "listing-1"
    assert missing.value.status_code == 404


def _admin_client(app) -> StorefrontClient:
    """The canonical storefront client as the configured administrator.

    Responses are verified against the storefront's own marketplace signer.
    """
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def test_pause_is_admin_authenticated_and_process_local(tmp_path) -> None:
    path = str(tmp_path / "storefront.db")
    first_app = _app(_runtime(path))

    # Rejection path: an unsigned request is refused before any state changes.
    with TestClient(first_app) as client:
        assert client.post("/api/v1/admin/pause").status_code == 401
    async with first_app.router.lifespan_context(first_app):
        async with _admin_client(first_app) as admin:
            paused = await admin.admin_pause()
            paused_status = await admin.get_system_status()
            resumed = await admin.admin_resume()
            resumed_status = await admin.get_system_status()
            await admin.admin_pause()
    assert paused.paused is True and paused_status.paused is True
    assert resumed.paused is False and resumed_status.paused is False

    # The trading pause belongs to the process: a rebuilt application trades.
    second_app = _app(_runtime(path))
    async with second_app.router.lifespan_context(second_app):
        async with _admin_client(second_app) as admin:
            status = await admin.get_system_status()
    assert status.paused is False


async def _health(runtime: BareMetalStorefrontRuntime) -> HealthResponse:
    """Read ``/health`` through the canonical storefront client.

    The app runs its own lifespan, which composes the runtime into the request
    container, and the client talks to it over the in-process transport.
    """
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as client:
            return await client.get_health()


async def test_health_is_truthful_about_uncomposed_authorities(tmp_path) -> None:
    health = await _health(_runtime(str(tmp_path / "storefront.db")))

    assert health.status == "degraded"
    assert health.checks == {
        "api": "ok",
        "database": "ok",
        "commercial_settlement": "unavailable",
        "fulfillment": "unavailable",
    }
    assert health.paused is False
    assert "resource_count" not in health.extra
    assert health.site_projections == {}


def _sited_runtime(path: str, sites: dict) -> BareMetalStorefrontRuntime:
    """A runtime holding the projections of ``sites``, which startup loads.

    The state wakes the runtime's publication loop, as the composition root
    wires it.
    """
    wake = PublicationWake()
    return dataclasses.replace(
        _runtime(path),
        publication_wake=wake,
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                service_peer=f"{site_id}-peer",
                authority_url=f"http://{site_id}:8000",
            )
            for site_id in sites
        ),
        site_projections=projections_over(sites, on_resource_pool_change=wake),
        fulfillment_client=object(),
        loop_controller_factory=held_loop_controller,
    )


def _sites(**serving):
    """Site doubles by ID, each serving one pool at the given revision, or
    failing when given ``None``."""
    sites = {}
    for site_id, revisions in serving.items():
        site = Site(pool("pool-1", member("r1", "pool-1")))
        for _ in range(1, revisions or 1):
            site.serve(pool("pool-1", member("r1", "pool-1")))
        if revisions is None:
            site.fail()
        sites[site_id.replace("_", "-")] = site
    return sites


async def test_every_site_held_is_reported_loaded_and_health_calls_no_site(tmp_path) -> None:
    """Health reports both projection families of every site as the storefront
    holds them, and reading it calls no site. Spec scenario "An operator checks
    inventory readiness"."""
    sites = _sites(site_a=3, site_b=5)
    runtime = _sited_runtime(str(tmp_path / "storefront.db"), sites)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        loaded = {site_id: site.calls for site_id, site in sites.items()}
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as client:
            health = await client.get_health()
        called = {site_id: site.calls for site_id, site in sites.items()}

    projections = health.site_projections
    assert set(projections) == {"site-a", "site-b"}
    site_a = projections["site-a"]["resource_pool"]
    assert (site_a["state"], site_a["revision"], site_a["digest"]) == (
        "loaded",
        3,
        "digest-3",
    )
    assert site_a["fetched_at"] is not None
    assert projections["site-a"]["capacity_bucket"]["state"] == "loaded"
    assert projections["site-b"]["resource_pool"]["revision"] == 5
    assert called == loaded
    assert "site_projection" not in health.checks
    assert health.checks["fulfillment"] == "ok"


async def test_one_site_unavailable_is_reported_outside_the_health_gate(
    tmp_path,
) -> None:
    """One site being down is reported for that site and changes no gated check.

    Asserted against ``checks`` directly, the dict the status gates on, so the
    test does not depend on unrelated checks being healthy.
    """
    healthy = await _health(
        _sited_runtime(str(tmp_path / "healthy.db"), _sites(site_a=3, site_b=5))
    )
    one_down = await _health(
        _sited_runtime(str(tmp_path / "one-down.db"), _sites(site_a=3, site_b=None))
    )

    site_b = one_down.site_projections["site-b"]["resource_pool"]
    assert site_b["state"] == "unavailable"
    assert "site unreachable" in site_b["last_error"]
    assert one_down.site_projections["site-a"]["resource_pool"]["state"] == "loaded"
    assert one_down.checks == healthy.checks
    assert one_down.status == healthy.status
    assert "site_projections" not in one_down.checks


class _RecordingCycle:
    """Stands in for one publication pass, recording when it runs."""

    def __init__(self, log: list[str], name: str, gate: asyncio.Event | None) -> None:
        self._log = log
        self._name = name
        self._gate = gate

    async def run(self, *, dry_run: bool = False) -> dict[str, object]:
        self._log.append(f"start {self._name}" + (" (dry run)" if dry_run else ""))
        if self._gate is not None:
            await self._gate.wait()
        self._log.append(f"end {self._name}")
        return {"dry_run": dry_run, "actions": [{"action": "publish"}], "counts": {"publish": 1}}


def _stepped_runtime(path: str, log: list[str], gate: asyncio.Event | None = None):
    """A runtime whose publication cycles are recorded, its loops held from the
    start so only a step runs one."""
    runtime = _runtime(path)
    names = iter(("first", "second", "third"))
    return dataclasses.replace(
        runtime,
        publication_cycle_factory=lambda _runtime: _RecordingCycle(
            log, next(names), gate
        ),
        loop_controller_factory=held_loop_controller,
    )


async def test_the_publication_step_runs_one_pass_and_returns_its_report(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            report = await admin.admin_run_lifecycle_cycle("publication")

    assert report == {
        "dry_run": False,
        "actions": [{"action": "publish"}],
        "counts": {"publish": 1},
    }
    assert log == ["start first", "end first"]


async def test_the_publication_step_refuses_an_unsigned_request(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    # Rejection path: an unsigned request is refused before any pass runs.
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/lifecycle/publication/run-cycle")

    assert response.status_code == 401
    assert log == []


async def test_a_loop_the_storefront_does_not_run_is_not_found(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.admin_run_lifecycle_cycle("capacity-events")

    assert refused.value.status_code == 404
    assert log == []


class _ObservedLock(asyncio.Lock):
    """A lock a publication step takes, reporting each attempt to acquire it.

    Lets a test wait until a second request is actually blocked on the lock,
    rather than yielding and hoping it got there.
    """

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0
        self._attempted = asyncio.Event()

    async def acquire(self) -> bool:
        self.attempts += 1
        self._attempted.set()
        return await super().acquire()

    async def attempts_reach(self, count: int) -> None:
        while self.attempts < count:
            self._attempted.clear()
            await asyncio.wait_for(self._attempted.wait(), timeout=1)


async def test_concurrent_publication_steps_run_one_after_the_other(tmp_path) -> None:
    """The loop controller's cycle lock, the one ``run_cycle`` holds for a
    timer's cycle and a step's alike, serializes the steps: the second request
    waits on it while the first cycle runs."""
    log: list[str] = []
    gate = asyncio.Event()
    lock = _ObservedLock()
    runtime = dataclasses.replace(
        _stepped_runtime(str(tmp_path / "storefront.db"), log, gate),
        loop_controller_factory=lambda: held_loop_controller(
            cycle_lock_factory=lambda name: lock if name == PUBLICATION else asyncio.Lock()
        ),
    )
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            first = asyncio.create_task(admin.admin_run_lifecycle_cycle("publication"))
            await lock.attempts_reach(1)
            second = asyncio.create_task(admin.admin_run_lifecycle_cycle("publication"))
            # The second request is now waiting on the lock the first holds.
            await lock.attempts_reach(2)
            assert log == ["start first"]
            gate.set()
            await asyncio.gather(first, second)

    assert log == ["start first", "end first", "start second", "end second"]


class _ObservedCycles:
    """Composes each publication cycle over the runtime's held projections and a
    recording registry, as the production composition does, and reports each
    cycle that completes: the seam a test waits on instead of a timer."""

    def __init__(self) -> None:
        self.registries = RecordingRegistries()
        self.completed: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    def __call__(self, runtime: BareMetalStorefrontRuntime) -> "_ReportedCycle":
        cycle = BareMetalPublicationCycle(
            sqlite_client=runtime.db,
            registry=build_bare_metal_storefront_registry(domain=runtime.domain),
            site_projections=runtime.site_projections,
            site_ids=[binding.site_id for binding in runtime.site_bindings],
            registry_client_factory=self.registries,
            registry_urls=(REGISTRY_URL,),
            storefront_url=runtime.storefront_url,
            seller_principal=runtime.seller_principal,
            build_payload=Terms(),
            default_max_duration_seconds=3600,
            enter_stage=runtime.loops.enter_stage,
        )
        return _ReportedCycle(cycle, self.completed)

    async def next_cycle(self) -> dict[str, object]:
        return await asyncio.wait_for(self.completed.get(), timeout=5)


class _ReportedCycle:
    def __init__(self, cycle: BareMetalPublicationCycle, completed: asyncio.Queue) -> None:
        self._cycle = cycle
        self._completed = completed

    async def run(self, *, dry_run: bool = False) -> dict[str, object]:
        report = await self._cycle.run(dry_run=dry_run)
        if not dry_run:
            self._completed.put_nowait(report)
        return report


def _published(report: dict[str, object]) -> list[dict[str, object]]:
    return [item for item in report["actions"] if item["action"] == "publish"]


def _timed_runtime(path: str, site: Site, cycles: _ObservedCycles, **changes):
    """A runtime over one site whose loops run on their timers from the start,
    publication's interval far longer than any test waits."""
    return dataclasses.replace(
        _sited_runtime(path, {"site-a": site}),
        publication_cycle_factory=cycles,
        loop_controller_factory=bare_metal_loop_controller,
        publication_interval_seconds=3600,
        **changes,
    )


async def test_a_site_declaring_new_supply_is_published_by_the_timer(tmp_path) -> None:
    """With the loops running, a pool a site declares is published with no
    operator command: the poller's timer sees the site's new generation and
    wakes publication, whose interval has not passed. Spec scenario "A
    bare-metal site declares new supply"."""
    site = Site(pool("pool-0"))
    cycles = _ObservedCycles()
    runtime = _timed_runtime(
        str(tmp_path / "storefront.db"),
        site,
        cycles,
        site_projection_poll_interval_seconds=0.05,
    )
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        # The timer's first cycle, over what startup loaded: nothing to publish.
        first = await cycles.next_cycle()
        site.serve(pool("pool-1", member("r1", "pool-1")))
        woken = await cycles.next_cycle()
        outcome = runtime.loops.last_outcome(PUBLICATION)

    assert _published(first) == []
    (published,) = _published(woken)
    assert published["source"]["physical_resource_id"] == "r1"
    assert [operation for operation, _ in cycles.registries.operations()] == ["publish"]
    assert (outcome.trigger, outcome.completed) == ("timer", True)


async def test_the_projection_step_while_held_polls_and_publication_waits_for_resume(
    tmp_path,
) -> None:
    """Stepping the held site-projection poller runs exactly its cycle: it
    polls, sees the site's change, and wakes publication, which stays held and
    publishes only once the loops resume. Spec scenarios "The projection step is
    run while held" and "The loop is held"."""
    site = Site(pool("pool-0"))
    cycles = _ObservedCycles()
    runtime = _timed_runtime(str(tmp_path / "storefront.db"), site, cycles)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        await cycles.next_cycle()
        async with _admin_client(app) as admin:
            await admin.admin_pause_lifecycle_loops()
            site.serve(pool("pool-1", member("r1", "pool-1")))
            calls = site.calls
            stepped = await admin.admin_run_lifecycle_cycle("site-projections")
            held = cycles.completed.empty()
            still_paused = runtime.loops.is_pause_requested()
            await admin.admin_resume_lifecycle_loops()
            resumed = await cycles.next_cycle()

    assert site.calls > calls
    assert stepped["sites"]["site-a"]["resource_pool"]["revision"] == 2
    assert held and still_paused
    (published,) = _published(resumed)
    assert published["source"]["physical_resource_id"] == "r1"


class _FailingCycle:
    """A publication cycle that fails once it has started, naming a site's URL."""

    async def run(self, *, dry_run: bool = False) -> dict[str, object]:
        raise ConnectionError("http://site-a.internal:8081 refused the connection")


async def test_a_failed_publication_cycle_is_recorded_with_its_stage(tmp_path) -> None:
    """A cycle that cannot be composed fails in ``compose`` with the
    storefront's own publication error, whose message is disclosed; one failing
    on another exception is recorded by type alone, its message (a site URL)
    kept out. Spec scenario "A cycle fails on an unexpected exception"."""
    uncomposed = dataclasses.replace(
        _runtime(str(tmp_path / "uncomposed.db")),
        loop_controller_factory=held_loop_controller,
    )
    failing = dataclasses.replace(
        _runtime(str(tmp_path / "failing.db")),
        publication_cycle_factory=lambda _runtime: _FailingCycle(),
        loop_controller_factory=held_loop_controller,
    )
    outcomes = []
    for runtime in (uncomposed, failing):
        app = _app(runtime)
        async with app.router.lifespan_context(app):
            async with _admin_client(app) as admin:
                with pytest.raises(StorefrontClientError):
                    await admin.admin_run_lifecycle_cycle("publication")
            outcomes.append(runtime.loops.last_outcome(PUBLICATION))

    refused, failed = outcomes
    assert (refused.trigger, refused.completed, refused.stage) == ("step", False, "compose")
    assert refused.error.to_dict() == {
        "type": "BareMetalPublicationError",
        "message": "no registry is configured for publication",
    }
    # The double names no stage of its own, so it fails in the step's compose.
    assert (failed.completed, failed.stage) == (False, "compose")
    assert failed.error.to_dict() == {"type": "ConnectionError", "message": None}


class _NothingDue:
    """A settlement repository with no due obligations, counting each sweep."""

    def __init__(self) -> None:
        self.sweeps = 0

    async def list_due_settlement_obligations(self, **_kwargs):
        self.sweeps += 1
        return []


def _runtime_with_servicing(path: str) -> tuple[BareMetalStorefrontRuntime, _NothingDue]:
    """A runtime whose settlement servicing is its own composed worker, sweeping a
    repository with nothing due, on an interval no test waits out."""
    repository = _NothingDue()
    runtime = dataclasses.replace(
        _runtime(path),
        settlement_composition=alkahest_composition(
            SELLER_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients={"anvil": object()},
        ),
        settlement_servicing_interval_seconds=3600,
    )
    # The worker's sweep reads its repository; counting sweeps there shows a
    # step runs exactly one cycle.
    runtime.settlement_worker._repository = repository
    return runtime, repository


async def test_the_pause_holds_every_loop_and_each_step_runs_while_held(tmp_path) -> None:
    runtime, repository = _runtime_with_servicing(str(tmp_path / "storefront.db"))
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            paused = await admin.admin_pause_lifecycle_loops()
            assert paused["paused"] is True
            assert paused["loops"] == {
                "negotiation_watchdog": "paused",
                "publication": "paused",
                "settlement_servicing": "paused",
            }

            servicing = await admin.admin_run_lifecycle_cycle("settlement-servicing")
            watchdog = await admin.admin_run_lifecycle_cycle("negotiation-watchdog")
            assert servicing == {"loop": "settlement_servicing", "processed": 0}
            assert watchdog == {"loop": "negotiation_watchdog", "abandoned": 0}
            assert repository.sweeps == 1, "a step must run exactly one cycle"
            assert set(runtime.loops.states().values()) == {"paused"}, (
                "a step must not resume the loops"
            )

            resumed = await admin.admin_resume_lifecycle_loops()
            assert resumed == {
                "paused": False,
                "loops": {
                    "negotiation_watchdog": "running",
                    "publication": "running",
                    "settlement_servicing": "running",
                },
            }


async def test_the_lifecycle_pause_refuses_an_unsigned_request(tmp_path) -> None:
    runtime, _repository = _runtime_with_servicing(str(tmp_path / "storefront.db"))
    app = _app(runtime)

    # Rejection path: an unsigned request is refused before any loop is held.
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/lifecycle/pause")

    assert response.status_code == 401
    assert not runtime.loops.is_pause_requested()


async def test_the_publication_preview_runs_one_dry_pass(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            preview = await admin.admin_dry_run_lifecycle_cycle("publication")

    assert preview["dry_run"] is True
    assert log == ["start first (dry run)", "end first"]


async def test_startup_starts_every_loop_on_the_controllers_timer(tmp_path) -> None:
    """Every loop the runtime composes is a timer the controller runs over the
    step its route runs, the site-projection poller and publication among them,
    and shutdown stops every one."""
    runtime, _repository = _runtime_with_servicing(str(tmp_path / "storefront.db"))
    runtime = dataclasses.replace(
        runtime,
        site_projections=_sited_runtime(
            str(tmp_path / "unused.db"), _sites(site_a=1)
        ).site_projections,
        loop_controller_factory=held_loop_controller,
    )
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        started = runtime.loops.registered_loop_names()
        routes = runtime.loops.step_routes()

    assert started == [
        "negotiation_watchdog",
        "publication",
        "settlement_servicing",
        "site_projection_poller",
    ]
    assert routes == {
        "negotiation-watchdog": "negotiation_watchdog",
        "publication": "publication",
        "settlement-servicing": "settlement_servicing",
        "site-projections": "site_projection_poller",
    }
    # Shutdown stopped and awaited every timer.
    assert runtime.loops.registered_loop_names() == []


async def test_a_storefront_without_settlement_servicing_steps_no_such_loop(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        assert runtime.loops.registered_loop_names() == ["negotiation_watchdog", "publication"]
        async with _admin_client(app) as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.admin_run_lifecycle_cycle("settlement-servicing")
    assert refused.value.status_code == 404


# A development identity; never used on any public network.
SITE_SIGNER = Eip191Signer(bytes.fromhex("44" * 32))


# A second site authority's key, also a development identity.
SITE_B_SIGNER = Eip191Signer(bytes.fromhex("45" * 32))


def _status_runtime(path: str, *, authorities=None, **changes) -> BareMetalStorefrontRuntime:
    runtime = _runtime(path)
    # The site reads status as its service peer, seeded as startup seeds it.
    bindings, trust = seeded_sites(
        runtime.db.db_path, authorities or {"site-a": SITE_SIGNER.identity}
    )
    return dataclasses.replace(
        runtime, site_bindings=bindings, service_peer_trust=trust, **changes
    )


def _status_client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def test_status_reports_what_a_deal_depends_on_and_health_does_not(
    tmp_path,
) -> None:
    runtime = _status_runtime(
        str(tmp_path / "storefront.db"),
        chain_clients={"anvil": object()},
        negotiation_policies=["escrow_shape_guard", "bisection"],
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _status_client(app, ADMIN_SIGNER, "admin") as admin:
            status = await admin.get_system_status()
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            health = await public.get_health()

    assert status.checks["registry"] == "unconfigured"
    assert status.checks["negotiation_strategy"] == "chain[3] (count=3)"
    assert status.checks["alkahest"] == "anvil"
    assert status.provisioning_contract_version == COMPUTE_PROVISIONING_CONTRACT_VERSION
    for name in ("registry", "negotiation_strategy", "alkahest"):
        assert name not in health.checks
    assert health.provisioning_contract_version is None


_REGISTRY_TRUST = RegistryAuthorityTrust(
    authority="registry",
    principals=TrustedIdentitySet(
        identities=(Identity(scheme="eip191", identifier="0x" + "aa" * 20),)
    ),
)


async def test_an_unreachable_registry_degrades_status(tmp_path) -> None:
    unreachable = BareMetalRegistryConfiguration(
        # Nothing listens on the discard port, so the connection is refused.
        authorities={"http://127.0.0.1:9": _REGISTRY_TRUST},
    )
    runtime = _status_runtime(
        str(tmp_path / "storefront.db"), registry_configuration=unreachable
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _status_client(app, ADMIN_SIGNER, "admin") as admin:
            status = await admin.get_system_status()

    assert status.checks["registry"].startswith("error: ")
    assert status.status == "degraded"


def test_each_status_check_is_judged_by_its_own_rule() -> None:
    assert _status_check_healthy("registry", "ok")
    assert _status_check_healthy("registry", "unconfigured")
    assert not _status_check_healthy("registry", "http_503")
    assert _status_check_healthy("negotiation_strategy", "chain[3] (count=3)")
    assert not _status_check_healthy(
        "negotiation_strategy", "chain[3] (exit_on_probe: guard)"
    )
    assert not _status_check_healthy("negotiation_strategy", "unknown: 'nope'")
    assert _status_check_healthy("alkahest", "anvil,base_sepolia")
    assert not _status_check_healthy("alkahest", "error: no client")


def test_a_registry_reply_that_is_not_signed_is_reported_unverifiable() -> None:
    """The registry client verifies every reply, so an unsigned one reads as
    the client's own 502 rather than as whatever status it carried."""
    configuration = BareMetalRegistryConfiguration(
        authorities={"http://registry": _REGISTRY_TRUST},
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, text="down"))

    result = asyncio.run(configuration.reachability(SELLER_SIGNER, transport=transport))

    assert result == "http_502"


def test_status_reads_every_registry_and_reports_the_first_that_fails() -> None:
    """Publication reaches every configured registry, so its status asks each:
    one answering is not enough while another does not."""
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.host)
        return httpx.Response(503, text="down")

    configuration = BareMetalRegistryConfiguration(
        authorities={
            "http://registry-a": _REGISTRY_TRUST,
            "http://registry-b": _REGISTRY_TRUST,
        },
    )

    result = asyncio.run(
        configuration.reachability(SELLER_SIGNER, transport=httpx.MockTransport(answer))
    )

    assert result == "http_502"
    assert asked == ["registry-a"], "the first failure is reported without asking on"


async def test_every_configured_sites_peer_reads_status(tmp_path) -> None:
    """The read names no site, so with two sites each bound to its own peer,
    site B's peer reads status as site A's does."""
    runtime = _status_runtime(
        str(tmp_path / "storefront.db"),
        authorities={"site-a": SITE_SIGNER.identity, "site-b": SITE_B_SIGNER.identity},
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _status_client(app, SITE_SIGNER, "service") as site_a:
            read_by_a = await site_a.get_system_status()
        async with _status_client(app, SITE_B_SIGNER, "service") as site_b:
            read_by_b = await site_b.get_system_status()

    assert read_by_a.checks["database"] == "ok"
    assert read_by_b.checks["database"] == "ok"
    assert read_by_b.settlement_manual_required is None


async def test_a_configured_site_reads_status_as_a_service_and_another_cannot(
    tmp_path,
) -> None:
    impostor = Eip191Signer(bytes.fromhex("55" * 32))
    runtime = _status_runtime(str(tmp_path / "storefront.db"))
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _status_client(app, SITE_SIGNER, "service") as site:
            status = await site.get_system_status()
        async with _status_client(app, ADMIN_SIGNER, "admin") as admin:
            administrator = await admin.get_system_status()
        async with _status_client(app, impostor, "service") as other:
            with pytest.raises(StorefrontClientError) as refused:
                await other.get_system_status()

    assert status.checks["database"] == "ok"
    assert status.provisioning_contract_version == COMPUTE_PROVISIONING_CONTRACT_VERSION
    # The site reads readiness alone; operator state is the administrator's.
    assert status.settlement_manual_required is None
    assert status.extra.get("pool_overrides") is None
    assert administrator.settlement_manual_required == 0
    assert refused.value.status_code in (401, 403)
