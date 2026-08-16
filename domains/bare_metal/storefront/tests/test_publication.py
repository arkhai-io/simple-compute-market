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
                machine_id="machine-1",
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
                        "vm_host": "private-executor-alias",
                        "bare_metal_publication": {
                            "enabled": True,
                            "physical_host_id": "physical-host-1",
                            "machine_id": "machine-1",
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
    assert resource.machine_id == "machine-1"
    assert resource.capabilities == {"gpu_model": "H200"}
    assert resource.available is False


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
        "BARE_METAL_STOREFRONT_OFFER_EXPIRES_AT": "2026-08-17T04:00:00Z",
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
