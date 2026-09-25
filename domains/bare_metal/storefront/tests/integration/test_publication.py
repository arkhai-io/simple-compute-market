"""The bare-metal publication cycle over a real storefront database.

Integration in the sense ``docs/development/TESTING.md`` gives it for code with
no application of its own: the cycle's public API against a real embedded
database, with the collaborators it does not own injected. Each site answers
with a resource-pool projection built from the site-client contract fixture,
its bare-metal views from this domain's view fixture, and the registry client
records what each registry is sent.

The site authority and the registry are this repository's own services, so
these doubles prove the cycle's orchestration and persistence, not either
service's contract: the fixtures' producer tests and the command's composition
test cover that.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from arkhai_bare_metal.fixtures.publication_view import (
    build_bare_metal_publication_view,
)
from core_storefront.publication_runner import PublicationPayload
from market_capacity_publication import BoundListing, CapacityBinding
from market_identity import create_signer
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_projection,
    build_resource_pool_row,
)

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.publication_service import build_publication_runtime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

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
) -> dict[str, Any]:
    """A projected pool member carrying its bare-metal view.

    The site's view folds enablement into ``available``, as the provisioning
    service builds it.
    """
    return build_projected_resource(
        resource_id,
        enabled=enabled,
        publication_views={
            "bare_metal.v2": build_bare_metal_publication_view(
                resource_id,
                pool_id=pool_id if view_pool_id == "" else view_pool_id,
                host_id=host_id or f"machine-{resource_id}",
                physical_host_id=f"physical-{resource_id}",
                available=enabled and available,
            )
        },
    )


def pool(pool_id: str, *members: dict[str, Any], **declarations: Any) -> dict[str, Any]:
    declarations.setdefault("advertisable_modes", ("bare_metal",))
    return build_resource_pool_row(pool_id, resources=members, **declarations)


def unresolvable(pool_id: str, *members: dict[str, Any]) -> dict[str, Any]:
    return pool(pool_id, *members, policy_tags={"capacity_backing": "sometimes"})


class Site:
    """A site authority's typed client, answering its resource-pool projection."""

    def __init__(self, *pools: dict[str, Any]) -> None:
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

    async def resource_pool_projection(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


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
    def __init__(self, db: SQLiteClient, sites: dict[str, Site]) -> None:
        self.db = db
        self.sites = sites
        self.registries = RecordingRegistries()
        self.terms = Terms()

    async def run(self) -> dict[str, Any]:
        self.registries.sent.clear()
        cycle = BareMetalPublicationCycle(
            sqlite_client=self.db,
            registry=build_bare_metal_storefront_registry(
                domain=get_market_domain_contract()
            ),
            site_clients=self.sites,
            registry_client_factory=self.registries,
            registry_url=REGISTRY_URL,
            storefront_url=STOREFRONT_URL,
            seller_principal=SELLER,
            build_payload=self.terms,
        )
        return await cycle.run()

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


async def test_an_unbacked_pool_yields_no_listing_and_is_reported(db):
    storefront = Storefront(
        db,
        {
            "site-a": Site(
                pool("pool-u", member("r1", "pool-u"), capacity_backing="unbacked")
            )
        },
    )

    report = await storefront.run()

    assert storefront.listings() == {}
    assert storefront.registries.operations() == []
    assert actions(report, "refuse") == [
        {"action": "refuse", "site_id": "site-a", "pool_id": "pool-u", "reason": "pool_unbacked"}
    ]


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


@pytest.mark.parametrize("unknown", ["unreachable", "view-names-another-pool"])
async def test_an_unknown_site_keeps_its_listings_while_another_reconciles(db, unknown):
    site_a = Site(pool("pool-1", member("a1", "pool-1")))
    site_b = Site(pool("pool-1", member("b1", "pool-1")))
    storefront = Storefront(db, {"site-a": site_a, "site-b": site_b})
    await storefront.run()
    a_id = storefront.listing("site-a", "pool-1", "a1")[0]
    b_id = storefront.listing("site-b", "pool-1", "b1")[0]

    if unknown == "unreachable":
        site_a.fail()
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
        registry_url=REGISTRY_URL,
        storefront_url=STOREFRONT_URL,
    )
    await seller_close.close(
        BoundListing(listing_id, CapacityBinding("site-a", "bare_metal", "r1")),
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
    assert {"action": "refuse", "listing_id": listing_id, "reason": "identity_changed", "fields": ["host_id"]} in report["actions"]
