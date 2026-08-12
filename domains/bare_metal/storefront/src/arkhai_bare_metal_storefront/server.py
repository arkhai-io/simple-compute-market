"""FastAPI composition root for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

from core_storefront.app_composition import StorefrontAppConfig, build_storefront_app
from market_core import MarketDomainContract

from .api import router as http_router
from .domain_runtime import get_market_domain_contract
from .runtime import BareMetalStorefrontRuntime, build_runtime_from_environment
from .response_auth import authenticate_response


DESCRIPTION = (
    "Seller-side storefront for the Arkhai bare-metal marketplace.\n\n"
    "Admin and buyer-facing endpoints use the shared scheme-tagged marketplace "
    "request and response signature version 2 contracts."
)


def _runtime_lifespan(
    factory: Callable[[], BareMetalStorefrontRuntime],
):
    @asynccontextmanager
    async def lifespan(app: Any):
        app.state.runtime = factory()
        yield

    return lifespan


def build_bare_metal_storefront_app(
    *,
    domain: MarketDomainContract | None = None,
    runtime: BareMetalStorefrontRuntime | None = None,
    runtime_factory: Callable[[], BareMetalStorefrontRuntime] | None = None,
    lifespan: Any | None = None,
    routers: Iterable[Any] = (),
    root_path: str = "",
) -> Any:
    """Build the shared storefront shell around one bare-metal contract."""
    selected_domain = domain or get_market_domain_contract()
    if lifespan is None:
        factory = runtime_factory or (
            (lambda: runtime)
            if runtime is not None
            else lambda: build_runtime_from_environment(domain=selected_domain)
        )
        lifespan = _runtime_lifespan(factory)
    app = build_storefront_app(
        config=StorefrontAppConfig(
            title="Arkhai Bare-Metal Storefront",
            description=DESCRIPTION,
            root_path=root_path,
            swagger_ui_parameters={"persistAuthorization": True},
        ),
        domain=selected_domain,
        lifespan=lifespan,
        routers=(http_router, *tuple(routers)),
    )
    app.middleware("http")(authenticate_response)
    return app


app = build_bare_metal_storefront_app()


def run_serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    root_path: str = "",
) -> None:
    """Run the composed application with uvicorn."""
    uvicorn = import_module("uvicorn")
    uvicorn.run(app, host=host, port=port, root_path=root_path)
