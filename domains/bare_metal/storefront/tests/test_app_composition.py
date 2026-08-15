from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import APIRouter
from market_core import DomainCapability, DomainContractValidationError

from arkhai_bare_metal_storefront.contribution import (
    BARE_METAL_STOREFRONT_CONTRIBUTION,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app


def test_app_injects_validated_bare_metal_contract_and_router() -> None:
    router = APIRouter()

    @router.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app = build_bare_metal_storefront_app(
        routers=(router,),
        root_path="/bare-metal",
    )

    assert app.title == "Arkhai Bare-Metal Storefront"
    assert app.root_path == "/bare-metal"
    assert app.state.market_domain is get_market_domain_contract()
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
        build_bare_metal_storefront_app(domain=invalid)


def test_runnable_http_contract_includes_fulfillment_claims() -> None:
    app = build_bare_metal_storefront_app()
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


def test_importing_app_does_not_construct_publication_source() -> None:
    contract = get_market_domain_contract()

    app = build_bare_metal_storefront_app(domain=contract)

    assert app.state.market_domain.publication is contract.publication
    assert not hasattr(app.state, "publication_source")


def test_installed_contribution_exposes_complete_bare_metal_contract() -> None:
    contribution = BARE_METAL_STOREFRONT_CONTRIBUTION

    assert contribution.contribution_id == "bare_metal"
    assert contribution.build_contract() is get_market_domain_contract()
