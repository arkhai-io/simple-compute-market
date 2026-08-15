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
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.server import BARE_METAL_STOREFRONT_REGISTRY



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
                "virtualization_type": "bare_metal",
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
