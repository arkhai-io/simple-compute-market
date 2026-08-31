"""Reusable FastAPI application composition for storefront executables.

Domain storefronts still own their routers, lifespan setup, and domain-specific
startup tasks. This module owns the generic FastAPI shell shared by storefront
executables: title/description/version/root path, Swagger settings, marketplace
v2 OpenAPI installation, and router registration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
)
from core_storefront.openapi import install_marketplace_identity_openapi



class StorefrontRuntimeResolver(Protocol):
    """Resolve a persisted binding to the startup-owned runtime registration."""

    def __call__(
        self,
        binding: StorefrontDomainBinding,
    ) -> StorefrontDomainRegistration: ...
@dataclass(frozen=True)
class StorefrontAppConfig:
    """Configuration for a storefront FastAPI app shell."""

    title: str
    description: str
    version: str = "1.0.0"
    root_path: str = ""
    swagger_ui_parameters: dict[str, Any] | None = None


DEFAULT_STOREFRONT_DESCRIPTION = (
    "Seller-side storefront for the Arkhai compute marketplace.\n\n"
    "Authenticated routes require the complete "
    "`arkhai.market-request-signature.v2` header envelope: "
    "`X-Market-Signature-Version`, `X-Market-Identity-Scheme`, "
    "`X-Market-Identity-Identifier`, `X-Market-Role`, `X-Market-Request-ID`, "
    "`X-Market-Timestamp`, and `X-Market-Signature`. Administrator routes "
    "require the exact configured scheme-tagged principal and "
    "`X-Market-Role: admin`; provisioning callbacks require an explicitly "
    "trusted service principal and `X-Market-Role: service`."
)


def default_storefront_app_config(*, root_path: str = "") -> StorefrontAppConfig:
    """Return the default app shell config used by storefront executables."""

    return StorefrontAppConfig(
        title="Arkhai Storefront",
        description=DEFAULT_STOREFRONT_DESCRIPTION,
        version="1.0.0",
        root_path=root_path,
        swagger_ui_parameters={"persistAuthorization": True},
    )


def build_storefront_app(
    *,
    config: StorefrontAppConfig,
    registry: StorefrontDomainRegistry,
    runtime_resolver: StorefrontRuntimeResolver,
    lifespan: Any | None = None,
    routers: Iterable[Any] = (),
) -> Any:
    """Build a FastAPI storefront app and register routers.

    ``FastAPI`` remains an optional/lazy import for the core package: concrete
    storefront executables already depend on FastAPI, while lower-level core
    tests can import this module without importing FastAPI until they call the
    builder.
    """

    from fastapi import FastAPI

    app = FastAPI(
        title=config.title,
        description=config.description,
        version=config.version,
        lifespan=lifespan,
        root_path=config.root_path,
        swagger_ui_parameters=config.swagger_ui_parameters,
    )

    for registration in registry.registrations:
        resolved = runtime_resolver(registration.binding)
        if resolved is not registration:
            raise RuntimeError(
                "storefront runtime resolver must return the exact startup-owned "
                f"registration for {registration.binding!r}"
            )
    app.state.market_domains = registry.projection()

    for router in routers:
        app.include_router(router)

    install_marketplace_identity_openapi(app, root_path=config.root_path)
    return app
