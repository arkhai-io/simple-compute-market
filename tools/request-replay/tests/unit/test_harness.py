"""The double-dispatch harness over a toy application.

The toy holds one value per resource. ``raise_to`` sets it to at least the
requested value and answers the value now held, so its domain recognises an old
request as applied; ``set_to`` sets it outright and answers what it set, so an old
retry re-asserts its value over a later write.
"""

from __future__ import annotations

import asyncio

import pytest

from request_replay.harness import (
    DoubleDispatchCase,
    DoubleDispatchFailure,
    assert_complete,
    run_double_dispatch,
)


class Toy:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def raise_to(self, resource: str, value: int) -> int:
        self.values[resource] = max(self.values.get(resource, 0), value)
        return self.values[resource]

    async def set_to(self, resource: str, value: int) -> int:
        self.values[resource] = value
        return value

    async def read(self, resource: str) -> int:
        return self.values.get(resource, 0)


def case(toy: Toy, operation: str) -> DoubleDispatchCase[int]:
    write = getattr(toy, operation)
    return DoubleDispatchCase(
        operation=operation,
        request=lambda: write("a", 5),
        later_write=lambda: write("a", 9),
        exact_retry=lambda: write("a", 5),
        current_answer=lambda: toy.read("a"),
    )


def test_a_convergent_route_passes() -> None:
    toy = Toy()

    asyncio.run(run_double_dispatch(case(toy, "raise_to"), snapshot=lambda: dict(toy.values)))

    assert toy.values == {"a": 9}


def test_an_absolute_setter_fails_on_the_state_its_retry_changed() -> None:
    toy = Toy()

    with pytest.raises(DoubleDispatchFailure, match="set_to: its exact retry after a later write changed"):
        asyncio.run(run_double_dispatch(case(toy, "set_to"), snapshot=lambda: dict(toy.values)))


def test_a_retry_answering_other_than_the_route_now_answers_fails() -> None:
    toy = Toy()
    stale = DoubleDispatchCase(
        operation="raise_to",
        request=lambda: toy.raise_to("a", 5),
        later_write=lambda: toy.raise_to("a", 9),
        exact_retry=lambda: asyncio.sleep(0, result=5),
        current_answer=lambda: toy.read("a"),
    )

    with pytest.raises(DoubleDispatchFailure, match="answered 5, while the route now answers 9"):
        asyncio.run(run_double_dispatch(stale, snapshot=lambda: dict(toy.values)))


def test_completeness_names_every_rerun_operation_with_no_case() -> None:
    toy = Toy()

    assert_complete(["raise_to"], [case(toy, "raise_to")])
    with pytest.raises(DoubleDispatchFailure, match="no double-dispatch case: read, set_to"):
        assert_complete(["raise_to", "set_to", "read"], [case(toy, "raise_to")])

