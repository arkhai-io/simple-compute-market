"""The reversal following a stop whose time had passed: what the part still holds
beyond what a stop at that time would have earned under its partial-period rule."""

from __future__ import annotations

import pytest

from mediation_lane_double.service import stop_reversal_amount

START = 1_000_000
HOUR = 3_600


def _snapshot(*, earned: int, held: int, started: int | None = START) -> dict:
    part: dict = {"part": 0, "held": str(held), "rate": {"grossEarned": str(earned)}}
    if started is not None:
        part["started"] = started
    return {"parts": [part], "receipt": {"receipt": {"parts": [
        {"gross": "300", "rate": {"period": "PT1H", "periodsReserved": "3"}}]}}}


@pytest.mark.parametrize(("at", "rule", "earned", "held", "amount"), [
    (START + HOUR // 2, "returned", 200, 200, 200),
    (START + HOUR + 60, "returned", 200, 200, 100),
    (START + HOUR, "returned", 200, 200, 100),
    (START + HOUR // 2, "charged", 200, 200, 100),
    (START + HOUR // 4, "prorated", 200, 200, 175),
    (START + HOUR // 2, "returned", 200, 50, 50),
    (START + 2 * HOUR, "returned", 200, 200, 0),
    (START - 60, "returned", 200, 200, 200),
], ids=["returned, in the first period", "returned, in the second period",
        "at a boundary", "charged, the started period earned",
        "prorated, its elapsed share earned", "never more than is held",
        "nothing earned since", "before the part started"])
def test_a_passed_stop_reverses_what_was_earned_beyond_a_stop_at_its_time(
    at: int, rule: str, earned: int, held: int, amount: int,
) -> None:
    assert stop_reversal_amount(_snapshot(earned=earned, held=held), 0, at, rule) == amount


def test_a_part_that_never_started_reverses_nothing() -> None:
    snapshot = _snapshot(earned=0, held=0, started=None)
    assert stop_reversal_amount(snapshot, 0, START, "returned") == 0
