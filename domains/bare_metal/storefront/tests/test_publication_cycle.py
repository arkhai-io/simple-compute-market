"""The bare-metal publication cycle's orchestration and persistence.

The cycle's public API runs against a real storefront database and a real
held projection state, with the site authorities and the registry replaced by
doubles: each site answers with a resource-pool projection built from the
site-client contract fixture, its bare-metal views from this domain's view
fixture, and the registry client records what each registry is sent. The state
holds what each site served at its last poll, as it does in production, so a
run polls every site first, as the lane steps ``site-projections`` before
publication; a site that has never answered is a storefront restarted while it
was unreachable.

This is not integration evidence under ``docs/development/TESTING.md``. The
bare-metal storefront is an application, and the site authority and the
registry are this repository's own services rather than external boundaries,
so these tests prove how a run orchestrates, persists, closes, holds, and
converges, and nothing about either service's contract. That contract is
covered elsewhere: the projection and its bare-metal view over the canonical
site client against the real provisioning service, the view's contract fixture
on both sides, and the composition of the cycle the running storefront's
publication step runs (``test_publication_cli.py``, ``test_http_system.py``).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

import pytest
from arkhai_bare_metal import derive_bare_metal_shape
from core_storefront.aggregation import AggregateCapacityClient
from arkhai_bare_metal.fixtures.publication_view import (
    DEFAULT_CAPACITY,
    DEFAULT_GPU_MODEL,
    build_bare_metal_publication_view,
)
from core_storefront.publication_runner import NoSettlementOption, PublicationPayload
from market_alkahest import AlkahestChainProbe, ProbedChain
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_capacity_publication import (
    BoundListing,
    PublicationBinding,
    SiteDerivationLog,
    SiteProjectionState,
)
from market_identity import TrustedIdentitySet, create_signer
from market_resource_pools_contracts.backing import BACKED, UNBACKED, CapacityBacking
from market_pool_overrides import PoolOverrideRecord, SQLitePoolOverrideStore
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_projection,
    build_resource_pool_row,
)

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.listing_source_check import build_listing_source_check
from arkhai_bare_metal_storefront.pool_overrides import compile_publication_clauses
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.publication_composition import (
    publication_payload_builder,
)
from arkhai_bare_metal_storefront.publication_service import build_publication_runtime
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from settlement_compositions import ALKAHEST_SECTION, alkahest_composition

REGISTRY_URL = "https://registry.example"
STOREFRONT_URL = "https://seller.example"
# A development signer; never used on any public network.
SELLER = create_signer("ed25519", b"\x21" * 32).identity


# -- site ------------------------------------------------------------------


def member(
    resource_id: str,
    pool_id: str,
    *,
    enabled: bool = True,
    available: bool = True,
    host_id: str | None = None,
    view_pool_id: str | None = "",
    capacity: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    capabilities: dict[str, Any] | None = None,
    backing: CapacityBacking = BACKED,
) -> dict[str, Any]:
    """A projected pool member carrying its declaration and its bare-metal view.

    The declaration is a whole machine: one unit holding the default hardware,
    with the GPU model as a declared attribute. The site's view repeats the
    capacity and folds enablement into ``available``, as the provisioning
    service builds it for a pool of ``backing``. ``available=False`` also
    reports none of the declared capacity available in the site's ledger,
    where a machine taken shows whatever its backing: an unbacked view carries
    no availability of its own. ``host_id`` and ``physical_host_id`` are what
    the view builder is given; the backing's delegate decides whether the view
    carries them.
    """
    declared = dict(DEFAULT_CAPACITY if capacity is None else capacity)
    return build_projected_resource(
        resource_id,
        capacity=declared,
        available=None if available else {dimension: 0 for dimension in declared},
        attributes={"gpu_model": DEFAULT_GPU_MODEL} if attributes is None else attributes,
        enabled=enabled,
        publication_views={
            "bare_metal.v2": build_bare_metal_publication_view(
                resource_id,
                backing=backing,
                pool_id=pool_id if view_pool_id == "" else view_pool_id,
                host_id=host_id or f"machine-{resource_id}",
                physical_host_id=f"physical-{resource_id}",
                available=enabled and available,
                capacity=declared,
                capabilities=capabilities,
            )
        },
    )


def pool(pool_id: str, *members: dict[str, Any], **declarations: Any) -> dict[str, Any]:
    """A projected pool; it advertises bare metal and states a region unless told."""
    declarations.setdefault("advertisable_modes", ("bare_metal",))
    declarations["policy_tags"] = {"region": "us-west", **declarations.get("policy_tags", {})}
    return build_resource_pool_row(pool_id, resources=members, **declarations)


def unresolvable(pool_id: str, *members: dict[str, Any]) -> dict[str, Any]:
    return pool(pool_id, *members, policy_tags={"capacity_backing": "sometimes"})


class Site:
    """A site authority's typed client, answering both projection families.

    It serves the resource-pool projection a test sets and an empty
    capacity-bucket projection; ``calls`` counts every call made to it.
    """

    def __init__(self, *pools: dict[str, Any]) -> None:
        self.calls = 0
        self.serve(*pools)

    def serve(self, *pools: dict[str, Any]) -> None:
        self.revision = getattr(self, "revision", 0) + 1
        self.response: dict[str, Any] | None = {
            "revision": self.revision,
            "digest": f"digest-{self.revision}",
            **build_resource_pool_projection(pools),
        }
        self.error: Exception | None = None

    def fail(self) -> None:
        self.error = ConnectionError("site unreachable")

    def _answer(self) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        response = self._answer()
        return {"revision": response["revision"], "digest": response["digest"]}

    async def resource_pool_projection(self) -> dict[str, Any]:
        return self._answer()

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        self._answer()
        return {"revision": 1, "digest": "buckets-1"}

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        self._answer()
        return {"revision": 1, "digest": "buckets-1", "capacity_buckets": []}

    def set_topology_error_handler(self, _handler: Any) -> None:
        return None


def projections_over(
    sites: dict[str, Site],
    *,
    wakes: list[str] | None = None,
    on_resource_pool_change: Any = None,
):
    """The storefront's held projection state over ``sites``, holding nothing yet.

    ``on_resource_pool_change`` is the publication wake the state raises; with
    none given, ``wakes`` records each one.
    """
    recorded = wakes if wakes is not None else []
    return SiteProjectionState(
        AggregateCapacityClient(dict(sites)),
        on_resource_pool_change=on_resource_pool_change
        or (lambda: recorded.append("wake")),
    )


# -- registry --------------------------------------------------------------


class RecordingRegistries:
    """Stands where ``MultiRegistryClient`` wraps the registry, recording sends.

    ``failing`` holds ``(operation, url)`` pairs that fail until removed; an
    update's operation is the status it sets.
    """

    def __init__(self) -> None:
        self.urls = [REGISTRY_URL]
        self.sent: list[tuple[str, str, str, dict[str, Any]]] = []
        self.failing: set[tuple[str, str]] = set()

    def __call__(self) -> "RecordingRegistries":
        return self

    async def __aenter__(self) -> "RecordingRegistries":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    def _result(self, operation: str, url: str) -> dict[str, Any]:
        if (operation, url) in self.failing:
            return {"registry_url": url, "success": False, "error": "unreachable"}
        return {"registry_url": url, "success": True, "response": {"ok": True}}

    async def publish_listing_per_registry(self, *, payloads):
        results = []
        for url, request in payloads.items():
            body = request.to_dict()
            self.sent.append(("publish", url, str(body["listing_id"]), body))
            results.append(self._result("publish", url))
        return results

    async def update_listing_per_registry(self, *, listing_id, payloads):
        results = []
        for url, request in payloads.items():
            body = request.to_dict()
            status = str(body["status"])
            self.sent.append((status, url, listing_id, body))
            results.append(self._result(status, url))
        return results

    def operations(self) -> list[tuple[str, str]]:
        return [(operation, listing_id) for operation, _url, listing_id, _ in self.sent]


# -- storefront ------------------------------------------------------------


class Terms:
    """The configured publication inputs, as the payload builder reads them."""

    def __init__(self) -> None:
        self.max_duration_seconds = 3600

    async def __call__(self, candidate: dict[str, Any]) -> PublicationPayload:
        return PublicationPayload(max_duration_seconds=self.max_duration_seconds)


class Storefront:
    """One storefront process: its database, its held projections, its terms.

    A second ``Storefront`` over the same database is the storefront restarted:
    its projection state holds nothing until it polls.
    """

    def __init__(self, db: SQLiteClient, sites: dict[str, Site]) -> None:
        self.db = db
        self.sites = sites
        self.wakes: list[str] = []
        self.stages: list[str] = []
        self.projections = projections_over(sites, wakes=self.wakes)
        self.registries = RecordingRegistries()
        self.terms = Terms()
        # The storefront's one site-derivation log, which status serves.
        self.derivation = SiteDerivationLog()
        # The configured [pricing].default_max_duration_seconds; a pool resolves
        # its lease bound from its override first, then from this.
        self.default_max_duration: int | None = 3600

    async def run(self, *, dry_run: bool = False, poll: bool = True) -> dict[str, Any]:
        """Poll every site, as the lane steps ``site-projections``, then run a cycle.

        With ``poll`` false the cycle reads what the state already holds.
        """
        if poll:
            await self.projections.poll_once()
        self.registries.sent.clear()
        cycle = BareMetalPublicationCycle(
            sqlite_client=self.db,
            registry=build_bare_metal_storefront_registry(
                domain=get_market_domain_contract()
            ),
            site_projections=self.projections,
            site_ids=list(self.sites),
            registry_client_factory=self.registries,
            registry_urls=(REGISTRY_URL,),
            storefront_url=STOREFRONT_URL,
            seller_principal=SELLER,
            build_payload=self.terms,
            default_max_duration_seconds=self.default_max_duration,
            enter_stage=self.stages.append,
            derivation=self.derivation,
        )
        return await cycle.run(dry_run=dry_run)

    def refusals(self, site: str = "site-a") -> list[dict[str, Any]]:
        """The site's refusals, as its derivation log holds them for status."""
        return self.derivation.latest().get(site, {}).get("refusals", [])

    def listings(self) -> dict[tuple[str, str | None, str], tuple[str, str, str | None]]:
        """``(site, pool, resource) -> (listing_id, status, closed_by)``."""
        with sqlite3.connect(self.db.db_path) as conn:
            rows = conn.execute(
                """
                SELECT b.site_id, b.pool_id, b.physical_resource_id,
                       l.listing_id, l.status, l.closed_by
                FROM storefront_listing_bindings b
                JOIN listings l ON l.listing_id = b.listing_id
                """
            ).fetchall()
        return {(r[0], r[1], r[2]): (r[3], r[4], r[5]) for r in rows}

    def listing(self, site: str, pool_id: str | None, resource: str):
        return self.listings()[(site, pool_id, resource)]

    def stored(self, listing_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db.db_path) as conn:
            row = conn.execute(
                "SELECT max_duration_seconds, listing_resource FROM listings "
                "WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
        return {"max_duration_seconds": row[0], "listing_resource": row[1]}


def closes(report: dict[str, Any]) -> dict[str, str]:
    return {
        item["listing_id"]: item["reason"]
        for item in report["actions"]
        if item["action"] == "close"
    }


def actions(report: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [item for item in report["actions"] if item["action"] == action]


@pytest.fixture
def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(str(tmp_path / "storefront.db"))


# -- pool declarations -----------------------------------------------------


async def test_a_pool_advertising_bare_metal_publishes(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    report = await storefront.run()

    listing_id, status, _ = storefront.listing("site-a", "pool-1", "r1")
    assert status == "open"
    assert storefront.registries.operations() == [("publish", listing_id)]
    (published,) = actions(report, "publish")
    assert published["listing_id"] == listing_id
    body = storefront.registries.sent[0][3]
    assert body["listing_resource"]["offering_mode"] == "bare_metal"
    assert body["listing_resource"]["capacity_backing"] == "backed"


@pytest.mark.parametrize(
    "withdrawn",
    [
        {"advertisable_modes": ("vm",)},
        {"enabled": False},
    ],
    ids=["stops-advertising", "disabled"],
)
async def test_a_pool_that_stops_admitting_bare_metal_closes_as_source_gone(db, withdrawn):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id, _, _ = storefront.listing("site-a", "pool-1", "r1")

    site.serve(pool("pool-1", member("r1", "pool-1"), **withdrawn))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "reconciliation")
    assert closes(report) == {listing_id: "source_gone"}
    assert storefront.registries.operations() == [("closed", listing_id)]


async def test_an_unresolvable_pools_listing_is_neither_closed_nor_refreshed(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id, _, _ = storefront.listing("site-a", "pool-1", "r1")

    site.serve(unresolvable("pool-1", member("r1", "pool-1")), pool("pool-2"))
    storefront.terms.max_duration_seconds = 7200
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1] == "open"
    assert storefront.stored(listing_id)["max_duration_seconds"] == 3600
    assert storefront.registries.operations() == []
    assert any(
        item.get("pool_id") == "pool-1" and item["reason"] == "pool_unresolvable"
        for item in actions(report, "hold")
    )


def unbacked_pool(*members: dict[str, Any], pool_id: str = "pool-u", **declarations: Any):
    """An unbacked pool advertising bare metal, delivering nothing."""
    return pool(pool_id, *members, capacity_backing="unbacked", **declarations)


def unbacked_member(resource_id: str, pool_id: str = "pool-u", **changes: Any):
    """A member of an unbacked pool, its view built as if from a declaration
    naming a host, as the site projects it: the view carries no delivery term."""
    return member(resource_id, pool_id, backing=UNBACKED, **changes)


def _binding_backing(db: SQLiteClient, listing_id: str) -> tuple[str, dict[str, Any]]:
    """A listing's recorded backing and source envelope."""
    with sqlite3.connect(db.db_path) as conn:
        backing, envelope = conn.execute(
            "SELECT capacity_backing, source_envelope_json FROM storefront_listing_bindings "
            "WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
    return backing, json.loads(envelope)


async def test_an_unbacked_pool_publishes_an_unbacked_listing_with_no_delivery_terms(db):
    """Spec scenarios "An unbacked pool advertises bare metal" and "An unbacked
    declaration names a host": the listing is bound and published unbacked, and
    neither it nor its binding carries a host or access methods."""
    storefront = Storefront(db, {"site-a": Site(unbacked_pool(unbacked_member("r1")))})

    report = await storefront.run()

    listing_id, status, _ = storefront.listing("site-a", "pool-u", "r1")
    assert status == "open"
    assert storefront.registries.operations() == [("publish", listing_id)]
    published = storefront.registries.sent[0][3]["listing_resource"]
    assert published["capacity_backing"] == "unbacked"
    for term in ("host_id", "physical_host_id", "access_methods", "available"):
        assert term not in published
    backing, envelope = _binding_backing(db, listing_id)
    assert backing == "unbacked"
    assert "host_id" not in envelope and "physical_host_id" not in envelope
    assert actions(report, "refuse") == []


async def test_an_unbacked_listing_is_never_judged_against_availability(db):
    """Spec scenario "An unbacked resource's capacity is consumed": the site's
    ledger reports none of the machine's capacity available, and an unbacked
    view carries no availability, so the listing stays open, neither closed
    nor refreshed."""
    site = Site(unbacked_pool(unbacked_member("r1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-u", "r1")[0]

    site.serve(unbacked_pool(unbacked_member("r1", available=False)))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-u", "r1") == (listing_id, "open", None)
    assert closes(report) == {}
    assert storefront.registries.operations() == []


@pytest.mark.parametrize(
    "withdrawn",
    [{"enabled": False}, {"advertisable_modes": ("vm",)}],
    ids=["pool-disabled", "stops-advertising"],
)
async def test_a_withdrawn_unbacked_pools_listing_closes_on_the_next_cycle(db, withdrawn):
    """Source reconciliation is the only reconciliation an unbacked listing gets,
    and the publication cycle, the one the loop's timer runs, closes it."""
    site = Site(unbacked_pool(unbacked_member("r1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-u", "r1")[0]

    site.serve(unbacked_pool(unbacked_member("r1"), **withdrawn))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-u", "r1")[1:] == ("closed", "reconciliation")
    assert closes(report) == {listing_id: "source_gone"}


async def test_a_resource_the_site_built_no_view_for_is_reported_and_derives_nothing(db):
    """Spec scenario "The site cannot build a resource's view"."""
    unbuildable = build_projected_resource(
        "r2",
        capacity=dict(DEFAULT_CAPACITY),
        attributes={"gpu_model": DEFAULT_GPU_MODEL},
        publication_view_problems={"bare_metal.v2": ["host_id: required for backed supply"]},
    )
    storefront = Storefront(
        db, {"site-a": Site(pool("pool-1", member("r1", "pool-1"), unbuildable))}
    )

    report = await storefront.run()

    assert set(storefront.listings()) == {("site-a", "pool-1", "r1")}
    entry = {
        "action": "report",
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r2",
        "reason": "publication_view_unbuildable",
        "problems": ["host_id: required for backed supply"],
    }
    assert entry in report["actions"]
    assert [
        item["physical_resource_id"]
        for item in storefront.derivation.latest()["site-a"]["reports"]
        if item["reason"] == "publication_view_unbuildable"
    ] == ["r2"]


def unbuildable(resource_id: str, *, enabled: bool = True) -> dict[str, Any]:
    """A member whose declaration the site can build no bare-metal view from,
    projected with its problem in place of the view."""
    return build_projected_resource(
        resource_id,
        capacity=dict(DEFAULT_CAPACITY),
        attributes={"gpu_model": DEFAULT_GPU_MODEL},
        enabled=enabled,
        publication_view_problems={"bare_metal.v2": ["access_methods: required"]},
    )


async def test_an_open_listing_whose_view_the_site_can_no_longer_build_is_held(db):
    """A declaration the site cannot build a view from is unreadable, not
    withdrawn: the listing keeps its identity and its last terms, nothing is
    sent to a registry, and the site's derivation reports why. A changed
    configured term shows the listing is not refreshed either."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    published = storefront.stored(listing_id)

    site.serve(pool("pool-1", unbuildable("r1")))
    storefront.terms.max_duration_seconds = 7200
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert storefront.stored(listing_id) == published
    assert storefront.registries.operations() == []
    assert closes(report) == {}
    assert actions(report, "refresh") == [] and actions(report, "publish") == []
    assert {
        "action": "report",
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "reason": "publication_view_unbuildable",
        "problems": ["access_methods: required"],
    } in report["actions"]

    # Once the site can build the view again, the listing is reconciled as usual.
    site.serve(pool("pool-1", member("r1", "pool-1")))
    recovered = await storefront.run()

    assert [item["listing_id"] for item in actions(recovered, "refresh")] == [listing_id]
    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)


@pytest.mark.parametrize(
    "withdrawn",
    [
        pytest.param(lambda: pool("pool-1", unbuildable("r1", enabled=False)),
                     id="declaration-disabled"),
        pytest.param(
            lambda: pool("pool-1", unbuildable("r1"), advertisable_modes=("vm",)),
            id="pool-stops-advertising",
        ),
        pytest.param(lambda: pool("pool-1"), id="resource-removed"),
    ],
)
async def test_a_withdrawn_source_still_closes_whatever_its_view(db, withdrawn):
    """Holding an unbuildable view never keeps a withdrawn source open."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(withdrawn())
    report = await storefront.run()

    assert closes(report) == {listing_id: "source_gone"}
    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "reconciliation")
    assert storefront.registries.operations() == [("closed", listing_id)]


@pytest.mark.parametrize(
    ("policy_tags", "reason"),
    [
        pytest.param(lambda: {"region": None}, "pool_region_missing", id="region-missing"),
        pytest.param(
            lambda: {"asking_rates": {"bare_metal": [_rate("12.50", period="month")]}},
            "asking_rates_unreadable",
            id="asking-rate-unreadable",
        ),
    ],
)
async def test_an_unbacked_pools_hold_keeps_its_listing_open(db, policy_tags, reason):
    """The region and asking-rate holds apply to an unbacked pool exactly as to
    a backed one: the listing keeps its identity and terms, and nothing is sent."""
    site = Site(unbacked_pool(unbacked_member("r1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-u", "r1")[0]
    published = storefront.stored(listing_id)

    site.serve(unbacked_pool(unbacked_member("r1"), policy_tags=policy_tags()))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-u", "r1") == (listing_id, "open", None)
    assert storefront.stored(listing_id) == published
    assert storefront.registries.operations() == []
    assert closes(report) == {}
    (hold,) = actions(report, "hold")
    assert (hold["site_id"], hold["pool_id"], hold["reason"]) == ("site-a", "pool-u", reason)


# -- resources -------------------------------------------------------------


async def test_a_disabled_resource_closes_as_source_gone_and_a_leased_one_as_unavailable(db):
    site = Site(
        pool("pool-1", member("disabled", "pool-1"), member("leased", "pool-1"))
    )
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    disabled_id = storefront.listing("site-a", "pool-1", "disabled")[0]
    leased_id = storefront.listing("site-a", "pool-1", "leased")[0]

    # The disabled declaration's view also says unavailable; its class is
    # withdrawal all the same, and each listing is closed exactly once.
    site.serve(
        pool(
            "pool-1",
            member("disabled", "pool-1", enabled=False),
            member("leased", "pool-1", available=False),
        )
    )
    report = await storefront.run()

    assert closes(report) == {disabled_id: "source_gone", leased_id: "unavailable"}
    assert sorted(storefront.registries.operations()) == sorted(
        [("closed", disabled_id), ("closed", leased_id)]
    )

    site.serve(
        pool(
            "pool-1",
            member("disabled", "pool-1", enabled=False),
            member("leased", "pool-1"),
        )
    )
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "leased")[1:] == ("open", None)
    assert storefront.listing("site-a", "pool-1", "disabled")[1] == "closed"
    assert [item["listing_id"] for item in actions(report, "reopen")] == [leased_id]
    assert storefront.registries.operations() == [
        ("publish", leased_id),
        ("open", leased_id),
    ]


async def test_a_resource_moved_to_another_pool_closes_and_publishes_a_successor(db):
    site = Site(pool("pool-1", member("r1", "pool-1")), pool("pool-2"))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    old_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(pool("pool-1"), pool("pool-2", member("r1", "pool-2")))
    report = await storefront.run()

    new_id, status, _ = storefront.listing("site-a", "pool-2", "r1")
    assert new_id != old_id and status == "open"
    assert storefront.listing("site-a", "pool-1", "r1")[1] == "closed"
    assert closes(report) == {old_id: "source_gone"}
    assert storefront.registries.operations() == [
        ("closed", old_id),
        ("publish", new_id),
    ]


async def test_a_listing_bound_under_the_legacy_key_closes_and_its_successor_publishes(db):
    """A listing bound before the common key included the pool fails forward."""
    await db.upsert_listing(
        listing_id="legacy",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        listing_resource={
            "capacity_backing": "backed",
            "kind": "bare_metal.v2",
            "offering_mode": "bare_metal",
            "host_id": "machine-r1",
            "physical_host_id": "physical-r1",
            "access_methods": ["ssh"],
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url=STOREFRONT_URL,
        seller_principal=SELLER,
    )
    # Service-internal state no API expresses: the binding the historical
    # migration wrote, with no pool and the retired domain-table key.
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            """
            INSERT INTO storefront_listing_bindings(
              listing_id, site_id, pool_id, physical_resource_id, offering_mode,
              domain_identity, contract_major, contract_minor, derivation_key,
              source_envelope_json, last_reconciled_at, capacity_backing
            ) VALUES ('legacy', 'site-a', NULL, 'r1', 'bare_metal',
                      'bare_metal.v1', 1, 0, 'bare-metal:6:site-a:2:r1', ?,
                      '2026-01-01T00:00:00Z', 'backed')
            """,
            (
                json.dumps(
                    {
                        "host_id": "machine-r1",
                        "kind": "bare_metal.resource-projection.v1",
                        "physical_host_id": "physical-r1",
                        "physical_resource_id": "r1",
                        "schema_version": 1,
                        "site_id": "site-a",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    report = await storefront.run()

    assert storefront.listing("site-a", None, "r1")[:2] == ("legacy", "closed")
    successor, status, _ = storefront.listing("site-a", "pool-1", "r1")
    assert successor != "legacy" and status == "open"
    assert closes(report) == {"legacy": "source_gone"}


# -- sites -----------------------------------------------------------------


@pytest.mark.parametrize("unknown", ["unreachable-since-restart", "view-names-another-pool"])
async def test_an_unknown_site_keeps_its_listings_while_another_reconciles(db, unknown):
    """A site whose projection is not held, or whose held generation bare metal
    refuses, holds its listings while every other site reconciles. Spec
    scenarios "The storefront starts while a site is unreachable" and "A
    bare-metal site serves a generation bare metal refuses"."""
    site_a = Site(pool("pool-1", member("a1", "pool-1")))
    site_b = Site(pool("pool-1", member("b1", "pool-1")))
    storefront = Storefront(db, {"site-a": site_a, "site-b": site_b})
    await storefront.run()
    a_id = storefront.listing("site-a", "pool-1", "a1")[0]
    b_id = storefront.listing("site-b", "pool-1", "b1")[0]

    if unknown == "unreachable-since-restart":
        # The storefront restarts while site-a cannot be reached: its new
        # projection state never holds a generation of it.
        site_a.fail()
        storefront = Storefront(db, {"site-a": site_a, "site-b": site_b})
        reason = "site_projection_unknown"
    else:
        site_a.serve(
            pool("pool-vm", member("a1", "pool-vm", view_pool_id="pool-1"),
                 advertisable_modes=("vm",)),
        )
        reason = "site_projection_refused"
    site_b.serve(pool("pool-1", member("b1", "pool-1", enabled=False)))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "a1")[1] == "open"
    assert closes(report) == {b_id: "source_gone"}
    assert all(listing_id != a_id for _, listing_id in storefront.registries.operations())
    assert {"action": "hold", "site_id": "site-a", "reason": reason}.items() <= next(
        item for item in actions(report, "hold") if item["site_id"] == "site-a"
    ).items()


async def test_a_backed_view_without_its_availability_holds_the_site(db):
    """A backed pool's view owes every delivery term; one missing ``available``
    is malformed, so the site's whole generation is refused and its listings
    held, the hold carrying the validation error."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    malformed = member("r1", "pool-1")
    del malformed["publication_views"]["bare_metal.v2"]["available"]
    site.serve(pool("pool-1", malformed))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    assert closes(report) == {}
    (hold,) = [item for item in actions(report, "hold") if item["site_id"] == "site-a"]
    assert hold["reason"] == "site_projection_refused"
    assert "available" in hold["error"]


@pytest.mark.parametrize("malformation", ["unbacked-view-names-a-host", "row-not-a-mapping"])
async def test_a_malformed_generation_holds_its_site(db, malformation):
    """A view whose delivery terms its pool's backing forbids, or a pool row
    that is no mapping at all, refuses the site's generation: the site's
    listings are held and the cycle goes on. Spec scenario "An unbacked view
    carries a delivery term"."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    if malformation == "unbacked-view-names-a-host":
        # The view a site builds for a backed pool, in an unbacked one.
        site.serve(
            pool("pool-1", member("r1", "pool-1")),
            pool("pool-u", member("u1", "pool-u"), capacity_backing="unbacked"),
        )
        expected = "host_id"
    else:
        site.serve(pool("pool-1", member("r1", "pool-1")))
        site.response["resource_pools"].append("not a pool")
        expected = "mapping"
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    assert closes(report) == {}
    (hold,) = [item for item in actions(report, "hold") if item["site_id"] == "site-a"]
    assert hold["reason"] == "site_projection_refused"
    assert expected in hold["error"]


async def test_a_site_whose_poll_fails_keeps_deriving_from_its_last_generation(db):
    """A failed poll keeps the site's last generation, reported stale, and its
    listings keep deriving from it rather than becoming unknown. Spec scenario
    "An operator refreshes every site during an outage"."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.fail()
    storefront.terms.max_duration_seconds = 7200
    report = await storefront.run()

    assert storefront.projections.status()["site-a"]["resource_pool"].state == "stale"
    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert [item["listing_id"] for item in actions(report, "refresh")] == [listing_id]
    assert actions(report, "hold") == []


async def test_publication_and_the_opening_recheck_read_one_held_generation(db):
    """Both read the site's generation from the one state, and neither fetches
    the site. Spec scenario "Two consumers read one site"."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.projections.poll_once()
    calls = site.calls

    await storefront.run(poll=False)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    check = build_listing_source_check(
        db, storefront.projections, confirmation_window_seconds=60
    )
    verdict = await check(listing_id)

    assert verdict.outcome == "matches"
    assert site.calls == calls
    assert storefront.registries.operations() == [("publish", listing_id)]


async def test_a_cycle_names_each_stage_it_reaches(db):
    """Reading what it derives from, running the publication driver, and
    converging the registries, in order, for the loop controller's record."""
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    await storefront.run()

    assert storefront.stages == ["compose", "run", "converge"]


async def test_a_cycle_fetches_no_site_and_records_no_generation(db):
    """What a cycle reads is what the state held; a change the site makes after
    the last poll waits for the next one."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.projections.poll_once()
    site.serve(pool("pool-1", member("r1", "pool-1")), pool("pool-2", member("r2", "pool-2")))
    calls = site.calls

    await storefront.run(poll=False)

    assert site.calls == calls
    assert set(storefront.listings()) == {("site-a", "pool-1", "r1")}
    with sqlite3.connect(db.db_path) as conn:
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master")}
    assert not any("generation" in name for name in tables)


# -- ordering and convergence ----------------------------------------------


class FailingWrites(SQLiteClient):
    """Refuses every new listing write, as a full disk or lost volume would."""

    async def upsert_bare_metal_listing(self, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")


async def test_a_new_listing_whose_local_write_fails_reaches_no_registry(tmp_path):
    db = FailingWrites(str(tmp_path / "storefront.db"))
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    report = await storefront.run()

    assert storefront.listings() == {}
    assert storefront.registries.sent == []
    assert [item["reason"] for item in actions(report, "fail")] == ["disk I/O error"]


async def test_a_registry_that_missed_a_close_is_repaired_by_the_next_run_alone(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    storefront.registries.failing.add(("closed", REGISTRY_URL))
    site.serve(pool("pool-1", member("r1", "pool-1", enabled=False)))
    report = await storefront.run()
    assert storefront.listing("site-a", "pool-1", "r1")[1] == "closed"
    assert {"action": "fail", "listing_id": listing_id, "reason": "registry_not_converged"} in report["actions"]

    storefront.registries.failing.clear()
    report = await storefront.run()

    assert storefront.registries.operations() == [("closed", listing_id)]
    assert [item["listing_id"] for item in actions(report, "converge")] == [listing_id]
    assert actions(report, "fail") == []
    # Converged: a further run sends nothing.
    await storefront.run()
    assert storefront.registries.sent == []


async def test_a_registry_left_closed_by_a_failed_reopen_is_repaired_by_the_next_run(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    site.serve(pool("pool-1", member("r1", "pool-1", available=False)))
    await storefront.run()

    storefront.registries.failing.add(("open", REGISTRY_URL))
    site.serve(pool("pool-1", member("r1", "pool-1")))
    await storefront.run()
    assert storefront.listing("site-a", "pool-1", "r1")[1] == "open"

    storefront.registries.failing.clear()
    report = await storefront.run()

    assert storefront.registries.operations() == [
        ("publish", listing_id),
        ("open", listing_id),
    ]
    assert [item["listing_id"] for item in actions(report, "converge")] == [listing_id]
    await storefront.run()
    assert storefront.registries.sent == []


# -- an existing listing ---------------------------------------------------


async def test_a_sellers_close_is_left_closed(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    seller_close = build_publication_runtime(
        db,
        storefront.registries,
        registry_urls=(REGISTRY_URL,),
        storefront_url=STOREFRONT_URL,
    )
    await seller_close.close(
        BoundListing(listing_id, PublicationBinding("site-a", "bare_metal", "r1", BACKED)),
        closed_by="seller",
    )

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "seller")
    assert storefront.registries.sent == []
    assert {"action": "skip", "listing_id": listing_id, "reason": "closed_by_seller"} in report["actions"]


async def test_a_changed_term_refreshes_in_place(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    storefront.terms.max_duration_seconds = 7200
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert storefront.stored(listing_id)["max_duration_seconds"] == 7200
    assert [item["listing_id"] for item in actions(report, "refresh")] == [listing_id]
    assert storefront.registries.operations() == [("publish", listing_id)]
    assert storefront.registries.sent[0][3]["max_duration_seconds"] == 7200


async def test_an_unchanged_listing_sends_nothing(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()

    await storefront.run()

    assert storefront.registries.sent == []


async def test_a_changed_identity_closes_and_is_not_reopened(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(pool("pool-1", member("r1", "pool-1", host_id="machine-other")))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "reconciliation")
    assert closes(report) == {listing_id: "identity_changed"}

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1] == "closed"
    assert storefront.registries.sent == []
    refusal = {
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "listing_id": listing_id,
        "reason": "identity_changed",
        "fields": ["host_id"],
    }
    assert {"action": "refuse", **refusal} in report["actions"]
    # Named by its site, the refusal reaches the site's derivation status serves.
    refusal.pop("site_id")
    assert storefront.refusals() == [refusal]


async def test_a_pool_recreated_with_the_opposite_backing_closes_and_is_not_reopened(db):
    """Spec scenario "A pool is re-created with the opposite backing": the
    resource keeps its shape, so its candidate falls under the open listing's
    derivation key, and the backing comparison closes it first."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(unbacked_pool(unbacked_member("r1", "pool-1"), pool_id="pool-1"))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "reconciliation")
    assert closes(report) == {listing_id: "backing_changed"}

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[1] == "closed"
    assert {
        "action": "refuse",
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "listing_id": listing_id,
        "reason": "backing_changed",
        "fields": ["capacity_backing"],
    } in report["actions"]
    assert [(item["reason"], item["pool_id"]) for item in storefront.refusals()] == [
        ("backing_changed", "pool-1")
    ]


async def test_a_source_check_finds_the_backing_changed_as_a_declared_mismatch(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    check = build_listing_source_check(
        db, storefront.projections, confirmation_window_seconds=60
    )
    assert (await check(listing_id)).outcome == "matches"
    site.serve(unbacked_pool(unbacked_member("r1", "pool-1"), pool_id="pool-1"))
    await storefront.projections.poll_once()

    verdict = await check(listing_id)

    assert verdict.outcome == "declared_mismatch"
    assert verdict.differing_fields == ("capacity_backing",)


# -- shapes ----------------------------------------------------------------


def _bindings(db: SQLiteClient, resource: str) -> list[tuple[str, str, str, str]]:
    """``(listing_id, status, derivation_key, source_envelope_json)`` per binding."""
    with sqlite3.connect(db.db_path) as conn:
        return [
            tuple(row)
            for row in conn.execute(
                """
                SELECT b.listing_id, l.status, b.derivation_key, b.source_envelope_json
                FROM storefront_listing_bindings b
                JOIN listings l ON l.listing_id = b.listing_id
                WHERE b.physical_resource_id = ?
                ORDER BY l.created_at, b.listing_id
                """,
                (resource,),
            ).fetchall()
        ]


async def test_a_listing_publishes_its_shape_where_the_compute_schema_reads_it(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    await storefront.run()

    body = storefront.registries.sent[0][3]["listing_resource"]
    assert (body["gpu_count"], body["gpu_model"], body["ram_gb"]) == (8, "H200", 2048)
    assert body["region"] == "us-west"
    assert "capabilities" not in body and "site" not in body
    ((_, _, _, envelope),) = _bindings(db, "r1")
    assert json.loads(envelope)["schema_version"] == 2
    assert json.loads(envelope)["shape_digest"].startswith("capability-shape.v1:")


async def test_a_machine_without_gpus_publishes_with_no_gpu_key(db):
    cpu_only = member(
        "r1", "pool-1", capacity={"units": 1, "vcpu_count": 64, "ram_gb": 512}, attributes={}
    )
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", cpu_only))})

    report = await storefront.run()

    assert actions(report, "hold") == []
    assert storefront.listing("site-a", "pool-1", "r1")[1] == "open"
    ((operation, _, _, sent),) = storefront.registries.sent
    body = sent["listing_resource"]
    assert operation == "publish"
    assert (body["vcpu_count"], body["ram_gb"], body["region"]) == (64, 512, "us-west")
    assert "gpu_count" not in body and "gpu_model" not in body
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    stored = json.loads(storefront.stored(listing_id)["listing_resource"])
    assert "gpu_count" not in stored and "gpu_model" not in stored

    await storefront.run()

    assert storefront.registries.operations() == []


async def test_a_corrected_declaration_closes_and_publishes_a_successor(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    ((first_id, _, first_key, first_envelope),) = _bindings(db, "r1")

    site.serve(
        pool("pool-1", member("r1", "pool-1", capacity={"units": 1, "gpu_count": 8, "ram_gb": 4096}))
    )
    report = await storefront.run()

    (first, second) = _bindings(db, "r1")
    assert first == (first_id, "closed", first_key, first_envelope)
    assert second[1] == "open" and second[2] != first_key
    assert closes(report) == {first_id: "source_gone"}
    assert storefront.registries.operations() == [("closed", first_id), ("publish", second[0])]
    assert storefront.registries.sent[1][3]["listing_resource"]["ram_gb"] == 4096


async def test_an_unchanged_declaration_keeps_its_listing(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()

    site.serve(pool("pool-1", member("r1", "pool-1")))
    report = await storefront.run()

    assert len(_bindings(db, "r1")) == 1
    assert closes(report) == {}
    assert storefront.registries.operations() == []


async def test_a_pool_without_a_region_is_held_and_reported(db):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id, _, _ = storefront.listing("site-a", "pool-1", "r1")

    site.serve(
        pool("pool-1", member("r1", "pool-1"), policy_tags={"region": ""}),
        pool("pool-2", member("r2", "pool-2"), policy_tags={"region": None}),
    )
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    assert ("site-a", "pool-2", "r2") not in storefront.listings()
    held = {(item["pool_id"], item["reason"]) for item in actions(report, "hold")}
    assert held == {("pool-1", "pool_region_missing"), ("pool-2", "pool_region_missing")}
    assert storefront.registries.operations() == []


async def test_an_unreadable_declaration_holds_only_its_own_listing(db):
    site = Site(pool("pool-1", member("r1", "pool-1"), member("r2", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    r1_id, _, _ = storefront.listing("site-a", "pool-1", "r1")

    site.serve(
        pool(
            "pool-1",
            member("r1", "pool-1", attributes={}),
            member("r2", "pool-1", enabled=False),
        )
    )
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (r1_id, "open")
    assert storefront.listing("site-a", "pool-1", "r2")[1] == "closed"
    (hold,) = actions(report, "hold")
    assert (hold["physical_resource_id"], hold["reason"]) == ("r1", "declaration_unresolvable")
    assert any("gpu.model" in problem for problem in hold["problems"])


async def test_a_declaration_never_readable_publishes_nothing(db):
    storefront = Storefront(
        db,
        {"site-a": Site(pool("pool-1", member("r1", "pool-1", capacity={"gpu_count": 8})))},
    )

    report = await storefront.run()

    assert storefront.listings() == {}
    (hold,) = actions(report, "hold")
    assert hold["reason"] == "declaration_unresolvable"


async def test_bare_metal_listing_shapes_and_publication_capabilities_are_reported(db):
    storefront = Storefront(
        db,
        {
            "site-a": Site(
                pool(
                    "pool-1",
                    member("r1", "pool-1", capabilities={"gpu_model": "B200"}),
                    policy_tags={"listing_shapes": {"bare_metal": [{"gpu": {"count": 1}}]}},
                )
            )
        },
    )

    report = await storefront.run()

    reasons = {item["reason"] for item in actions(report, "report")}
    assert reasons == {"listing_shapes_not_applicable", "publication_capabilities_ignored"}
    body = storefront.registries.sent[0][3]["listing_resource"]
    assert body["gpu_model"] == "H200"


# -- asking rates ---------------------------------------------------------------

MACHINE_SHAPE = derive_bare_metal_shape(DEFAULT_CAPACITY, {"gpu_model": DEFAULT_GPU_MODEL})


def _priced(*rates: dict[str, Any], resource: str = "r1") -> dict[str, Any]:
    return pool(
        "pool-1", member(resource, "pool-1"),
        policy_tags={"asking_rates": {"bare_metal": list(rates)}},
    )


def _rate(amount: str, *, shape=None, period: str = "hour") -> dict[str, Any]:
    return {"shape": shape or MACHINE_SHAPE, "amount": amount, "asset": "usd", "period": period}


async def test_a_priced_machine_publishes_its_asking_rate(db):
    storefront = Storefront(db, {"site-a": Site(_priced(_rate("12.50")))})

    await storefront.run()

    body = storefront.registries.sent[0][3]["listing_resource"]
    assert body["asking_rate"] == {"amount": "12.50", "asset": "usd", "period": "hour"}


async def test_an_unpriced_machine_publishes_no_rate_field(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})

    await storefront.run()

    assert "asking_rate" not in storefront.registries.sent[0][3]["listing_resource"]


async def test_a_rate_change_or_removal_refreshes_in_place(db):
    site = Site(_priced(_rate("12.50")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(_priced(_rate("11.00")))
    changed = await storefront.run()
    changed_body = storefront.registries.sent[0][3]["listing_resource"]
    site.serve(pool("pool-1", member("r1", "pool-1")))
    removed = await storefront.run()
    removed_body = storefront.registries.sent[0][3]["listing_resource"]

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert [item["fields"] for item in actions(changed, "refresh")] == [["asking_rate"]]
    assert [item["fields"] for item in actions(removed, "refresh")] == [["asking_rate"]]
    assert changed_body["asking_rate"]["amount"] == "11.00"
    assert "asking_rate" not in removed_body


async def test_an_unreadable_rate_holds_the_pool_and_keeps_its_listing(db):
    site = Site(_priced(_rate("12.50")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    site.serve(_priced(_rate("12.50", period="month")))
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    # The pool is held once, naming why, rather than once per machine.
    (hold,) = actions(report, "hold")
    assert (hold["pool_id"], hold["reason"]) == ("pool-1", "asking_rates_unreadable")
    assert "physical_resource_id" not in hold and hold["problems"]
    assert storefront.registries.operations() == []


async def test_a_rate_for_a_shape_no_machine_has_is_reported(db):
    other = {"gpu": {"count": 1, "model": DEFAULT_GPU_MODEL}}
    storefront = Storefront(
        db, {"site-a": Site(_priced(_rate("12.50"), _rate("2.00", shape=other)))}
    )

    report = await storefront.run()

    (reported,) = [
        item for item in actions(report, "report")
        if item["reason"] == "asking_rate_shape_unpublished"
    ]
    assert reported["shapes"] == [other]


# -- storefront pool overrides -------------------------------------------------


async def _override(db: SQLiteClient, **stated: Any) -> None:
    await SQLitePoolOverrideStore(db.db_path).replace(
        PoolOverrideRecord(site_id="site-a", pool_id="pool-1", offering_mode="bare_metal",
                           **stated)
    )


async def test_an_override_rate_and_bound_reach_the_published_listing(db):
    site = Site(_priced(_rate("12.50")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    await _override(db, asking_rates=[_rate("9.00")], terms={"min_duration_seconds": 3600})
    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    body = storefront.registries.sent[0][3]["listing_resource"]
    assert body["asking_rate"]["amount"] == "9.00"
    assert body["min_duration_seconds"] == 3600
    assert sorted(actions(report, "refresh")[0]["fields"]) == [
        "asking_rate", "min_duration_seconds",
    ]


async def test_an_unreadable_stored_override_holds_its_pool(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    conn = sqlite3.connect(db.db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO pool_overrides (site_id, pool_id, offering_mode, terms) "
                "VALUES ('site-a', 'pool-1', 'bare_metal', '{not json')"
            )
    finally:
        conn.close()

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    assert {item["reason"] for item in actions(report, "hold")} == {"pool_override_unreadable"}
    assert storefront.registries.operations() == []


async def test_an_override_minimum_above_the_configured_maximum_holds_its_pool(db):
    """Written while the configured maximum allowed it; configuration then fell
    below the override's minimum, so the effective pair is unordered."""
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    storefront.default_max_duration = 10800
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    await _override(db, terms={"min_duration_seconds": 7200})
    storefront.default_max_duration = 3600

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1")[:2] == (listing_id, "open")
    assert {item["reason"] for item in actions(report, "hold")} == {
        "pool_override_terms_conflict"
    }
    assert storefront.registries.operations() == []


async def test_a_pool_resolving_no_lease_bound_is_held_while_others_publish(db):
    """No configured default maximum: the pool whose override states one
    publishes, the pool with nothing to publish as its maximum is held and
    reported, and the cycle completes. Spec scenario: "A bare-metal pool
    resolves no lease bound"."""
    site = Site(pool("pool-1", member("r1", "pool-1")), pool("pool-2", member("r2", "pool-2")))
    storefront = Storefront(db, {"site-a": site})
    storefront.default_max_duration = None
    await _override(db, terms={"max_duration_seconds": 7200})

    report = await storefront.run()

    assert set(storefront.listings()) == {("site-a", "pool-1", "r1")}
    assert actions(report, "hold") == [
        {
            "action": "hold",
            "site_id": "site-a",
            "pool_id": "pool-2",
            "reason": "pool_lease_bound_missing",
        }
    ]


@pytest.mark.parametrize("bound", [0, -1])
async def test_a_bound_that_is_not_positive_holds_its_pools_listings_open(db, bound):
    """A configured maximum that bounds nothing holds rather than closes: the
    listing it published under an earlier bound stays as it was."""
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    storefront.default_max_duration = bound

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert {item["reason"] for item in actions(report, "hold")} == {
        "pool_lease_bound_missing"
    }
    assert storefront.registries.operations() == []


async def test_stored_terms_that_are_not_a_mapping_hold_rather_than_read_as_absent(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()
    conn = sqlite3.connect(db.db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO pool_overrides (site_id, pool_id, offering_mode, terms) "
                "VALUES ('site-a', 'pool-1', 'bare_metal', '[]')"
            )
    finally:
        conn.close()

    report = await storefront.run()

    assert {item["reason"] for item in actions(report, "hold")} == {"pool_override_unreadable"}


# -- dry run ---------------------------------------------------------------


def _row_counts(db: SQLiteClient) -> dict[str, int]:
    with sqlite3.connect(db.db_path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for (table,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }


async def test_a_dry_run_reports_the_opens_a_pass_would_make_and_writes_nothing(db):
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    before = _row_counts(db)

    preview = await storefront.run(dry_run=True)

    assert preview["dry_run"] is True
    assert len(actions(preview, "publish")) == 1
    assert storefront.registries.sent == []
    assert _row_counts(db) == before
    report = await storefront.run()
    assert len(actions(report, "publish")) == 1


async def test_a_dry_run_logs_a_refresh_it_would_make_as_a_preview_not_a_failure(
    db, caplog
):
    """A previewed refresh is logged as what it would do, at info, and the
    cycle logs no failed candidate."""
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    await storefront.run()
    kept = storefront.listing("site-a", "pool-1", "r1")[0]
    storefront.terms.max_duration_seconds = 7200

    with caplog.at_level(logging.INFO, logger="arkhai_bare_metal_storefront.publication"):
        preview = await storefront.run(dry_run=True)

    logged = [
        record
        for record in caplog.records
        if record.name == "arkhai_bare_metal_storefront.publication"
    ]
    (refresh,) = actions(preview, "refresh")
    assert refresh["listing_id"] == kept
    assert [(record.levelno, record.getMessage()) for record in logged] == [
        (
            logging.INFO,
            f"bare-metal listing {kept} would be refreshed (dry run): {refresh['fields']}",
        )
    ]


async def test_a_dry_run_logs_a_reopen_it_would_make_as_a_preview_not_a_failure(
    db, caplog
):
    """A listing closed while its machine was leased would be reopened once it
    is free again: the preview reports the reopen, logs it at info, reopens
    nothing, and logs no failed candidate."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    leased = storefront.listing("site-a", "pool-1", "r1")[0]
    site.serve(pool("pool-1", member("r1", "pool-1", available=False)))
    await storefront.run()
    site.serve(pool("pool-1", member("r1", "pool-1")))

    with caplog.at_level(logging.INFO, logger="arkhai_bare_metal_storefront.publication"):
        preview = await storefront.run(dry_run=True)

    logged = [
        record
        for record in caplog.records
        if record.name == "arkhai_bare_metal_storefront.publication"
    ]
    (reopen,) = actions(preview, "reopen")
    assert (reopen["listing_id"], reopen["status"]) == (leased, "dry_run")
    assert [(record.levelno, record.getMessage()) for record in logged] == [
        (
            logging.INFO,
            f"bare-metal listing {leased} would be reopened (dry run): {reopen['fields']}",
        )
    ]
    assert storefront.listing("site-a", "pool-1", "r1")[1] == "closed"
    assert storefront.registries.sent == []


async def test_a_dry_run_reports_closes_and_refreshes_and_applies_neither(db):
    site = Site(pool("pool-1", member("r1", "pool-1")), pool("pool-2", member("r2", "pool-2")))
    storefront = Storefront(db, {"site-a": site})
    await storefront.run()
    kept = storefront.listing("site-a", "pool-1", "r1")[0]
    withdrawn = storefront.listing("site-a", "pool-2", "r2")[0]

    site.serve(
        pool("pool-1", member("r1", "pool-1")),
        pool("pool-2", member("r2", "pool-2"), enabled=False),
    )
    storefront.terms.max_duration_seconds = 7200
    before = _row_counts(db)
    preview = await storefront.run(dry_run=True)

    assert closes(preview) == {withdrawn: "source_gone"}
    assert [item["listing_id"] for item in actions(preview, "refresh")] == [kept]
    assert storefront.registries.sent == []
    assert _row_counts(db) == before
    assert storefront.listing("site-a", "pool-2", "r2")[1] == "open"
    assert storefront.stored(kept)["max_duration_seconds"] == 3600


# -- settlement terms ------------------------------------------------------

# Development values only; never used on any public network. The chain ID is
# one no other test resolves a token on, because resolved token metadata is
# held per chain for the life of the process.
SELLER_WALLET = "0x" + "33" * 20
DEAL_TOKEN = "0x" + "22" * 20
DEAL_CHAIN_ID = 424242


ALKAHEST_ADDRESS_BOOK = str(anvil_address_book_path())


#: The storefront's configured ``[pricing].settlements``: one Alkahest clause on
#: the anvil chain, which the production payload builder reads; ``Terms``
#: builds each payload without reading them.
CONFIGURED_CLAUSES_RAW = (
    {
        "mechanism": "alkahest.v1",
        "asset": DEAL_TOKEN,
        "rate": "1",
        "per": "hour",
        "mechanism_input": {
            "chain": "anvil",
            "escrow_kind": "erc20_escrow_obligation_default",
        },
    },
)
CONFIGURED_CLAUSES = compile_publication_clauses(list(CONFIGURED_CLAUSES_RAW))


def alkahest_publication(tmp_path, monkeypatch, signer):
    """Alkahest settlement publishing one clause on the anvil chain.

    Returns the composition and the configured publication clauses, as the
    runtime holds them from ``[pricing].settlements``. The deal token's metadata
    is cached where the option builder reads it, so the real Alkahest option
    builds without a chain to ask.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    tokens = tmp_path / "cache" / "arkhai" / "tokens"
    tokens.mkdir(parents=True)
    (tokens / f"{DEAL_CHAIN_ID}.json").write_text(
        json.dumps(
            {
                DEAL_TOKEN: {
                    "symbol": "USDC",
                    "contract_address": DEAL_TOKEN,
                    "decimals": 6,
                    "chain_id": DEAL_CHAIN_ID,
                }
            }
        ),
        encoding="utf-8",
    )
    return anvil_alkahest(signer), CONFIGURED_CLAUSES


def anvil_alkahest(signer, *, section=None, chain_probe=None):
    """Alkahest settlement on the anvil chain, its section changed by
    ``section`` and its readiness reading ``chain_probe`` where one is given.
    The token metadata ``alkahest_publication`` caches must be in place."""
    return alkahest_composition(
        signer,
        wallet=SELLER_WALLET,
        chain_clients={"anvil": object()},
        section={"address_books": {"anvil": ALKAHEST_ADDRESS_BOOK}, **(section or {})},
        chains={"anvil": {"rpc_url": "http://anvil.test", "chain_id": DEAL_CHAIN_ID}},
        chain_probe=chain_probe,
    )


#: The release condition a listing on the anvil chain advertises by default.
RECIPIENT_CONDITION = {
    "chain_name": "anvil",
    "arbiter": get_recipient_arbiter("anvil", config_path=ALKAHEST_ADDRESS_BOOK).lower(),
    "demand_data": {"recipient": SELLER_WALLET.lower()},
}


async def test_an_alkahest_listing_advertises_the_recipient_arbiter_paying_the_seller(
    db, tmp_path, monkeypatch
):
    signer = create_signer("ed25519", b"\x21" * 32)
    composition, clauses = alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    storefront.terms = publication_payload_builder(
        _settling_runtime(db, signer, composition, clauses)
    )

    await storefront.run()

    body = storefront.registries.sent[0][3]
    assert [escrow["chain_name"] for escrow in body["accepted_escrows"]] == ["anvil"]
    assert body["demands"] == [RECIPIENT_CONDITION]


def _settling_runtime(db, signer, composition, clauses=CONFIGURED_CLAUSES, *, sites=()):
    """A runtime whose payload builder publishes ``clauses`` through
    ``composition``, configured with ``sites``, each bound to a peer and an
    authority URL its tests never call."""
    return BareMetalStorefrontRuntime(
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                service_peer=f"{site_id}-peer",
                authority_url=f"http://{site_id}.test",
            )
            for site_id in sites
        ),
        db=db,
        domain=get_market_domain_contract(),
        seller_principal=signer.identity,
        admin_principals=TrustedIdentitySet(identities=(signer.identity,)),
        storefront_url=STOREFRONT_URL,
        marketplace_signer=signer,
        seller_evm_address=SELLER_WALLET,
        settlement_composition=composition,
        publication_clauses=clauses,
        default_max_duration_seconds=3600,
    )


# -- candidates with no settlement option ----------------------------------

#: An oracle-gated section naming no oracle: Alkahest is unready for a
#: configuration blocker, whatever its chain answers.
NO_ORACLE = {"oracle_gated": True, "trusted_oracle_addresses": []}


def unprobed_chain() -> AlkahestChainProbe:
    """A probe of the anvil chain that has not yet run, so Alkahest reads as
    unready for reachability: its readiness is unknown."""

    def never_called(*_args: Any) -> Any:
        raise AssertionError("the probe is never stepped")

    return AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", chain_id=DEAL_CHAIN_ID)],
        json_rpc=never_called,
        required_addresses=lambda _chain: {},
    )


async def _published_alkahest_listing(db, tmp_path, monkeypatch):
    """A storefront that has published one Alkahest listing, and its signer."""
    signer = create_signer("ed25519", b"\x21" * 32)
    composition, _ = alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    storefront.terms = publication_payload_builder(_settling_runtime(db, signer, composition))
    await storefront.run()
    return storefront, signer, composition


def _stored_terms(db: SQLiteClient, listing_id: str) -> tuple[Any, ...]:
    """A listing's stored settlement terms, as its record holds them."""
    with sqlite3.connect(db.db_path) as conn:
        return conn.execute(
            "SELECT accepted_escrows, settlement_options, demands, max_duration_seconds "
            "FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()


def _no_option_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("site_id", "pool_id", "physical_resource_id",
                                       "reason", "mechanisms")}


async def test_a_listing_whose_only_mechanism_is_configured_away_closes_and_reopens(
    db, tmp_path, monkeypatch
):
    storefront, signer, ready = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]

    storefront.terms = publication_payload_builder(
        _settling_runtime(db, signer, anvil_alkahest(signer, section=NO_ORACLE))
    )
    unready = await storefront.run()
    closed = storefront.listing("site-a", "pool-1", "r1")
    sent_on_close = storefront.registries.operations()
    storefront.terms = publication_payload_builder(_settling_runtime(db, signer, ready))
    restored = await storefront.run()

    assert closes(unready) == {listing_id: "no_settlement_option"}
    assert closed == (listing_id, "closed", "reconciliation")
    assert sent_on_close == [("closed", listing_id)]
    (refusal,) = actions(unready, "refuse")
    assert _no_option_entry(refusal) == {
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "reason": "no_settlement_option",
        "mechanisms": ["alkahest.v1"],
    }
    assert actions(unready, "hold") == []
    assert [item["listing_id"] for item in actions(restored, "reopen")] == [listing_id]
    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)


async def test_a_listing_whose_only_mechanisms_chain_is_unprobed_is_held(
    db, tmp_path, monkeypatch
):
    storefront, signer, _ = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    published_terms = _stored_terms(db, listing_id)
    storefront.terms = publication_payload_builder(
        _settling_runtime(db, signer, anvil_alkahest(signer, chain_probe=unprobed_chain()))
    )

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert _stored_terms(db, listing_id) == published_terms
    assert json.loads(published_terms[0])
    assert storefront.registries.operations() == []
    assert closes(report) == {} and actions(report, "refuse") == []
    (hold,) = actions(report, "hold")
    assert _no_option_entry(hold) == {
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "reason": "settlement_mechanism_unknown",
        "mechanisms": ["alkahest.v1"],
    }


async def test_an_unknown_mechanism_with_no_open_listing_is_refused_not_held(
    db, tmp_path, monkeypatch
):
    """A candidate with no listing has nothing to hold, so an unknown mechanism
    is recorded as its refusal."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    storefront.terms = publication_payload_builder(
        _settling_runtime(db, signer, anvil_alkahest(signer, chain_probe=unprobed_chain()))
    )

    report = await storefront.run()

    assert storefront.listings() == {}
    assert actions(report, "hold") == []
    (refusal,) = actions(report, "refuse")
    assert (refusal["reason"], refusal["mechanisms"]) == (
        "settlement_mechanism_unknown",
        ["alkahest.v1"],
    )


async def test_a_listing_whose_mechanism_is_disabled_closes_as_vms_does(
    db, tmp_path, monkeypatch
):
    """A disabled section is a configuration blocker: its mechanism is ruled
    out, so the listing whose only clause names it closes."""
    storefront, signer, _ = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    disabled = alkahest_composition(
        signer,
        wallet=SELLER_WALLET,
        chain_clients={"anvil": object()},
        enabled=False,
    )
    storefront.terms = publication_payload_builder(_settling_runtime(db, signer, disabled))

    report = await storefront.run()

    assert closes(report) == {listing_id: "no_settlement_option"}
    (refusal,) = actions(report, "refuse")
    assert refusal["mechanisms"] == ["alkahest.v1"]


@pytest.mark.parametrize(
    "mechanism_input",
    [
        {
            "chain": "anvil",
            "escrow_kind": "erc20_escrow_obligation_default",
            "unknown": True,
        },
        {"chain": "anvil"},
    ],
    ids=["unknown-field", "incomplete"],
)
async def test_an_override_clause_that_cannot_be_read_never_closes_its_listing(
    db, tmp_path, monkeypatch, mechanism_input
):
    """A stored override's clause naming Alkahest, whose section is disabled,
    with input Alkahest cannot read, is a defect: the candidate is refused as
    `payload_unbuildable` under its site, and its open listing keeps its
    identity and terms, publishing nothing, where a readable clause naming the
    disabled mechanism would close it."""
    storefront, signer, _ = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    published_terms = _stored_terms(db, listing_id)
    await _override(
        db,
        settlements=[{**CONFIGURED_CLAUSES_RAW[0], "mechanism_input": mechanism_input}],
    )
    disabled = alkahest_composition(
        signer,
        wallet=SELLER_WALLET,
        chain_clients={"anvil": object()},
        enabled=False,
    )
    storefront.terms = publication_payload_builder(_settling_runtime(db, signer, disabled))

    report = await storefront.run()

    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert _stored_terms(db, listing_id) == published_terms
    assert storefront.registries.operations() == []
    assert closes(report) == {} and actions(report, "hold") == []
    (refusal,) = actions(report, "refuse")
    assert {key: refusal[key] for key in ("site_id", "pool_id", "physical_resource_id", "reason")} == {
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "reason": "payload_unbuildable",
    }
    assert "invalid publication input for 'alkahest.v1'" in refusal["error"]
    assert [item["reason"] for item in storefront.refusals()] == ["payload_unbuildable"]

    # The same override, its clause readable, is the configuration ruling
    # Alkahest out: the listing closes.
    await _override(db, settlements=list(CONFIGURED_CLAUSES_RAW))
    readable = await storefront.run()

    assert closes(readable) == {listing_id: "no_settlement_option"}


async def test_a_mechanism_ruled_out_and_unreachable_at_once_closes_its_listing(
    db, tmp_path, monkeypatch
):
    """A configuration blocker rules a mechanism out whatever its chain answers."""
    storefront, signer, _ = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    storefront.terms = publication_payload_builder(
        _settling_runtime(
            db,
            signer,
            anvil_alkahest(signer, section=NO_ORACLE, chain_probe=unprobed_chain()),
        )
    )

    report = await storefront.run()

    assert closes(report) == {listing_id: "no_settlement_option"}
    assert storefront.listing("site-a", "pool-1", "r1")[1:] == ("closed", "reconciliation")


async def test_a_preview_reports_the_close_and_applies_none(db, tmp_path, monkeypatch):
    storefront, signer, _ = await _published_alkahest_listing(db, tmp_path, monkeypatch)
    listing_id = storefront.listing("site-a", "pool-1", "r1")[0]
    storefront.terms = publication_payload_builder(
        _settling_runtime(db, signer, anvil_alkahest(signer, section=NO_ORACLE))
    )

    report = await storefront.run(dry_run=True)

    assert closes(report) == {listing_id: "no_settlement_option"}
    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert storefront.registries.operations() == []


#: Contact exchange configured only for another origin, so a candidate from
#: ``site-a`` builds no contact option. The address is on the reserved
#: ``.invalid`` domain, a development value never for a public network.
CONTACT_ELSEWHERE = {
    "enabled": True,
    "origins": {"site-b": {"contact_payload": {"email": "sales@seller.invalid"}}},
    "profiles": {"default": {"channel": "email", "terms": "Introduction."}},
}
CONTACT_CLAUSE = {
    "mechanism": "contact-exchange.v1",
    "asset": "introduction",
    "mechanism_input": {"profile": "default"},
}


def _alkahest_and_contact(signer, *, chain_probe=None, contact=CONTACT_ELSEWHERE):
    """Alkahest on the anvil chain beside contact exchange configured by
    ``contact``, by default only for ``site-b``; Alkahest's readiness reads
    ``chain_probe`` where one is given."""
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "schema_version": 1,
            "priority": ["alkahest.v1", "contact-exchange.v1"],
            "alkahest": {
                **ALKAHEST_SECTION,
                "address_books": {"anvil": ALKAHEST_ADDRESS_BOOK},
            },
            "contact": contact,
        },
        resources={
            "marketplace_signer": signer,
            "claimant_principal": signer.identity,
            "wallet": SELLER_WALLET,
            "clients": {"anvil": object()},
            "chains": {"anvil": {"rpc_url": "http://anvil.test", "chain_id": DEAL_CHAIN_ID}},
            **({"chain_probe": chain_probe} if chain_probe is not None else {}),
        },
    )


def _unbacked_candidate(**changes: Any) -> dict[str, Any]:
    return {
        "site_id": "site-a",
        "pool_id": "pool-u",
        "physical_resource_id": "r1",
        "listing_resource": {"capacity_backing": "unbacked"},
        **changes,
    }


async def test_the_builder_rules_out_an_unbacked_candidate_whatever_an_inadmissible_mechanism_answers(
    db, tmp_path, monkeypatch
):
    """The payload builder alone: an unbacked candidate may publish only
    contact exchange, which its origin's configuration rules out, so it is
    refused for configuration while Alkahest, which unbacked bare metal cannot
    publish, is unknown. This shows the refusal's classification, not a
    cycle closing a listing."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    build = publication_payload_builder(
        _settling_runtime(
            db,
            signer,
            _alkahest_and_contact(signer, chain_probe=unprobed_chain()),
            compile_publication_clauses([*CONFIGURED_CLAUSES_RAW, CONTACT_CLAUSE]),
            sites=("site-a", "site-b"),
        )
    )

    with pytest.raises(NoSettlementOption) as refused:
        await build(_unbacked_candidate())

    assert refused.value.mechanisms == ("contact-exchange.v1",)
    assert refused.value.ruled_out_by_configuration is True


CONTACT_ONLY = compile_publication_clauses([CONTACT_CLAUSE])
ALKAHEST_AND_CONTACT = compile_publication_clauses([*CONFIGURED_CLAUSES_RAW, CONTACT_CLAUSE])


def _contact_terms(db, signer, clauses, *, chain_probe=None):
    """The payload builder publishing ``clauses`` through Alkahest beside a
    contact exchange that names a contact for ``site-b`` only."""
    return publication_payload_builder(
        _settling_runtime(
            db,
            signer,
            _alkahest_and_contact(signer, chain_probe=chain_probe),
            clauses,
            sites=("site-a", "site-b"),
        )
    )


def _contact_storefront(db, signer, clauses):
    """A storefront over one backed pool on ``site-a`` publishing ``clauses``."""
    storefront = Storefront(db, {"site-a": Site(pool("pool-1", member("r1", "pool-1")))})
    storefront.terms = _contact_terms(db, signer, clauses)
    return storefront


async def test_a_contact_only_candidate_whose_origin_has_no_contact_yields_no_listing(
    db, tmp_path, monkeypatch, caplog
):
    """Spec scenario "An unbacked candidate's origin has no contact", on a
    backed candidate, since one whose only clause is contact exchange is
    refused the same way whatever its backing; and the refusal, standing for
    two cycles, is logged once, when the site derivation's log records it
    appearing, and not warned as a failed candidate in either cycle."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = _contact_storefront(db, signer, CONTACT_ONLY)

    with caplog.at_level(logging.WARNING):
        first = await storefront.run()
        second = await storefront.run()

    assert storefront.listings() == {}
    assert storefront.registries.operations() == []
    for report in (first, second):
        (refusal,) = actions(report, "refuse")
        assert _no_option_entry(refusal) == {
            "site_id": "site-a",
            "pool_id": "pool-1",
            "physical_resource_id": "r1",
            "reason": "no_settlement_option",
            "mechanisms": ["contact-exchange.v1"],
        }
    assert not [
        record for record in caplog.records if "bare-metal candidate" in record.getMessage()
    ]
    logged = [
        record
        for record in caplog.records
        if "refusals" in record.getMessage() and "no_settlement_option" in record.getMessage()
    ]
    assert len(logged) == 1
    assert [item["reason"] for item in storefront.refusals()] == ["no_settlement_option"]


async def test_an_unreached_mechanism_beside_one_ruled_out_holds_the_listing(
    db, tmp_path, monkeypatch
):
    """Spec scenario "An unreachable mechanism beside one ruled out by
    configuration": a listing published with only its Alkahest option, beside
    contact exchange that gives its origin no contact, is held once Alkahest's
    chain is unreached, because the offer it published is one the storefront
    would make again."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = _contact_storefront(db, signer, ALKAHEST_AND_CONTACT)
    await storefront.run()
    listing_id, status, _ = storefront.listing("site-a", "pool-1", "r1")
    published = storefront.registries.sent[0][3]

    storefront.terms = _contact_terms(
        db, signer, ALKAHEST_AND_CONTACT, chain_probe=unprobed_chain()
    )
    report = await storefront.run()

    assert status == "open"
    assert published["accepted_escrows"]
    assert "contact-exchange.v1" not in {
        option["mechanism"] for option in published["settlement_options"]
    }
    assert storefront.listing("site-a", "pool-1", "r1") == (listing_id, "open", None)
    assert closes(report) == {} and storefront.registries.operations() == []
    (hold,) = actions(report, "hold")
    assert (hold["reason"], hold["mechanisms"]) == (
        "settlement_mechanism_unknown",
        ["alkahest.v1"],
    )


async def test_an_override_naming_only_a_capacity_mechanism_leaves_no_admissible_clause(
    db, tmp_path, monkeypatch
):
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    build = publication_payload_builder(
        _settling_runtime(
            db,
            signer,
            _alkahest_and_contact(signer, chain_probe=unprobed_chain()),
            compile_publication_clauses([CONTACT_CLAUSE]),
            sites=("site-a", "site-b"),
        )
    )

    with pytest.raises(NoSettlementOption, match="no settlement option") as refused:
        await build(_unbacked_candidate(override_clauses=list(CONFIGURED_CLAUSES_RAW)))

    assert refused.value.mechanisms == ()
    assert refused.value.ruled_out_by_configuration is True


# -- unbacked candidates with no settlement option, through the cycle -----------

#: Contact exchange giving ``site-a`` its contact. The address is a reserved
#: example domain, never a real mailbox.
CONTACT_HERE = {
    "enabled": True,
    "origins": {"site-a": {"contact_payload": {"email": "sales@seller.invalid"}}},
    "profiles": {"default": {"channel": "email", "terms": "Introduction."}},
}


def _unbacked_storefront(db, signer, *, contact):
    """A storefront over one unbacked pool on ``site-a``, publishing Alkahest
    and contact-exchange clauses by default, Alkahest's chain never probed and
    contact exchange configured by ``contact``."""
    storefront = Storefront(db, {"site-a": Site(unbacked_pool(unbacked_member("r1")))})
    storefront.terms = _unbacked_terms(db, signer, contact=contact)
    return storefront


def _unbacked_terms(db, signer, *, contact):
    return publication_payload_builder(
        _settling_runtime(
            db,
            signer,
            _alkahest_and_contact(signer, chain_probe=unprobed_chain(), contact=contact),
            ALKAHEST_AND_CONTACT,
            sites=("site-a", "site-b"),
        )
    )


async def _override_unbacked_pool(db: SQLiteClient, settlements: list[dict[str, Any]]):
    """Store the unbacked pool's override through the real store, returning the
    record as stored."""
    return await SQLitePoolOverrideStore(db.db_path).replace(
        PoolOverrideRecord(
            site_id="site-a",
            pool_id="pool-u",
            offering_mode="bare_metal",
            settlements=settlements,
        )
    )


def _mechanisms(body: dict[str, Any]) -> list[str]:
    return [option["mechanism"] for option in body.get("settlement_options") or []]


async def test_an_override_leaving_no_admissible_clause_closes_the_unbacked_listing(
    db, tmp_path, monkeypatch
):
    """Spec scenario "A pool override leaves no admissible clause", through the
    stored override, the payload builder, and the cycle. Alkahest's chain is
    never probed, so its readiness stays unknown throughout: a mechanism the
    unbacked candidate cannot publish holds nothing."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = _unbacked_storefront(db, signer, contact=CONTACT_HERE)

    await storefront.run()
    listing_id, status, _ = storefront.listing("site-a", "pool-u", "r1")
    published = storefront.registries.sent[0][3]

    assert status == "open"
    assert published["listing_resource"]["capacity_backing"] == "unbacked"
    assert _mechanisms(published) == ["contact-exchange.v1"]
    assert not published.get("accepted_escrows")

    stored = await _override_unbacked_pool(db, list(CONFIGURED_CLAUSES_RAW))
    assert [clause["mechanism"] for clause in stored["settlements"]] == ["alkahest.v1"]
    closing = await storefront.run()

    assert storefront.listing("site-a", "pool-u", "r1") == (
        listing_id,
        "closed",
        "reconciliation",
    )
    assert closes(closing) == {listing_id: "no_settlement_option"}
    assert storefront.registries.operations() == [("closed", listing_id)]
    assert actions(closing, "publish") == [] and actions(closing, "hold") == []
    (refusal,) = actions(closing, "refuse")
    assert _no_option_entry(refusal) == {
        "site_id": "site-a",
        "pool_id": "pool-u",
        "physical_resource_id": "r1",
        "reason": "no_settlement_option",
        "mechanisms": [],
    }
    assert [item["reason"] for item in storefront.refusals()] == ["no_settlement_option"]

    await _override_unbacked_pool(db, [CONTACT_CLAUSE])
    reopening = await storefront.run()

    assert [item["listing_id"] for item in actions(reopening, "reopen")] == [listing_id]
    assert storefront.listing("site-a", "pool-u", "r1") == (listing_id, "open", None)
    assert actions(reopening, "refuse") == []
    assert storefront.refusals() == []


async def test_an_unbacked_candidate_whose_origin_has_no_contact_yields_no_listing(
    db, tmp_path, monkeypatch
):
    """Spec scenario "An unbacked candidate's origin has no contact": contact
    exchange, its only admissible mechanism, names a contact for another site
    alone, while Alkahest, which it cannot publish, is unknown."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = _unbacked_storefront(db, signer, contact=CONTACT_ELSEWHERE)

    report = await storefront.run()

    assert storefront.listings() == {}
    assert storefront.registries.operations() == []
    assert actions(report, "hold") == []
    (refusal,) = actions(report, "refuse")
    assert _no_option_entry(refusal) == {
        "site_id": "site-a",
        "pool_id": "pool-u",
        "physical_resource_id": "r1",
        "reason": "no_settlement_option",
        "mechanisms": ["contact-exchange.v1"],
    }
    assert [item["reason"] for item in storefront.refusals()] == ["no_settlement_option"]


async def test_an_unbacked_listing_whose_origin_loses_its_contact_closes(
    db, tmp_path, monkeypatch
):
    """Spec scenario "An unreachable mechanism the candidate could never
    publish": the open unbacked contact listing closes once its origin has no
    contact, although Alkahest's chain is unreached, since unbacked bare metal
    could never publish Alkahest."""
    signer = create_signer("ed25519", b"\x21" * 32)
    alkahest_publication(tmp_path, monkeypatch, signer)
    storefront = _unbacked_storefront(db, signer, contact=CONTACT_HERE)
    await storefront.run()
    listing_id, status, _ = storefront.listing("site-a", "pool-u", "r1")

    storefront.terms = _unbacked_terms(db, signer, contact=CONTACT_ELSEWHERE)
    report = await storefront.run()

    assert status == "open"
    assert closes(report) == {listing_id: "no_settlement_option"}
    assert storefront.listing("site-a", "pool-u", "r1") == (
        listing_id,
        "closed",
        "reconciliation",
    )
    assert storefront.registries.operations() == [("closed", listing_id)]
    assert actions(report, "hold") == [] and actions(report, "publish") == []
    (refusal,) = actions(report, "refuse")
    assert _no_option_entry(refusal) == {
        "site_id": "site-a",
        "pool_id": "pool-u",
        "physical_resource_id": "r1",
        "reason": "no_settlement_option",
        "mechanisms": ["contact-exchange.v1"],
    }
