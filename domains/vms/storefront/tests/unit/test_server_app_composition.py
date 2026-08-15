from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest

import market_storefront.container as container
import market_storefront.server as server
from market_storefront.domain_runtime import build_vm_storefront_domain


def test_server_uses_shared_storefront_app_shell() -> None:
    app = server.app

    assert app.title == "Arkhai Storefront"
    assert app.version == "1.0.0"
    assert app.swagger_ui_parameters == {"persistAuthorization": True}
    assert app.openapi.__name__ == "_custom_openapi"
    assert app.state.market_domain.identity == "compute.v1"

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/system/status" in paths
    assert "/api/v1/listings/create" in paths
    assert "/api/v1/settle/{escrow_uid}" in paths


def test_app_factory_retains_each_distinct_compatible_contract() -> None:
    first = build_vm_storefront_domain()
    second = build_vm_storefront_domain()

    first_app = server.build_vm_storefront_app(domain=first)
    second_app = server.build_vm_storefront_app(domain=second)

    assert first is not second
    assert first_app.state.market_domain is first
    assert second_app.state.market_domain is second


@pytest.mark.asyncio
async def test_lifespan_publishes_and_clears_exact_contract_without_cross_app_leakage(
    monkeypatch,
) -> None:
    signer = SimpleNamespace(identity=object())

    def fake_sqlite_client(*, domain):
        return SimpleNamespace(db_path=f"/{id(domain)}.db", market_domain=domain)

    def fake_listing_service(*, domain, **_kwargs):
        return SimpleNamespace(market_domain=domain)

    def fake_negotiation_service(*, domain, **_kwargs):
        return SimpleNamespace(
            _continue_negotiation=partial(lambda: None, domain=domain)
        )

    def fake_settlement_composition(*, domain, **_kwargs):
        return SimpleNamespace(domain=domain)

    async def fake_startup_tasks(*, domain):
        assert container.resolved_market_domain is domain

    monkeypatch.setattr(server, "get_sqlite_client", fake_sqlite_client)
    monkeypatch.setattr(server, "resolve_marketplace_signer", lambda: signer)
    monkeypatch.setattr(server, "get_registry_authorities", lambda: ())
    monkeypatch.setattr(server, "set_stage_event_db_path", lambda _path: None)
    monkeypatch.setattr(server, "_build_alkahest_clients", lambda: {})
    monkeypatch.setattr(server, "_build_listing_service", fake_listing_service)
    monkeypatch.setattr(server, "_build_negotiation_service", fake_negotiation_service)
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
        application = server.build_vm_storefront_app(domain=domain)
        async with application.router.lifespan_context(application):
            assert application.state.market_domain is domain
            assert container.resolved_market_domain is domain
            assert container.resolved_sqlite_client.market_domain is domain
            assert container.resolved_listing_service.market_domain is domain
            assert container.resolved_settlement_composition.domain is domain
        assert container.resolved_market_domain is None
        assert container.resolved_sqlite_client is None
        assert container.resolved_listing_service is None
        assert container.resolved_settlement_composition is None
