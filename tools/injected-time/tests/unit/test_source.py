"""The process source: wall by default, or injected, frozen and forward-only."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

import injected_time
from injected_time import (
    InjectedTime,
    InvalidTime,
    InvalidTimeSource,
    TimeMovesForward,
    WallTime,
    install,
    installed,
    source_for,
)


@pytest.fixture
def restored_source() -> Iterator[None]:
    """Whatever a test installs, the process source is as it was afterwards."""
    before = installed()
    yield
    install(before)


class FakeWall:
    """A wall clock a test moves, read in seconds as `time.time` is."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __call__(self) -> float:
        return self.seconds


def test_wall_reads_follow_the_wall_clock() -> None:
    before = int(time.time())
    read = WallTime().now()
    after = int(time.time())

    assert before <= read <= after
    assert isinstance(read, int)


def test_wall_reads_follow_every_move_of_the_wall_clock_in_whole_seconds() -> None:
    wall = FakeWall(1794821400.75)
    source = WallTime(wall)

    assert source.now() == 1794821400
    wall.seconds = 1794822300.2
    assert source.now() == 1794822300


def test_the_process_source_is_wall_time_until_another_is_installed() -> None:
    assert installed().name == "wall"
    before = int(time.time())
    assert before <= injected_time.now() <= int(time.time())


def test_an_injected_source_starts_at_the_wall_instant_it_was_made() -> None:
    before = int(time.time())
    source = InjectedTime()
    after = int(time.time())

    assert before <= source.now() <= after
    assert source.name == "injected"


def test_an_injected_source_starts_at_its_wall_instant_and_holds_it_while_the_wall_moves() -> None:
    wall = FakeWall(1794821400.5)
    source = InjectedTime(wall=wall)

    assert source.now() == 1794821400
    wall.seconds += 3600
    assert source.now() == 1794821400


def test_a_set_holds_until_the_next_set_while_the_wall_moves() -> None:
    wall = FakeWall(1794821400)
    source = InjectedTime(wall=wall)

    assert source.set(1794822300) == 1794822300
    wall.seconds += 86400
    assert source.now() == 1794822300
    source.set(1794823200)
    wall.seconds += 86400
    assert source.now() == 1794823200


def test_setting_the_current_instant_again_changes_nothing() -> None:
    source = InjectedTime(start=1794821400)

    assert source.set(1794821400) == 1794821400
    assert source.now() == 1794821400


def test_a_backward_set_is_refused_and_the_instant_is_unchanged() -> None:
    source = InjectedTime(start=1794822300)

    with pytest.raises(TimeMovesForward) as refused:
        source.set(1794821400)

    assert refused.value.code == "time_moves_forward"
    assert (refused.value.current, refused.value.requested) == (1794822300, 1794821400)
    assert "1794822300" in str(refused.value) and "1794821400" in str(refused.value)
    assert source.now() == 1794822300


def test_an_invalid_instant_is_refused_and_the_instant_is_unchanged() -> None:
    source = InjectedTime(start=1794821400)

    for value in (True, 1794822300.0, 253402300800):
        with pytest.raises(InvalidTime):
            source.set(value)  # type: ignore[arg-type]
    assert source.now() == 1794821400


def test_an_invalid_start_is_refused() -> None:
    with pytest.raises(InvalidTime):
        InjectedTime(start=-1)


@pytest.mark.parametrize(("value", "kind"), [("wall", WallTime), ("injected", InjectedTime)])
def test_a_configured_value_names_its_source(value: str, kind: type) -> None:
    assert isinstance(source_for(value, setting="time.source"), kind)


@pytest.mark.parametrize("value", ["injectd", "WALL", "", None, 1])
def test_any_other_configured_value_is_refused_naming_the_setting_and_the_value(
        value: object) -> None:
    with pytest.raises(InvalidTimeSource) as refused:
        source_for(value, setting="[Time] source")

    assert "[Time] source" in str(refused.value)
    assert repr(value) in str(refused.value)
    assert (refused.value.setting, refused.value.value) == ("[Time] source", value)


def test_the_installed_source_answers_every_read(restored_source: None) -> None:
    source = install(InjectedTime(start=1794821400))

    assert installed() is source
    assert injected_time.now() == 1794821400
    source.set(1794822300)
    assert injected_time.now() == 1794822300


def test_installing_from_a_configured_value(restored_source: None) -> None:
    install(source_for("injected", setting="time.source"))

    assert installed().name == "injected"
