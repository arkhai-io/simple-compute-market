"""Shared OpenAPI customization for storefront composition roots.

Every storefront FastAPI app (VM compute, API-tokens, and whatever
domain comes next) authenticates admin endpoints with an ``X-Admin-Key``
header and runs behind an optional gateway path prefix. Both facts shape
the generated schema identically:

* an ``AdminKey`` apiKey security scheme so Swagger renders the
  🔒 Authorize button, and
* a ``servers`` block carrying the gateway prefix so the docs page's
  "try it out" calls target the right path.

This is the one piece the per-domain ``server.py`` roots genuinely
share; the lifespan and router wiring stay domain-specific.
"""

from __future__ import annotations

from typing import Any


def install_admin_key_openapi(app: Any, root_path: str = "") -> None:
    """Install the storefront's custom ``app.openapi`` generator.

    Wires a cached generator that augments FastAPI's default schema with
    the ``X-Admin-Key`` security scheme and — when ``root_path`` is set —
    the gateway ``servers`` block. Call once, after the app and its
    routers exist.
    """
    from fastapi.openapi.utils import get_openapi

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "AdminKey": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Admin-Key",
                "description": "Admin API key — required for all /api/v1/admin/* endpoints.",
            }
        }
        # The gateway prefix as the OpenAPI server URL so Swagger UI builds
        # correct "try it out" requests. The app's root_path drives the docs
        # page's OpenAPI URL; this servers block drives the call targets.
        if root_path:
            schema["servers"] = [{"url": root_path}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi
