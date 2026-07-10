"""Reusable FastAPI app shell composition for provisioning executables."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProvisioningAppConfig:
    """Configuration for a provisioning FastAPI app shell."""

    title: str
    description: str
    version: str
    openapi_tags: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ProvisioningMiddlewareMount:
    """Middleware class plus keyword arguments to install on the app."""

    middleware_class: Any
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisioningRouterMount:
    """Router plus optional prefix to register on the app."""

    router: Any
    prefix: str = ""


DEFAULT_PROVISIONING_DESCRIPTION = (
    "Asynchronous provisioning for a multi-agent compute marketplace."
)


def build_provisioning_app(
    *,
    config: ProvisioningAppConfig,
    lifespan: Any | None = None,
    middlewares: Iterable[ProvisioningMiddlewareMount] = (),
    routers: Iterable[ProvisioningRouterMount] = (),
) -> Any:
    """Build a FastAPI provisioning app and register middleware/routers.

    FastAPI remains a lazy import for the core package. Concrete provisioning
    executables already depend on FastAPI, while core unit tests can import this
    module without importing FastAPI unless they call the builder.
    """

    from fastapi import FastAPI

    app = FastAPI(
        title=config.title,
        version=config.version,
        description=config.description,
        openapi_tags=config.openapi_tags,
        lifespan=lifespan,
    )

    for middleware in middlewares:
        app.add_middleware(middleware.middleware_class, **middleware.kwargs)

    for mount in routers:
        if mount.prefix:
            app.include_router(mount.router, prefix=mount.prefix)
        else:
            app.include_router(mount.router)

    return app
