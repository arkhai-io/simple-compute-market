"""The credits service's ``time.source`` setting, read as stated."""

from __future__ import annotations

from dynaconf import Dynaconf

from apicredits_service.config import Settings


def _settings(**values) -> Settings:
    source = Dynaconf(environments=False)
    for key, value in values.items():
        source.set(key, value)
    return Settings(source)


def test_the_time_source_is_unset_unless_a_layer_states_it() -> None:
    assert _settings().configured_time_source is None
    assert _settings(time="injected").configured_time_source is None


def test_the_time_source_is_read_as_stated_in_any_case() -> None:
    assert _settings(time={"source": "injected"}).configured_time_source == "injected"
    assert _settings(TIME={"SOURCE": "wall"}).configured_time_source == "wall"
    assert _settings(time={"source": "injectd"}).configured_time_source == "injectd"
