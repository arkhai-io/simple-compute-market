"""The perceived clock moves forward only, and a reset returns it to wall time."""

from __future__ import annotations

import pytest

from lane_double_controls.clock import PerceivedClock

T0 = 1_800_000_000


class Clock:
    """An injected wall clock a test moves by hand."""

    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def test_with_no_offset_it_reads_wall_time() -> None:
    wall = Clock(T0)
    perceived = PerceivedClock(wall)

    assert perceived() == T0
    wall.now = T0 + 5
    assert perceived() == T0 + 5


def test_an_advance_adds_to_wall_time_and_accumulates() -> None:
    wall = Clock(T0)
    perceived = PerceivedClock(wall)

    perceived.advance(3_600)
    perceived.advance(60)

    assert (perceived(), perceived.offset) == (T0 + 3_660, 3_660)
    wall.now = T0 + 1
    assert perceived() == T0 + 3_661


@pytest.mark.parametrize("seconds", [0, -1])
def test_the_clock_never_moves_back_by_an_advance(seconds: int) -> None:
    perceived = PerceivedClock(Clock(T0))
    perceived.advance(60)

    with pytest.raises(ValueError):
        perceived.advance(seconds)
    assert perceived.offset == 60


def test_a_reset_returns_to_wall_time() -> None:
    wall = Clock(T0)
    perceived = PerceivedClock(wall)
    perceived.advance(86_400)

    perceived.reset()

    assert (perceived(), perceived.offset) == (T0, 0)
