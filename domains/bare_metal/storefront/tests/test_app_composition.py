from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from importlib.metadata import entry_points

import pytest
from fastapi import APIRouter
from market_core import DomainCapability, DomainContractValidationError
from core_storefront.domain_plugins import STOREFRONT_CONTRIBUTION_GROUP

import arkhai_bare_metal_storefront.runtime as runtime_module
import arkhai_bare_metal_storefront.server as server_module
from arkhai_bare_metal_storefront.contribution import (
    BARE_METAL_STOREFRONT_CONTRIBUTION,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.fulfillment_service import fulfill_bare_metal
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)


def _registry(domain=None):
    return build_bare_metal_storefront_registry(
        domain=domain or get_market_domain_contract()
    )


def test_app_injects_validated_bare_metal_contract_and_router() -> None:
    router = APIRouter()

    @router.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app = build_bare_metal_storefront_app(
        registry=_registry(),
        routers=(router,),
        root_path="/bare-metal",
    )

    assert app.title == "Arkhai Bare-Metal Storefront"
    assert app.root_path == "/bare-metal"
    assert app.state.storefront_binding.offering_mode == "bare_metal"
    assert "/healthz" in {route.path for route in app.routes}


def test_app_rejects_inconsistent_domain_before_startup() -> None:
    invalid = replace(
        get_market_domain_contract(),
        fulfillment=None,
    )

    with pytest.raises(
        DomainContractValidationError,
        match="provides no implementation",
    ):
        build_bare_metal_storefront_app(registry=_registry(invalid))


def test_runnable_http_contract_includes_fulfillment_claims() -> None:
    app = build_bare_metal_storefront_app(registry=_registry())
    paths = set(app.openapi()["paths"])

    assert {
        "/api/v1/listings",
        "/api/v1/listings/{listing_id}",
        "/api/v1/negotiate/new",
        "/api/v1/negotiate/{negotiation_id}",
        "/api/v1/settle/{escrow_uid}",
        "/api/v1/settle/{escrow_uid}/status",
        "/api/v1/fulfillments/begin",
        "/api/v1/fulfillments/{negotiation_id}/status",
        "/api/v1/fulfillments/{negotiation_id}/result",
        "/api/v1/fulfillments/{negotiation_id}/teardown",
        "/api/v1/admin/pause",
        "/api/v1/admin/resume",
        "/api/v1/system/status",
        "/health",
    } <= paths
    assert DomainCapability.FULFILLMENT in (
        get_market_domain_contract().declared_capabilities
    )
    settle_schema = app.openapi()["components"]["schemas"]["BareMetalSettleRequest"]
    assert set(settle_schema["properties"]) == {
        "negotiation_id",
        "buyer_principal",
        "buyer_evm_address",
    }


def test_registry_injects_exact_contract_binding_without_publication_source() -> None:
    contract = get_market_domain_contract()
    registry = _registry(contract)
    registration = registry.resolve_mode("bare_metal")

    app = build_bare_metal_storefront_app(registry=registry)

    assert registration.contract is contract
    assert registry.resolve(registration.binding) is contract
    assert app.state.storefront_binding == registration.binding
    assert app.state.market_domains == registry.projection()
    assert not hasattr(app.state, "publication_source")


@pytest.mark.asyncio
async def test_lifespan_exposes_exact_bare_metal_runtime_without_global_lookup(
    monkeypatch,
) -> None:
    domain = get_market_domain_contract()
    runtime = SimpleNamespace(domain=domain)
    started = []

    async def start(selected):
        started.append(selected)

    monkeypatch.setattr(server_module, "_start_runtime", start)
    app = build_bare_metal_storefront_app(
        registry=_registry(domain),
        runtime=runtime,
    )

    async with app.router.lifespan_context(app):
        assert app.state.storefront_container is runtime
        assert app.state.storefront_container.domain is domain
    assert app.state.storefront_container is None
    assert started == [runtime]


def test_bare_metal_contributes_chain_values_to_shared_factory(monkeypatch) -> None:
    captured = []
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_CHAINS",
        '{"anvil":{"rpc_url":"http://rpc",'
        '"alkahest_address_config_path":"addresses.json"}}',
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY", "secret")
    monkeypatch.setattr(
        runtime_module,
        "build_alkahest_clients",
        lambda policy, **_kwargs: captured.append(policy) or {"anvil": object()},
    )

    clients, paths = runtime_module._build_chain_clients_from_environment()

    assert tuple(clients) == ("anvil",)
    assert paths == {"anvil": "addresses.json"}
    assert captured[0].chains[0].rpc_url == "http://rpc"


def test_bare_metal_watchdog_uses_domain_environment_schedule(monkeypatch) -> None:
    monkeypatch.setenv("BARE_METAL_NEGOTIATION_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("BARE_METAL_NEGOTIATION_WATCHDOG_INTERVAL", "45")

    policy = server_module._negotiation_watchdog_policy()

    assert policy.timeout_seconds == 900
    assert policy.interval_seconds == 45
    assert policy.terminal_state == "abandoned"


def test_installed_contribution_exposes_complete_bare_metal_contract() -> None:
    contribution = BARE_METAL_STOREFRONT_CONTRIBUTION
    matching = [
        entry_point
        for entry_point in entry_points(group=STOREFRONT_CONTRIBUTION_GROUP)
        if entry_point.name == "bare_metal"
    ]
    contract = contribution.build_contract()

    assert len(matching) == 1
    assert matching[0].load() is contribution
    assert contribution.contribution_id == "bare_metal"
    assert contract is get_market_domain_contract()
    assert contract.publication is not None
    assert contract.storefront is not None
    assert contract.settlement is not None
    assert contract.fulfillment is not None
    assert contract.fulfillment.fulfill is fulfill_bare_metal
