"""FastAPI composition root for the bare-metal storefront."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Any

from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.escrow_identity import backfill_escrow_obligation_records
from core_storefront.stage_log import set_stage_event_db_path
from market_core import MarketDomainContract
from market_storefront_kit import (
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_composed_storefront_app,
)

from .api import router as http_router
from .domain_runtime import get_market_domain_contract
from .lifecycle_steps import register_bare_metal_loops
from .response_auth import authenticate_response
from .runtime import BareMetalStorefrontRuntime, build_runtime_from_configuration
from .storefront_registry import build_bare_metal_storefront_registry

DESCRIPTION = (
    "Seller-side storefront for the Arkhai bare-metal marketplace.\n\n"
    "Admin and buyer-facing endpoints use the shared scheme-tagged marketplace "
    "request and response signature version 2 contracts."
)


logger = logging.getLogger(__name__)


async def _start_runtime(runtime: BareMetalStorefrontRuntime) -> None:
    """Start the storefront's loops over its composed runtime.

    The first projection load runs before any timer, so neither the
    site-projection poller nor publication runs its first cycle over
    projections nothing has loaded, and the escrow backfill before servicing,
    which reads what it records. Every loop then runs on the controller's
    timer over its registered step.
    """
    set_stage_event_db_path(runtime.db.db_path)
    if runtime.settlement_runtime is not None:
        await backfill_escrow_obligation_records(
            sqlite_client=runtime.db,
            settlement_runtime=runtime.settlement_runtime,
            local_principal=runtime.seller_principal,
        )
    if runtime.site_projections is not None:
        await runtime.site_projections.poll_once()
    intervals = register_bare_metal_loops(runtime)
    for name in runtime.loops.start_loops(task_logger=logger):
        logger.info("[STARTUP] %s started (interval=%ss)", name, intervals.get(name))


async def _stop_runtime(runtime: BareMetalStorefrontRuntime) -> None:
    """Cancel every loop and wait for each task to end, so none outlives the app.

    No cycle is left running against a runtime its app has uninstalled, and an
    app started again over the same runtime registers and starts its loops
    afresh. A publication cycle cancelled mid-run stops its worker thread
    through the kit's cycle driver; this waits for the loop's task only.
    """
    await runtime.loops.stop_loops()


def build_bare_metal_storefront_app(
    *,
    registry: StorefrontDomainRegistry,
    runtime: BareMetalStorefrontRuntime | None = None,
    runtime_factory: Callable[[], BareMetalStorefrontRuntime] | None = None,
    routers: Iterable[Any] = (),
    root_path: str = "",
) -> Any:
    """Build the shared storefront shell around one bare-metal registration."""

    registration = registry.resolve_mode("bare_metal")
    selected_domain = registration.contract

    def build_services(domain: MarketDomainContract) -> BareMetalStorefrontRuntime:
        if domain is not selected_domain:
            raise RuntimeError(
                "storefront kit supplied a domain outside the bare-metal registration"
            )
        if runtime_factory is not None:
            selected_runtime = runtime_factory()
        elif runtime is not None:
            selected_runtime = runtime
        else:
            selected_runtime = build_runtime_from_configuration(domain=domain)
        if selected_runtime.domain is not domain:
            raise RuntimeError(
                "bare-metal runtime must carry the exact registered domain contract"
            )
        return selected_runtime

    service_hooks = StorefrontServiceHooks(
        build=build_services,
        start=_start_runtime,
        stop=_stop_runtime,
    )
    return build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=registration.binding,
            domain=selected_domain,
            app=StorefrontAppConfig(
                title="Arkhai Bare-Metal Storefront",
                description=DESCRIPTION,
                root_path=root_path,
                swagger_ui_parameters={"persistAuthorization": True},
            ),
            services=service_hooks,
            routes=StorefrontRouteHooks(
                routers=(http_router, *tuple(routers)),
                middleware=(authenticate_response,),
            ),
        )
    )


BARE_METAL_STOREFRONT_REGISTRY = build_bare_metal_storefront_registry(
    domain=get_market_domain_contract(),
)
app = build_bare_metal_storefront_app(
    registry=BARE_METAL_STOREFRONT_REGISTRY,
)


def run_serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    root_path: str = "",
) -> None:
    """Run the composed application with uvicorn."""
    uvicorn = import_module("uvicorn")
    uvicorn.run(app, host=host, port=port, root_path=root_path)
