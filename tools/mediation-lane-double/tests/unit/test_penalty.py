"""A penalty's reversals: what the parts hold, in mandate order, up to the penalty."""

from __future__ import annotations

import pytest

from mediation_lane_double.service import penalty_reversals


@pytest.mark.parametrize(("amount", "held", "reversals"), [
    (1000, [200, 300], [(0, 200), (1, 300)]),
    (250, [200, 300], [(0, 200), (1, 50)]),
    (150, [200, 300], [(0, 150)]),
    (200, [0, 300, 100], [(1, 200)]),
    (500, [0, 0], []),
], ids=["more than is held", "into a later part", "within the first part",
        "past a part holding nothing", "nothing held"])
def test_a_penalty_reverses_what_is_held_part_by_part_and_no_more(
    amount: int, held: list[int], reversals: list[tuple[int, int]],
) -> None:
    assert penalty_reversals(amount, held) == reversals
