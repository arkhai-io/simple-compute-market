"""The registry's ``TIME_SOURCE`` setting and its startup announcement."""

from __future__ import annotations

import logging

from injected_time import InjectedTime, WallTime

from core_registry import main
from core_registry.config import Settings


def test_the_time_source_is_unset_unless_stated(monkeypatch) -> None:
    monkeypatch.delenv("TIME_SOURCE", raising=False)
    assert Settings(_env_file=()).time_source is None
    monkeypatch.setenv("TIME_SOURCE", "injected")
    assert Settings(_env_file=()).time_source == "injected"


def test_an_injected_registry_announces_its_time_and_a_wall_one_nothing(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=main.logger.name):
        main.announce_time_source(InjectedTime(start=1794822300))
        main.announce_time_source(WallTime())

    (record,) = caplog.records
    assert "TIME_SOURCE" in record.getMessage()
    assert "1794822300" in record.getMessage()
