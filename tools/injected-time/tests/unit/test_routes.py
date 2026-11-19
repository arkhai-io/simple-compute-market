"""The route service: the setting route's answers and refusals, and the status section."""

from __future__ import annotations

import pytest

from injected_time import InjectedTime, TimeFile, TimeRouteError, TimeRouteService, WallTime


def test_a_set_answers_the_source_and_the_instant_set() -> None:
    source = InjectedTime(start=1794821400)
    service = TimeRouteService(source)

    assert service.set_time('{"now": 1794822300}') == {"source": "injected", "now": 1794822300}
    assert source.now() == 1794822300
    assert service.status() == {"source": "injected", "now": 1794822300}


def test_a_body_given_as_bytes_is_read_alike() -> None:
    service = TimeRouteService(InjectedTime(start=1794821400))

    assert service.set_time(b'{"now": 1794822300}') == {"source": "injected", "now": 1794822300}


def test_an_earlier_instant_is_refused_409_and_nothing_changes() -> None:
    source = InjectedTime(start=1794822300)
    service = TimeRouteService(source)

    with pytest.raises(TimeRouteError) as refused:
        service.set_time('{"now": 1794821400}')

    assert (refused.value.status_code, refused.value.code) == (409, "time_moves_forward")
    assert "1794822300" in refused.value.detail and "1794821400" in refused.value.detail
    assert source.now() == 1794822300


@pytest.mark.parametrize("body", [
    '{"now": true}',
    '{"now": 1794822300.5}',
    '{"now": "1794822300"}',
    '{"now": 253402300800}',
    '{}',
    '{"now": 1794822300, "source": "injected"}',
    'not json',
])
def test_an_invalid_body_is_refused_422_and_nothing_changes(body: str) -> None:
    source = InjectedTime(start=1794821400)
    service = TimeRouteService(source)

    with pytest.raises(TimeRouteError) as refused:
        service.set_time(body)

    assert (refused.value.status_code, refused.value.code) == (422, "invalid_time")
    assert source.now() == 1794821400


def test_the_status_of_a_wall_source_carries_no_instant() -> None:
    assert TimeRouteService(WallTime()).status() == {"source": "wall"}


def test_the_status_of_an_injected_source_carries_its_instant() -> None:
    assert TimeRouteService(InjectedTime(start=1794821400)).status() == {
        "source": "injected", "now": 1794821400}


def test_only_an_injected_source_this_process_sets_is_settable() -> None:
    assert TimeRouteService(InjectedTime(start=1794821400)).settable
    assert not TimeRouteService(WallTime()).settable
    assert not TimeRouteService(TimeFile("time.json")).settable
