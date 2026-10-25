"""The API-credit listing rendering the plugin contributes."""

from __future__ import annotations

from arkhai_apicredits_buyer.cli import CONTRIBUTIONS

_RESOURCE = {
    "kind": "api_credits.v1",
    "service_name": "weather-api",
    "description": "Forecasts, 1 token per call",
    "openapi_url": "http://api.example/openapi.json",
    "base_url": "http://api.example",
}


def test_summary_names_the_service_and_its_description():
    rendering = CONTRIBUTIONS.rendering
    summary = rendering.summary(rendering.resource(_RESOURCE))
    assert summary == "weather-api — Forecasts, 1 token per call"
    assert rendering.summary(rendering.resource("not json")) == "-"


def test_columns_and_details_name_the_openapi_and_base_urls():
    rendering = CONTRIBUTIONS.rendering
    assert [(header, value(_RESOURCE)) for header, value in rendering.columns] == [
        ("OpenAPI", "http://api.example/openapi.json")
    ]
    assert dict(rendering.details(_RESOURCE)) == {
        "Service": "weather-api",
        "Description": "Forecasts, 1 token per call",
        "OpenAPI URL": "http://api.example/openapi.json",
        "Base URL": "http://api.example",
    }
