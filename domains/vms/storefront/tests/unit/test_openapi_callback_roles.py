"""The fulfillment-event routes the VM storefront serves, and the caller role
its OpenAPI document gives each."""

from __future__ import annotations

from core_storefront.openapi import install_marketplace_identity_openapi
from fastapi import FastAPI

from market_storefront.controllers.admin_controller import router as admin_router

_EVENTS = "/api/v1/admin/fulfillment/events/"


def test_capacity_released_is_the_one_fulfillment_event_and_a_service_callback() -> None:
    app = FastAPI()
    app.include_router(admin_router)
    install_marketplace_identity_openapi(app)

    events = {
        path: {method: operation["x-market-role"] for method, operation in item.items()}
        for path, item in app.openapi()["paths"].items()
        if path.startswith(_EVENTS)
    }

    assert events == {f"{_EVENTS}capacity-released": {"post": "service"}}
