from __future__ import annotations

from types import SimpleNamespace

import pytest

import market_storefront.container as container
import market_storefront.server as server
import market_storefront.services.capacity_client as capacity_client_module
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)


def _registry(domain):
    registry = build_vm_storefront_registry(domain)
    assert registry.resolve_mode("vm").contract is domain
    return registry


def test_server_uses_shared_storefront_app_shell() -> None:
    app = server.app

    assert app.title == "Arkhai Storefront"
    assert app.version == "1.0.0"
    assert app.swagger_ui_parameters == {"persistAuthorization": True}
    assert app.openapi.__name__ == "_custom_openapi"
    assert app.state.market_domains[0].domain_identity == "compute.v1"
    assert app.state.storefront_binding == server.storefront_domain_registry().resolve_mode(
        "vm"
    ).binding

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/system/status" in paths
    assert "/api/v1/listings/create" in paths
    assert "/api/v1/settle/{escrow_uid}" in paths


def test_app_factory_retains_each_distinct_compatible_contract() -> None:
    first = build_vm_storefront_domain()
    second = build_vm_storefront_domain()

    first_registry = _registry(first)
    second_registry = _registry(second)
    first_app = server.build_vm_storefront_app(registry=first_registry)
    second_app = server.build_vm_storefront_app(registry=second_registry)

    assert first is not second
    assert first_registry.resolve(first_app.state.storefront_binding) is first
    assert second_registry.resolve(second_app.state.storefront_binding) is second
    assert first_app.state.market_domains[0].domain_identity == "compute.v1"
    assert second_app.state.market_domains[0].domain_identity == "compute.v1"


@pytest.mark.asyncio
async def test_lifespan_publishes_and_clears_exact_contract_without_cross_app_leakage(
    monkeypatch,
) -> None:
    signer = SimpleNamespace(identity=object())
    capacity_runtime = SimpleNamespace(client=lambda: None)
    built = {}

    def fake_sqlite_client(*, registry):
        sqlite_client = SimpleNamespace(
            db_path=f"/{id(registry)}.db",
            domain_registry=registry,
        )
        built["registry"] = registry
        built["sqlite_client"] = sqlite_client
        return sqlite_client

    def fake_capacity_runtime(repository, *, signer: object):
        assert repository() is built["sqlite_client"]
        assert signer is built["signer"]
        return capacity_runtime

    def fake_negotiation_runtime(
        domain,
        *,
        registry,
        binding,
        capacity_runtime: object,
    ):
        registration = registry.resolve_registration(binding)
        assert registry is built["registry"]
        assert registration.contract is domain
        assert capacity_runtime is built["capacity_runtime"]
        runtime = SimpleNamespace(continue_negotiation=lambda: None)
        built["negotiation_runtime"] = runtime
        return runtime

    def fake_listing_service(
        *,
        registry,
        binding,
        domain,
        capacity_runtime: object,
        settlement_composition,
        **_kwargs,
    ):
        assert registry is built["registry"]
        assert registry.resolve(binding) is domain
        assert capacity_runtime is built["capacity_runtime"]
        assert settlement_composition is built["settlement_composition"]
        listing_service = SimpleNamespace(
            domain_registry=registry,
            domain_binding=binding,
            market_domain=domain,
            capacity_runtime=capacity_runtime,
        )
        built["listing_service"] = listing_service
        return listing_service

    def fake_settlement_composition(*, domain, **_kwargs):
        composition = SimpleNamespace(domain=domain)
        built["settlement_composition"] = composition
        return composition

    async def fake_startup_tasks(*, registry, domain):
        registration = registry.resolve_mode("vm")
        assert container.resolved_domain_registry is registry
        assert registration.contract is domain
        assert container.resolved_negotiation_runtime is built["negotiation_runtime"]
        assert container.resolved_listing_service is built["listing_service"]

    monkeypatch.setattr(server, "get_sqlite_client", fake_sqlite_client)
    monkeypatch.setattr(
        server,
        "resolve_marketplace_signer",
        lambda: built.setdefault("signer", signer),
    )
    monkeypatch.setattr(server, "get_registry_authorities", lambda: ())
    monkeypatch.setattr(server, "set_stage_event_db_path", lambda _path: None)
    monkeypatch.setattr(server, "_build_alkahest_clients", lambda: {})
    monkeypatch.setattr(
        capacity_client_module,
        "build_capacity_runtime_for",
        lambda repository, *, signer: built.setdefault(
            "capacity_runtime",
            fake_capacity_runtime(repository, signer=signer),
        ),
    )
    monkeypatch.setattr(
        server,
        "build_vm_negotiation_runtime",
        fake_negotiation_runtime,
    )
    monkeypatch.setattr(server, "_build_listing_service", fake_listing_service)
    monkeypatch.setattr(
        server,
        "_build_system_service",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        server,
        "_build_settlement_composition",
        fake_settlement_composition,
    )
    monkeypatch.setattr(server, "_run_startup_tasks", fake_startup_tasks)
    monkeypatch.setattr(
        server,
        "initialize_administrator_identities",
        lambda _path: None,
    )
    monkeypatch.setattr(
        server,
        "initialize_service_peer_identities",
        lambda _path: None,
    )

    first = build_vm_storefront_domain()
    second = build_vm_storefront_domain()
    for domain in (first, second):
        registry = _registry(domain)
        registration = registry.resolve_mode("vm")
        application = server.build_vm_storefront_app(registry=registry)
        assert application.state.storefront_binding == registration.binding
        async with application.router.lifespan_context(application):
            assert application.state.market_domains[0].domain_identity == "compute.v1"
            assert container.resolved_domain_registry is registry
            assert container.resolved_sqlite_client.domain_registry is registry
            assert container.resolved_listing_service.domain_registry is registry
            assert container.resolved_listing_service.domain_binding == registration.binding
            assert container.resolved_listing_service.market_domain is domain
            assert container.resolved_listing_service.capacity_runtime is capacity_runtime
            assert container.resolved_negotiation_runtime is built["negotiation_runtime"]
            assert container.resolved_settlement_composition.domain is domain
        assert container.resolved_domain_registry is None
        assert container.resolved_sqlite_client is None
        assert container.resolved_listing_service is None
        assert container.resolved_settlement_composition is None
        assert container.resolved_negotiation_runtime is None
        assert container.resolved_negotiation_service is None
