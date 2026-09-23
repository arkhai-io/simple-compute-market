from __future__ import annotations
from types import SimpleNamespace
import json

from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
)

from arkhai_bare_metal_storefront.publication import (
    build_bare_metal_publication_selection,
    run_bare_metal_publication,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.server import BARE_METAL_STOREFRONT_REGISTRY
from arkhai_bare_metal_storefront import publication_cli


def _projection():
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        complete=True,
        resources=[
            BareMetalResourceProjection(
                physical_resource_id="resource-1",
                pool_id="pool-1",
                physical_host_id="physical-host-1",
                host_id="machine-1",
                available=True,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
                capabilities={"gpu_model": "H200"},
            ),
        ],
    )


def test_projections_use_allowlisted_bare_metal_publication_metadata():
    class CapacityClient:
        async def snapshot(self):
            return [
                {
                    "site": "site-a",
                    "resource_id": "resource-1",
                    "pool_id": "pool-1",
                    "capacity": {"gpu_count": 1, "units": 1},
                    "available": {"gpu_count": 1, "units": 0},
                    "enabled": True,
                    "attributes": {
                        "host_id": "private-executor-alias",
                        "bare_metal_publication": {
                            "enabled": True,
                            "physical_host_id": "physical-host-1",
                            "host_id": "machine-1",
                            "allocation_mode": "exclusive",
                            "access_methods": ["ssh"],
                            "capabilities": {"gpu_model": "H200"},
                        },
                    },
                },
            ]

    projections = publication_cli._projections(
        SimpleNamespace(
            capacity_client=CapacityClient(),
            site_bindings=(SimpleNamespace(site_id="site-a"),),
        )
    )

    resource = projections[0].resources[0]
    assert resource.pool_id == "pool-1"
    assert resource.physical_resource_id == "resource-1"
    assert resource.physical_host_id == "physical-host-1"
    assert resource.host_id == "machine-1"
    assert resource.capabilities == {"gpu_model": "H200"}
    assert resource.available is False


def test_registry_republication_replaces_the_complete_listing_payload():
    published = []

    class Client:
        def publish_listing(self, request):
            published.append(request)
            return {"listing_id": request.listing_id, "status": "open"}

    result = publication_cli._publish_registry_listing(
        Client(),
        listing_id="listing-1",
        listing_resource={"kind": "bare_metal.v2"},
        accepted_escrows=[],
        settlement_options=[{"option_id": "hosted-1"}],
        demands=[],
        max_duration_seconds=3600,
        storefront_url="https://storefront.example",
    )

    assert result == {"status": "published", "listing_id": "listing-1"}
    assert published[0].settlement_options == [{"option_id": "hosted-1"}]


def _selection():
    return build_bare_metal_publication_selection(
        BARE_METAL_STOREFRONT_REGISTRY,
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: kwargs,
    )


def test_selection_builds_only_bare_metal_source():
    registration = BARE_METAL_STOREFRONT_REGISTRY.resolve_mode("bare_metal")
    selection = _selection()

    sources = selection.build_sources()

    assert registration.contract is get_market_domain_contract()
    assert tuple(selection.source_names) == (registration.contribution_id,)
    assert [source.name for source in sources] == [registration.contribution_id]


def test_core_runner_publishes_exact_opaque_bare_metal_payload(tmp_path):
    path = str(tmp_path / "storefront.db")
    SQLiteClient(path)
    selection = _selection()
    offers = []

    result = run_bare_metal_publication(
        selection,
        config=StorefrontPublicationCommandConfig(
            db_path=path,
            base_url="https://seller.example",
            close_stale=False,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=lambda _source, _candidate, _offer: (
                [{"chain_name": "base"}],
                [],
                7200,
            ),
            publish_listing=lambda listing_resource, accepted, demands, maximum: (
                offers.append((listing_resource, accepted, demands, maximum))
                or {"listing_id": "listing-1", "status": "published"}
            ),
        ),
    )

    assert result.published_count == 1
    assert result.failed == []
    assert offers == [
        (
            {
                "capacity_backing": "backed",
                "kind": "bare_metal.v2",
                "offering_mode": "bare_metal",
                "host_id": "machine-1",
                "physical_host_id": "physical-host-1",
                "access_methods": ["ssh"],
                "capabilities": {"gpu_count": 8, "gpu_model": "H200"},
            },
            [{"chain_name": "base"}],
            [],
            7200,
        ),
    ]


