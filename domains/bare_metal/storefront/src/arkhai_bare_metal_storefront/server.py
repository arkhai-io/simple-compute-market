"""FastAPI composition root for the bare-metal storefront."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from functools import partial
from importlib import import_module
from typing import Any

from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.app_startup import StorefrontBackgroundTask
from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.escrow_identity import backfill_escrow_obligation_records
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_core import MarketDomainContract
from market_storefront_kit import (
    NegotiationWatchdogPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_composed_storefront_app,
    run_negotiation_watchdog,
)

from .api import router as http_router
from .domain_runtime import get_market_domain_contract
from .lifecycle_steps import NEGOTIATION_WATCHDOG, SETTLEMENT_SERVICING
from .runtime import BareMetalStorefrontRuntime, build_runtime_from_environment
from .storefront_registry import build_bare_metal_storefront_registry
from .response_auth import authenticate_response


DESCRIPTION = (
    "Seller-side storefront for the Arkhai bare-metal marketplace.\n\n"
    "Admin and buyer-facing endpoints use the shared scheme-tagged marketplace "
    "request and response signature version 2 contracts."
)


def _negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    return NegotiationWatchdogPolicy(
        timeout_seconds=float(
            os.environ.get("BARE_METAL_NEGOTIATION_TIMEOUT_SECONDS", "1800")
        ),
        interval_seconds=float(
            os.environ.get("BARE_METAL_NEGOTIATION_WATCHDOG_INTERVAL", "60")
        ),
    )


async def _start_runtime(runtime: BareMetalStorefrontRuntime) -> None:
    set_stage_event_db_path(runtime.db.db_path)
    loops = runtime.loops
    policy = _negotiation_watchdog_policy()
    loops.start_loop(
        StorefrontBackgroundTask(
            name=NEGOTIATION_WATCHDOG,
            task_factory=partial(
                run_negotiation_watchdog,
                runtime.db,
                policy,
                emit_stage_event=stage_event,
                paused=loops.loop_gate(NEGOTIATION_WATCHDOG),
                wait=loops.idle,
            ),
        )
    )
    if runtime.settlement_runtime is not None:
        await backfill_escrow_obligation_records(
            sqlite_client=runtime.db,
            settlement_runtime=runtime.settlement_runtime,
            local_principal=runtime.seller_principal,
        )
    if runtime.settlement_worker is not None:
        loops.start_loop(
            StorefrontBackgroundTask(
                name=SETTLEMENT_SERVICING,
                task_factory=partial(
                    runtime.settlement_worker.run,
                    paused=loops.loop_gate(SETTLEMENT_SERVICING),
                    wait=loops.idle,
                ),
            )
        )


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
            selected_runtime = build_runtime_from_environment(domain=domain)
        if selected_runtime.domain is not domain:
            raise RuntimeError(
                "bare-metal runtime must carry the exact registered domain contract"
            )
        return selected_runtime

    service_hooks = StorefrontServiceHooks(
        build=build_services,
        start=_start_runtime,
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
