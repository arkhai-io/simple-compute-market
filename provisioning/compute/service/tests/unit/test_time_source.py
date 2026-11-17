"""The provisioning service's ``time.source`` and its startup announcement."""

from __future__ import annotations

import logging

from dynaconf import Dynaconf
from injected_time import InjectedTime, WallTime

from compute_provisioning_service import main
from compute_provisioning_service.config import Settings


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


def test_an_injected_service_announces_its_time_and_a_wall_one_nothing(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=main.logger.name):
        main.announce_time_source(InjectedTime(start=1794822300))
        main.announce_time_source(WallTime())

    (record,) = caplog.records
    assert "time.source" in record.getMessage()
    assert "1794822300" in record.getMessage()
