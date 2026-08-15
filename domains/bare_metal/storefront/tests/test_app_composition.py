from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from market_core import DomainCapability, DomainContractValidationError

import arkhai_bare_metal_storefront.runtime as runtime_module
import arkhai_bare_metal_storefront.server as server_module
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
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
    assert app.state.storefront_binding.offering_mode == "bare_metal.ansible"
    assert "/healthz" in {route.path for route in app.routes}


def test_app_rejects_inconsistent_domain_before_startup() -> None:
    invalid = replace(
        get_market_domain_contract(),
        declared_capabilities=(
            get_market_domain_contract().declared_capabilities
            | {DomainCapability.FULFILLMENT}
        ),
    )

    with pytest.raises(
        DomainContractValidationError,
        match="provides no implementation",
    ):
        build_bare_metal_storefront_app(registry=_registry(invalid))


def test_runnable_http_contract_excludes_fulfillment_claims() -> None:
    app = build_bare_metal_storefront_app(registry=_registry())
    paths = set(app.openapi()["paths"])

    assert {
        "/api/v1/listings",
        "/api/v1/listings/{listing_id}",
        "/api/v1/negotiate/new",
        "/api/v1/negotiate/{negotiation_id}",
        "/api/v1/settle/{escrow_uid}",
        "/api/v1/settle/{escrow_uid}/status",
        "/api/v1/admin/pause",
        "/api/v1/admin/resume",
        "/api/v1/system/status",
        "/health",
    } <= paths
    assert not any(
        fragment in path
        for path in paths
        for fragment in ("fulfillment", "provision", "claim", "collect")
    )
    settle_schema = app.openapi()["components"]["schemas"]["BareMetalSettleRequest"]
    assert set(settle_schema["properties"]) == {
        "negotiation_id",
        "buyer_principal",
        "buyer_evm_address",
    }


def test_importing_app_does_not_construct_publication_source() -> None:
    contract = get_market_domain_contract()

    app = build_bare_metal_storefront_app(registry=_registry(contract))

    assert app.state.storefront_binding == _registry(contract).resolve_mode(
        "bare_metal.ansible"
    ).binding
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
