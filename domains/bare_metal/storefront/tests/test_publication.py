from __future__ import annotations

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


def _projection():
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        complete=True,
        resources=[
            BareMetalResourceProjection(
                physical_resource_id="resource-1",
                physical_host_id="physical-host-1",
                machine_id="machine-1",
                available=True,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
                capabilities={"gpu_model": "H200"},
            ),
        ],
    )


def test_selection_builds_only_bare_metal_source():
    selection = build_bare_metal_publication_selection(
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: kwargs,
    )

    sources = selection.build_sources()

    assert tuple(selection.source_names) == ("bare_metal",)
    assert [source.name for source in sources] == ["bare_metal"]


def test_core_runner_publishes_exact_opaque_bare_metal_payload(tmp_path):
    path = str(tmp_path / "storefront.db")
    SQLiteClient(path)
    selection = build_bare_metal_publication_selection(
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: kwargs,
    )
    offers = []

    result = run_bare_metal_publication(
        selection,
        config=StorefrontPublicationCommandConfig(
            db_path=path,
            base_url="https://seller.example",
            private_key=None,
            close_stale=False,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=lambda _source, _candidate, _offer: (
                [{"chain_name": "base"}],
                [],
                7200,
            ),
            publish_offer=lambda offer, accepted, demands, maximum: (
                offers.append((offer, accepted, demands, maximum))
                or {"listing_id": "listing-1", "status": "published"}
            ),
        ),
    )

    assert result.published_count == 1
    assert result.failed == []
    assert offers == [
        (
            {
                "kind": "bare_metal.v1",
                "machine_id": "machine-1",
                "physical_host_id": "physical-host-1",
                "access_methods": ["ssh"],
                "capabilities": {"gpu_count": 8, "gpu_model": "H200"},
            },
            [{"chain_name": "base"}],
            [],
            7200,
        ),
    ]
