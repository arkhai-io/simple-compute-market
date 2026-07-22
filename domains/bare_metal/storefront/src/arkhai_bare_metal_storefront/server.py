"""FastAPI composition root for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import Any

from core_storefront.app_composition import StorefrontAppConfig, build_storefront_app
from market_core import MarketDomainContract

from .domain_runtime import get_market_domain_contract


DESCRIPTION = (
    "Seller-side storefront for the Arkhai bare-metal marketplace.\n\n"
    "Admin endpoints require an `X-Admin-Key` header. Buyer-facing endpoints "
    "use the shared signed storefront protocol."
)


def build_bare_metal_storefront_app(
    *,
    domain: MarketDomainContract | None = None,
    lifespan: Any | None = None,
    routers: Iterable[Any] = (),
    root_path: str = "",
) -> Any:
    """Build the shared storefront shell around one bare-metal contract."""
    return build_storefront_app(
        config=StorefrontAppConfig(
            title="Arkhai Bare-Metal Storefront",
            description=DESCRIPTION,
            root_path=root_path,
            swagger_ui_parameters={"persistAuthorization": True},
        ),
        domain=domain or get_market_domain_contract(),
        lifespan=lifespan,
        routers=routers,
    )


app = build_bare_metal_storefront_app()


def run_serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    root_path: str = "",
) -> None:
    """Run the composed application with uvicorn."""
    uvicorn = import_module("uvicorn")
    uvicorn.run(app, host=host, port=port, root_path=root_path)
