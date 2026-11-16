"""The storefronts' time controls: the setting, the route service, the announcement."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime, WallTime
from pydantic import BaseModel, ValidationError

from market_storefront_kit import (
    StorefrontTimeRouteService,
    TimeRouteError,
    TimeSourceSetting,
    announce_time_source,
    configured_time_source,
    install_time_source,
    time_refusal_body,
)

T = 1794822300


@pytest.fixture(autouse=True)
def restored_source() -> Iterator[None]:
    before = injected_time.installed()
    yield
    injected_time.install(before)


def test_an_unset_source_installs_wall_time() -> None:
    assert isinstance(install_time_source(None), WallTime)
    assert isinstance(injected_time.installed(), WallTime)


def test_an_injected_source_is_installed_frozen() -> None:
    source = install_time_source("injected")

    assert isinstance(source, InjectedTime)
    assert injected_time.installed() is source


def test_a_misspelled_source_refuses_naming_the_setting_and_the_value() -> None:
    before = injected_time.installed()
    with pytest.raises(injected_time.InvalidTimeSource) as refused:
        install_time_source("injectd")

    assert "[Time] source" in str(refused.value)
    assert "injectd" in str(refused.value)
    assert injected_time.installed() is before


class _Settings(BaseModel):
    source: TimeSourceSetting = "wall"


def test_the_typed_setting_admits_the_two_sources_and_names_any_other() -> None:
    assert _Settings().source == "wall"
    assert _Settings(source="injected").source == "injected"
    with pytest.raises(ValidationError) as refused:
        _Settings(source="injectd")
    assert "[Time] source" in str(refused.value)
    assert "injectd" in str(refused.value)


def test_a_wall_source_mounts_no_route_and_reports_its_source_alone() -> None:
    service = StorefrontTimeRouteService(WallTime())

    assert service.mounted is False
    assert service.status() == {"source": "wall"}


def test_the_route_service_reads_the_installed_source_when_built() -> None:
    injected_time.install(InjectedTime(start=T))

    service = StorefrontTimeRouteService()

    assert service.mounted is True
    assert service.status() == {"source": "injected", "now": T}


def test_the_route_service_sets_its_source_and_a_refusal_carries_its_code() -> None:
    # The value rule and the forward-only set are the component's, tested there;
    # this is the storefronts' binding of them and the refusal body they answer.
    source = InjectedTime(start=T)
    service = StorefrontTimeRouteService(source)

    assert service.set_time(b'{"now": 1794823200}') == {
        "source": "injected",
        "now": 1794823200,
    }
    with pytest.raises(TimeRouteError) as refused:
        service.set_time(b'{"now": 1794822300}')

    assert time_refusal_body(refused.value) == {
        "code": refused.value.code,
        "detail": refused.value.detail,
    }
    assert source.now() == 1794823200


def test_the_configured_source_is_read_from_the_time_section_in_any_case() -> None:
    assert configured_time_source({}) is None
    assert configured_time_source({"time": "injected"}) is None
    assert configured_time_source({"time": {"SOURCE": "injected"}}) == "injected"
    assert configured_time_source({"time": {"source": "injectd"}}) == "injectd"


def test_a_wall_storefront_announces_nothing(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("storefront-under-test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        announce_time_source(WallTime(), payments_livemode=True, logger=logger)

    assert caplog.records == []


def test_an_injected_storefront_announces_its_source_and_warns_beside_live_payments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("storefront-under-test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        announce_time_source(InjectedTime(start=T), payments_livemode=False, logger=logger)
    announced = [(record.levelno, record.getMessage()) for record in caplog.records]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=logger.name):
        announce_time_source(InjectedTime(start=T), payments_livemode=True, logger=logger)
    warned = [record for record in caplog.records if record.levelno == logging.WARNING]

    assert len(announced) == 1
    assert announced[0][0] == logging.INFO
    assert "[Time] source" in announced[0][1] and str(T) in announced[0][1]
    assert len(warned) == 1
    assert "[Time] source" in warned[0].getMessage()
    assert "[Settlement.arkhai_payments] livemode" in warned[0].getMessage()
