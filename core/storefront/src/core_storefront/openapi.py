"""Shared marketplace-v2 OpenAPI customization for storefront applications."""

from __future__ import annotations

from typing import Any


def install_marketplace_identity_openapi(app: Any, root_path: str = "") -> None:
    """Document the complete v2 identity envelope and gateway root path."""
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
        identity_headers = {
            "MarketplaceSignatureVersion": "X-Market-Signature-Version",
            "MarketplaceIdentityScheme": "X-Market-Identity-Scheme",
            "MarketplaceIdentityIdentifier": "X-Market-Identity-Identifier",
            "MarketplaceRole": "X-Market-Role",
            "MarketplaceRequestId": "X-Market-Request-ID",
            "MarketplaceTimestamp": "X-Market-Timestamp",
            "MarketplaceSignature": "X-Market-Signature",
        }
        security_schemes = schema["components"].setdefault("securitySchemes", {})
        for name, header in identity_headers.items():
            security_schemes[name] = {
                "type": "apiKey",
                "in": "header",
                "name": header,
                "description": (
                    "Part of the body-bound arkhai.market-request-signature.v2 "
                    "authentication envelope."
                ),
            }
        signature_requirement = {name: [] for name in identity_headers}
        service_callbacks = {
            "/api/v1/admin/fulfillment/events/capacity-released",
            "/api/v1/admin/fulfillment/events/usage-started",
            "/api/v1/admin/fulfillment/events/failed",
        }
        for path, path_item in schema.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            if path.startswith("/api/v1/admin/") or path in {
                "/api/v1/system/events",
            } or (
                path.startswith("/api/v1/listings/")
                and (
                    path.endswith("/pause")
                    or path.endswith("/resume")
                    or "/negotiations" in path
                )
            ):
                required_role = "service" if path in service_callbacks else "admin"
                for operation in path_item.values():
                    if not isinstance(operation, dict) or "responses" not in operation:
                        continue
                    operation["security"] = [dict(signature_requirement)]
                    operation["x-market-role"] = required_role
                    operation["description"] = (
                        (operation.get("description") or "")
                        + "\\n\\nRequires all marketplace v2 signature headers with "
                        + f"`X-Market-Role: {required_role}`."
                    ).strip()
        # The gateway prefix as the OpenAPI server URL so Swagger UI builds
        # correct "try it out" requests. The app's root_path drives the docs
        # page's OpenAPI URL; this servers block drives the call targets.
        if root_path:
            schema["servers"] = [{"url": root_path}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi
