from market_storefront.server import app


def test_server_uses_shared_storefront_app_shell():
    assert app.title == "Arkhai Storefront"
    assert app.version == "1.0.0"
    assert app.swagger_ui_parameters == {"persistAuthorization": True}
    assert app.openapi.__name__ == "_custom_openapi"

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/system/status" in paths
    assert "/api/v1/listings/create" in paths
    assert "/api/v1/settle/{escrow_uid}" in paths
