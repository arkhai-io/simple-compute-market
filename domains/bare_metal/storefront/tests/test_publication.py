from __future__ import annotations
from types import SimpleNamespace
import json

import httpx
import pytest
from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)
from market_identity import Ed25519Signer
from registry_client import ListingRequest
from registry_client.client import SyncRegistryClient
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


def test_registry_republication_replaces_the_complete_listing_payload():
    published = []

    class Client:
        def publish_listing(self, request):
            published.append(request)
            return {"listing_id": request.listing_id, "status": "open"}

    result = publication_cli._publish_registry_listing(
        Client(),
        listing_id="listing-1",
        offer={"kind": "bare_metal.v1"},
        accepted_escrows=[],
        settlement_options=[{"option_id": "hosted-1"}],
        demands=[],
        max_duration_seconds=3600,
        storefront_url="https://storefront.example",
    )

    assert result == {"status": "published", "listing_id": "listing-1"}
    assert published[0].settlement_options == [{"option_id": "hosted-1"}]


class _CapturedRequest(Exception):
    """Stops the exchange once the outgoing request has been observed.

    The registry client verifies the signed response before returning, which a
    transport stub cannot produce; raising here keeps the assertion on the real
    request the client put on the wire.
    """

    def __init__(self, request: httpx.Request) -> None:
        super().__init__("captured")
        self.request = request


def _publish_through_real_client(monkeypatch) -> httpx.Request:
    """Run one publish through the client ``_registry`` actually builds.

    Only the transport is substituted, so the bearer credential, the signature
    headers, and the request body are the ones production would send.
    """

    # Deterministic development-only signing key. It is a fixture value and
    # must never be used on a public network.
    signer = Ed25519Signer(bytes.fromhex("22" * 32))
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        raise _CapturedRequest(request)

    class _SeamBoundClient(SyncRegistryClient):
        def __init__(self, base_url, **kwargs):
            super().__init__(
                base_url, transport=httpx.MockTransport(handler), **kwargs
            )

    monkeypatch.setattr(publication_cli, "SyncRegistryClient", _SeamBoundClient)
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS",
        json.dumps(
            [
                {
                    "scheme": signer.identity.scheme.value,
                    "identifier": signer.identity.identifier,
                }
            ]
        ),
    )
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_REGISTRY_URL", "https://registry.example"
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY", "registry-dev")

    client = publication_cli._registry(SimpleNamespace(marketplace_signer=signer))
    with pytest.raises(_CapturedRequest):
        client.publish_listing(
            ListingRequest(
                listing_id="listing-1",
                offer={"kind": "bare_metal.v1"},
                accepted_escrows=[],
                settlement_options=[],
                demands=[],
                max_duration_seconds=3600,
                storefront_url="https://storefront.example",
            )
        )
    client.close()
    return captured[0]


def test_publication_sends_the_configured_registry_write_credential(monkeypatch):
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_REGISTRY_API_KEY", "write-scoped-dev-key"
    )

    request = _publish_through_real_client(monkeypatch)

    assert request.headers["Authorization"] == "Bearer write-scoped-dev-key"
    # The credential authenticates the caller; it never replaces the per-request
    # seller signature the registry verifies on top of it.
    assert request.headers["X-Market-Identity-Scheme"] == "ed25519"


def test_publication_without_a_configured_credential_sends_no_bearer(monkeypatch):
    monkeypatch.delenv("BARE_METAL_STOREFRONT_REGISTRY_API_KEY", raising=False)

    request = _publish_through_real_client(monkeypatch)

    assert "authorization" not in request.headers


def test_empty_registry_credential_is_not_sent_as_an_empty_bearer(monkeypatch):
    # An unset Secret key renders as an empty string. Sending `Bearer ` would
    # reach the registry as a malformed credential rather than as the absent
    # one an open-publishing registry expects.
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_API_KEY", "")

    request = _publish_through_real_client(monkeypatch)

    assert "authorization" not in request.headers


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
