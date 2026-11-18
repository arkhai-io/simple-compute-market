"""The time control answers as the time component does, its refusals as control errors."""

from __future__ import annotations

import pytest

from injected_time import InjectedTime, WallTime
from lane_double_controls.models import ControlError, TimeView
from lane_double_controls.time_control import TimeControl

T0 = 1_794_821_400


def test_an_injected_source_is_settable_and_viewed_at_its_instant() -> None:
    control = TimeControl(InjectedTime(start=T0))

    assert control.settable
    assert control.view() == TimeView(source="injected", now=T0)


def test_a_wall_source_is_viewed_without_an_instant_and_is_not_settable() -> None:
    control = TimeControl(WallTime(wall=lambda: T0))

    assert not control.settable
    assert control.view() == TimeView(source="wall")


def test_a_setting_moves_the_source_and_answers_its_instant() -> None:
    source = InjectedTime(start=T0)
    control = TimeControl(source)

    answer = control.set_time(b'{"now": 1794825000}')

    assert answer == TimeView(source="injected", now=1_794_825_000)
    assert source.now() == 1_794_825_000


@pytest.mark.parametrize(("body", "status", "code"), [
    (b'{"now": 1794821399}', 409, "time_moves_forward"),
    (b'{"now": true}', 422, "invalid_time"),
    (b'{"seconds": 60}', 422, "invalid_time"),
    (b"not json", 422, "invalid_time"),
])
def test_a_refused_setting_is_a_control_error_and_changes_nothing(
        body: bytes, status: int, code: str) -> None:
    source = InjectedTime(start=T0)

    with pytest.raises(ControlError) as refused:
        TimeControl(source).set_time(body)

    assert (refused.value.status, refused.value.code) == (status, code)
    assert refused.value.body()["message"]
    assert source.now() == T0
