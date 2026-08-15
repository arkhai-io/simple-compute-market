from __future__ import annotations

from dataclasses import dataclass

import pytest
from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.domain_registry import (
    StorefrontDomainRegistry,
    StorefrontDomainRegistration,
)
from fastapi import APIRouter
from market_core import (
    DomainCapability,
    DomainIdentity,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    ImmutableBuyerCapability,
    MARKET_DOMAIN_CONTRACT_VERSION,
    MarketDomainContract,
)

from market_storefront_kit import (
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_composed_storefront_app,
)


class Codecs:
    def listing(self, value):
        return value

    def message(self, value):
        return value

    def terms(self, value):
        return value

    def materialization(self, value):
        return value

    def receipt(self, value):
        return value

    def result(self, value):
        return value


def _domain(identity: str = "external.example") -> MarketDomainContract:
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=Codecs(),
        declared_capabilities=frozenset(
            {
                DomainCapability.BUYER,
                DomainCapability.PUBLICATION,
                DomainCapability.STOREFRONT,
                DomainCapability.SETTLEMENT,
                DomainCapability.FULFILLMENT,
            }
        ),
        buyer=ImmutableBuyerCapability(
            identity_injection_contract="core.resolved-buyer-identity.v1",
            register_commands=lambda app: None,
            build_provision_terms=lambda **payload: payload,
            select_policy=lambda: "policy",
            decode_result=lambda payload: payload,
        ),
        publication=ImmutablePublicationCapability(
            source_factory=lambda: (),
        ),
        storefront=ImmutableStorefrontCapability(
            run_negotiation_policy=lambda *args, **kwargs: None,
        ),
        settlement=ImmutableSettlementCapability(
            verify=lambda *args, **kwargs: None,
            build_plan=lambda *args, **kwargs: None,
        ),
        fulfillment=ImmutableFulfillmentCapability(
            fulfill=lambda *args, **kwargs: None,
        ),
    )


def _registry(domain: MarketDomainContract) -> StorefrontDomainRegistry:
    return StorefrontDomainRegistry(
        (
            StorefrontDomainRegistration(
                offering_mode="external",
                contract=domain,
                contribution_id="external",
            ),
        )
    )

@dataclass(frozen=True)
class Container:
    domain: MarketDomainContract
    service: object


@pytest.mark.asyncio
async def test_composition_carries_exact_contract_through_lifecycle_and_routes():
    domain = _domain()
    registry = _registry(domain)
    service = object()
    events: list[tuple[str, object]] = []
    router = APIRouter()

    @router.get("/probe")
    async def probe():
        return {"ok": True}

    async def start(container: Container) -> None:
        events.append(("start", container.service))

    async def stop(container: Container) -> None:
        events.append(("stop", container.service))

    app = build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=registry.resolve_mode("external").binding,
            domain=domain,
            app=StorefrontAppConfig(title="External", description="external"),
            services=StorefrontServiceHooks(
                build=lambda selected: Container(selected, service),
                start=start,
                stop=stop,
            ),
            routes=StorefrontRouteHooks(routers=(router,)),
        )
    )

    assert app.state.storefront_binding == registry.resolve_mode("external").binding
    assert app.state.market_domains[0].domain_identity == "external.example"
    assert any(route.path == "/probe" for route in app.routes)
    async with app.router.lifespan_context(app):
        assert app.state.storefront_container.domain is domain
        assert app.state.storefront_container.service is service
        assert events == [("start", service)]
    assert app.state.storefront_container is None
    assert events == [("start", service), ("stop", service)]


@pytest.mark.asyncio
async def test_lifespan_rejects_reconstructed_equal_contract_container():
    domain = _domain()
    registry = _registry(domain)
    replacement = _domain()
    app = build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=registry.resolve_mode("external").binding,
            domain=domain,
            app=StorefrontAppConfig(title="External", description="external"),
            services=StorefrontServiceHooks(
                build=lambda _selected: Container(replacement, object()),
            ),
            routes=StorefrontRouteHooks(routers=()),
        )
    )

    with pytest.raises(RuntimeError, match="contract object"):
        async with app.router.lifespan_context(app):
            pass
