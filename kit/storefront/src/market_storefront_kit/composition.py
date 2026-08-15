"""Domain-neutral storefront application and lifecycle composition.

A domain composition root supplies one validated market contract, an immutable
set of service lifecycle callbacks, and its ordered route contribution.  This
module owns the shared FastAPI shell and carries the exact contract into the
lifespan-built container; it never resolves a domain from module state.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, cast

from core_storefront.app_composition import StorefrontAppConfig, build_storefront_app
from market_core import MarketDomainContract


class StorefrontContainer(Protocol):
    """Minimum container contract required by the shared lifespan."""

    domain: MarketDomainContract


ContainerT = TypeVar("ContainerT", bound=StorefrontContainer)
LifecycleResult = Awaitable[None] | None
ContainerResult = ContainerT | Awaitable[ContainerT]


@dataclass(frozen=True, slots=True)
class StorefrontServiceHooks(Generic[ContainerT]):
    """Domain-owned service/container construction injected into the kit shell."""

    build: Callable[[MarketDomainContract], ContainerResult]
    start: Callable[[ContainerT], LifecycleResult] | None = None
    stop: Callable[[ContainerT], LifecycleResult] | None = None


@dataclass(frozen=True, slots=True)
class StorefrontRouteHooks:
    """Ordered routers and HTTP middleware contributed by a storefront domain."""

    routers: tuple[Any, ...]
    middleware: tuple[Callable[..., Any], ...] = ()


@dataclass(frozen=True, slots=True)
class StorefrontComposition(Generic[ContainerT]):
    """Complete immutable input to one single-domain storefront application."""

    domain: MarketDomainContract
    app: StorefrontAppConfig
    services: StorefrontServiceHooks[ContainerT]
    routes: StorefrontRouteHooks


async def _resolve(value: ContainerResult) -> ContainerT:
    if inspect.isawaitable(value):
        return cast(ContainerT, await value)
    return value


async def _call_lifecycle(
    callback: Callable[[ContainerT], LifecycleResult] | None,
    container: ContainerT,
) -> None:
    if callback is None:
        return
    result = callback(container)
    if inspect.isawaitable(result):
        await result


def build_storefront_lifespan(
    *,
    domain: MarketDomainContract,
    services: StorefrontServiceHooks[ContainerT],
) -> Callable[[Any], Any]:
    """Build a lifespan that binds one contract to one service container."""

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application: Any):
        if getattr(application.state, "market_domain", None) is not domain:
            raise RuntimeError(
                "FastAPI app and lifespan must share the exact market-domain "
                "contract object"
            )
        container = await _resolve(services.build(domain))
        if getattr(container, "domain", None) is not domain:
            raise RuntimeError(
                "storefront service container is not bound to the app-selected "
                "market-domain contract object"
            )
        application.state.storefront_container = container
        try:
            await _call_lifecycle(services.start, container)
            yield
        finally:
            await _call_lifecycle(services.stop, container)
            application.state.storefront_container = None

    return lifespan


def build_composed_storefront_app(
    composition: StorefrontComposition[ContainerT],
) -> Any:
    """Build one storefront app from explicit domain, service, and route hooks."""

    application = build_storefront_app(
        config=composition.app,
        domain=composition.domain,
        lifespan=build_storefront_lifespan(
            domain=composition.domain,
            services=composition.services,
        ),
        routers=composition.routes.routers,
    )
    for middleware in composition.routes.middleware:
        application.middleware("http")(middleware)
    return application


def get_storefront_container(request: Any) -> StorefrontContainer:
    """Return the lifespan-owned container for a request without global lookup."""

    container = getattr(request.app.state, "storefront_container", None)
    if container is None:
        raise RuntimeError("storefront service container is unavailable")
    return cast(StorefrontContainer, container)
