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
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainRegistry,
)
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
    """Complete immutable input to one explicitly registered storefront app."""

    registry: StorefrontDomainRegistry
    binding: StorefrontDomainBinding
    domain: MarketDomainContract
    app: StorefrontAppConfig
    services: StorefrontServiceHooks[ContainerT]
    routes: StorefrontRouteHooks

    def __post_init__(self) -> None:
        if not isinstance(self.registry, StorefrontDomainRegistry):
            raise TypeError("registry must be a StorefrontDomainRegistry")
        if not isinstance(self.binding, StorefrontDomainBinding):
            raise TypeError("binding must be a StorefrontDomainBinding")
        registration = self.registry.resolve_registration(self.binding)
        if registration.contract is not self.domain:
            raise RuntimeError(
                "storefront composition domain must be the exact contract "
                "resolved by its frozen registry and binding"
            )


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
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    domain: MarketDomainContract,
    services: StorefrontServiceHooks[ContainerT],
) -> Callable[[Any], Any]:
    """Build a lifespan bound to one exact frozen registry registration."""

    registration = registry.resolve_registration(binding)
    if registration.contract is not domain:
        raise RuntimeError(
            "storefront lifespan domain must be the exact registered contract"
        )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application: Any):
        expected = registration.binding
        configured = tuple(application.state.market_domains)
        if not any(
            item.offering_mode == expected.offering_mode
            and item.domain_identity == str(expected.domain_identity)
            and item.contract_version == str(expected.contract_version)
            for item in configured
        ):
            raise RuntimeError(
                "FastAPI app registration projection does not contain its "
                "lifespan market-domain binding"
            )
        container = await _resolve(services.build(domain))
        if getattr(container, "domain", None) is not domain:
            raise RuntimeError(
                "storefront service container is not bound to the app-selected "
                "market-domain contract object"
            )
        application.state.storefront_container = container
        started = False
        try:
            await _call_lifecycle(services.start, container)
            started = True
            yield
        finally:
            # A rejected start never acquired lifecycle ownership. Calling its
            # stop hook could clear a different app's registry-owned container.
            if started:
                await _call_lifecycle(services.stop, container)
            application.state.storefront_container = None

    return lifespan


def build_composed_storefront_app(
    composition: StorefrontComposition[ContainerT],
) -> Any:
    """Build one storefront app from explicit registry and domain hooks."""

    application = build_storefront_app(
        config=composition.app,
        registry=composition.registry,
        runtime_resolver=composition.registry.resolve_registration,
        lifespan=build_storefront_lifespan(
            registry=composition.registry,
            binding=composition.binding,
            domain=composition.domain,
            services=composition.services,
        ),
        routers=composition.routes.routers,
    )
    application.state.storefront_binding = composition.binding
    for middleware in composition.routes.middleware:
        application.middleware("http")(middleware)
    return application


def get_storefront_container(request: Any) -> StorefrontContainer:
    """Return the lifespan-owned container for a request without global lookup."""

    container = getattr(request.app.state, "storefront_container", None)
    if container is None:
        raise RuntimeError("storefront service container is unavailable")
    return cast(StorefrontContainer, container)
