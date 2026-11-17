"""The double's time source setting: wall by default, injected when stated, nothing else."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime, InvalidTimeSource, WallTime

from mediation_lane_double.settings import Settings, install_time_source


@pytest.fixture
def restored_source() -> Iterator[None]:
    before = injected_time.installed()
    yield
    injected_time.install(before)


def test_the_time_source_is_wall_unless_stated() -> None:
    assert Settings.from_environment({}).time_source == "wall"


def test_a_lane_states_injected_time() -> None:
    settings = Settings.from_environment({"MEDIATION_LANE_DOUBLE_TIME_SOURCE": "injected"})

    assert settings.time_source == "injected"


def test_a_misspelled_time_source_is_refused_naming_the_setting_and_the_value() -> None:
    with pytest.raises(InvalidTimeSource) as refused:
        Settings.from_environment({"MEDIATION_LANE_DOUBLE_TIME_SOURCE": "injectd"})

    assert str(refused.value) == (
        "MEDIATION_LANE_DOUBLE_TIME_SOURCE is \"wall\" or \"injected\", not 'injectd'")


def test_injected_time_is_installed_and_announced(
        restored_source: None, caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings.from_environment({"MEDIATION_LANE_DOUBLE_TIME_SOURCE": "injected"})

    with caplog.at_level(logging.INFO):
        source = install_time_source(settings)

    assert isinstance(source, InjectedTime) and injected_time.installed() is source
    [record] = caplog.records
    assert record.getMessage() == (
        f"MEDIATION_LANE_DOUBLE_TIME_SOURCE is injected: the double holds {source.now()} "
        "until its time control sets it")


def test_wall_time_is_installed_silently(
        restored_source: None, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        source = install_time_source(Settings.from_environment({}))

    assert isinstance(source, WallTime) and injected_time.installed() is source
    assert caplog.records == []