def test_one_shot_publication_builds_registry_from_runtime_domain(monkeypatch):
    domain = object()
    runtime = SimpleNamespace(
        settlement_composition=object(),
        domain=domain,
        db=SimpleNamespace(db_path="storefront.db"),
        storefront_url="http://storefront.example",
    )
    registry = object()
    selection = object()
    closed = []
    captured = {}
    summary_resource = _projection().resources[0]

    monkeypatch.setattr(
        publication_cli, "build_runtime_from_environment", lambda: runtime
    )
    monkeypatch.setattr(
        publication_cli,
        "_registry",
        lambda _runtime: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(publication_cli, "_projections", lambda _runtime: ())

    def build_registry(*, domain):
        captured["domain"] = domain
        return registry

    monkeypatch.setattr(
        publication_cli, "build_bare_metal_storefront_registry", build_registry
    )
    monkeypatch.setattr(
        publication_cli,
        "build_bare_metal_publication_selection",
        lambda value, **_kwargs: selection if value is registry else None,
    )
    monkeypatch.setattr(
        publication_cli,
        "run_bare_metal_publication",
        lambda value, **_kwargs: (
            SimpleNamespace(
                closed=[],
                published=[{"resource": summary_resource}],
                failed=[],
                skipped=[],
            )
            if value is selection
            else None
        ),
    )
    for name, value in {
        "BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES": "[]",
        "BARE_METAL_STOREFRONT_FUNDING_DEADLINES": "{}",
        "BARE_METAL_STOREFRONT_DEMANDS": "[]",
        "BARE_METAL_STOREFRONT_OPTION_EXPIRES_AT": "2026-08-17T04:00:00Z",
        "BARE_METAL_STOREFRONT_FULFILLMENT_DEADLINE": "2026-08-17T03:30:00Z",
        "BARE_METAL_STOREFRONT_MAX_DURATION_SECONDS": "3600",
    }.items():
        monkeypatch.setenv(name, value)

    output = publication_cli.run_publication_once()
    assert output == {
        "closed": [],
        "published": [{"resource": summary_resource.model_dump(mode="json")}],
        "failed": [],
        "skipped": [],
    }
    json.dumps(output)
    assert captured == {"domain": domain}
    assert closed == [True]


# ---------------------------------------------------------------------------
# A tracked listing is reconciled against a fresh candidate: terms refresh in
# place, and a changed identity closes the listing and refuses reopen.
# ---------------------------------------------------------------------------


def _tracked_listing(tmp_path, *, max_duration_seconds=7200):
    import asyncio

    from arkhai_bare_metal.storefront_publication import (
        bare_metal_listing_candidates,
        record_derived_bare_metal_listing,
    )
    from market_identity import create_signer

    path = str(tmp_path / "storefront.db")
    db = SQLiteClient(path)
    (candidate,) = bare_metal_listing_candidates([_projection()])
    listing = dict(candidate["listing_resource"])
    listing.pop("offering_mode", None)
    listing["max_duration_seconds"] = max_duration_seconds
    asyncio.run(
        db.upsert_bare_metal_listing(
            listing_id="listing-1",
            status="open",
            created_at="2026-09-23T00:00:00Z",
            updated_at="2026-09-23T00:00:00Z",
            # A development signer; never used on any public network.
            seller_principal=create_signer("ed25519", b"\x21" * 32).identity,
            storefront_url="https://seller.example",
            listing=listing,
            accepted_escrows=[],
            settlement_options=[],
            demands=[],
            site_id="site-a",
            pool_id="pool-1",
            physical_resource_id="resource-1",
        )
    )
    record_derived_bare_metal_listing(path, listing_id="listing-1", candidate=candidate)
    return path, candidate


def _reconcile(path, candidate, listing_resource, *, max_duration_seconds=7200):
    from arkhai_bare_metal.storefront_publication import (
        reopen_derived_bare_metal_listing_if_present,
    )

    published, closed = [], []
    result = reopen_derived_bare_metal_listing_if_present(
        db_path=path,
        base_url="https://seller.example",
        candidate=candidate,
        listing_resource=listing_resource,
        accepted_escrows=[],
        demands=[],
        max_duration_seconds=max_duration_seconds,
        publish_existing_listing=lambda **values: published.append(values)
        or {"status": "published"},
        close_listing=lambda base_url, listing_id: closed.append(listing_id)
        or {"status": "closed"},
        settlement_options=[],
        publication_clauses=[],
    )
    return result, published, closed


def _stored_resource(path):
    import sqlite3

    with sqlite3.connect(path) as conn:
        (raw,) = conn.execute(
            "SELECT listing_resource FROM listings WHERE listing_id='listing-1'"
        ).fetchone()
    return json.loads(raw)


def test_an_unchanged_tracked_listing_is_left_alone(tmp_path):
    path, candidate = _tracked_listing(tmp_path)

    result, published, closed = _reconcile(path, candidate, _stored_resource(path))

    assert result["status"] == "unchanged"
    assert (published, closed) == ([], [])


def test_a_changed_term_refreshes_the_listing_in_place(tmp_path):
    path, candidate = _tracked_listing(tmp_path)

    result, published, closed = _reconcile(
        path, candidate, _stored_resource(path), max_duration_seconds=3600
    )

    assert result == {"status": "published"}
    assert published[0]["listing_id"] == "listing-1"
    assert published[0]["max_duration_seconds"] == 3600
    assert closed == []


def test_a_changed_identity_closes_and_refuses_reopen(tmp_path):
    path, candidate = _tracked_listing(tmp_path)
    diverged = {**_stored_resource(path), "host_id": "machine-2"}

    result, published, closed = _reconcile(path, candidate, diverged)

    assert result["status"] == "unchanged"
    assert closed == ["listing-1"]
    assert published == []
    again, published, closed = _reconcile(path, candidate, diverged)
    assert again["status"] == "unchanged"
    assert (published, closed) == ([], [])
