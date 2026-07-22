from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import APIRouter
from market_core import DomainCapability, DomainContractValidationError

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
        declared_capabilities=(
            get_market_domain_contract().declared_capabilities
            | {DomainCapability.SETTLEMENT}
        ),
    )

    with pytest.raises(
        DomainContractValidationError,
        match="provides no implementation",
    ):
        build_bare_metal_storefront_app(domain=invalid)


def test_importing_app_does_not_construct_publication_source() -> None:
    contract = get_market_domain_contract()

    app = build_bare_metal_storefront_app(domain=contract)

    assert app.state.market_domain.publication is contract.publication
    assert not hasattr(app.state, "publication_source")
