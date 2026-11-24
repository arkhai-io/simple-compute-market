"""A not-held part's reason, read from its signed amounts."""

from __future__ import annotations

import pytest

from mediation_lane_double.protection import not_held_reason


def _part(released: str = "0", reversed_: str = "0", refunded: str | None = None) -> dict:
    part = {"released": released, "reversed": reversed_}
    if refunded is not None:
        part["refunded"] = refunded
    return part


@pytest.mark.parametrize(("part", "reason"), [
    (_part(released="975"), "paid_out"),
    (_part(reversed_="1000"), "reversed"),
    (_part(released="475", reversed_="500"), "paid_out"),
    (_part(refunded="1000"), "reversed"),
    (_part(refunded="0"), "nothing_held"),
], ids=["released only", "reversed only", "released and reversed", "refunded only",
        "nothing moved"])
def test_the_reason_follows_what_moved(part: dict, reason: str) -> None:
    assert not_held_reason(part) == reason
