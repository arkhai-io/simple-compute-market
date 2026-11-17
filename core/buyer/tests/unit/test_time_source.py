"""The buyer's ``[time]`` table: which source it names, and what it refuses."""

from __future__ import annotations

from typing import Any

import pytest
from injected_time import InvalidTimeSource, WallTime

from core_buyer.time_source import (
    TimeConfigurationError,
    announcement,
    configured_time_source,
    live_sections,
    live_warnings,
)


@pytest.mark.parametrize("config", [{}, {"time": {}}, {"time": {"file": "/lane/now.json"}}])
def test_a_configuration_stating_no_source_names_none(config: dict[str, Any]) -> None:
    assert configured_time_source(config) is None


def test_wall_time_is_named_by_its_value() -> None:
    assert isinstance(configured_time_source({"time": {"source": "wall"}}), WallTime)


def test_a_misspelled_source_is_refused_naming_the_setting_and_the_value() -> None:
    with pytest.raises(InvalidTimeSource) as refused:
        configured_time_source({"time": {"source": "injectd"}})

    assert str(refused.value) == "[time] source is \"wall\" or \"injected\", not 'injectd'"


@pytest.mark.parametrize("time", [{"source": "injected"}, {"source": "injected", "file": ""}])
def test_injected_time_without_a_file_is_refused_naming_the_setting(time: dict[str, Any]) -> None:
    with pytest.raises(TimeConfigurationError, match=r"\[time\] file names no lane-time file"):
        configured_time_source({"time": time})


def test_a_time_value_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(TimeConfigurationError):
        configured_time_source({"time": "injected"})


def test_every_table_stating_livemode_true_is_live_wherever_it_sits() -> None:
    config = {
        "livemode": True,
        "Settlement": {
            "arkhai_payments": {"enabled": True, "livemode": True},
            "alkahest": {"livemode": "true"},
            "other": {"livemode": False},
            "scalar": True,
        },
        "bare_metal": {"registry_url": "https://registry.test",
                       "arkhai_payments": {"livemode": True}},
    }

    assert live_sections(config) == [
        "[Settlement.arkhai_payments]", "[bare_metal.arkhai_payments]"]
    assert live_sections({}) == []


def test_wall_time_is_neither_announced_nor_warned_of() -> None:
    wall = WallTime()
    config = {"Settlement": {"arkhai_payments": {"livemode": True}}}

    assert announcement(wall) is None and announcement(None) is None
    assert live_warnings(wall, config) == [] and live_warnings(None, config) == []
