"""The Apprise sink's settings and installation, with no service involved."""

from __future__ import annotations

import pytest
from market_delivery_apprise import AppriseSinkSettings, build_apprise_sink


def test_an_unrecognised_url_is_refused_by_position() -> None:
    with pytest.raises(ValueError, match="url 0") as caught:
        build_apprise_sink({"urls": ["not-a-service://token-secret"]})
    assert "token-secret" not in str(caught.value)


def test_urls_are_secret_settings() -> None:
    schema = AppriseSinkSettings.model_json_schema()
    assert schema["properties"]["urls"]["secret"] is True


def test_the_sink_is_installed_under_its_name() -> None:
    from market_delivery import discover_sink_factories

    factories, _ = discover_sink_factories()
    assert "apprise" in factories


def test_the_sink_declares_its_settings_model() -> None:
    from market_delivery import discover_sink_settings_models

    models, _ = discover_sink_settings_models()
    assert models["apprise"] is AppriseSinkSettings

