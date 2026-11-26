"""The double-dispatch harness: proving a re-run route's exact retry changes nothing.

A route may resolve an exact retry by running again only where its domain
recognises the retry as already applied, so that a re-run after any later write to
the same resource changes nothing, and its answer still tells the caller what
happened. Idempotence is not enough: an absolute setter is idempotent against
itself, but a delayed retry of it re-asserts an old value over a newer one. So a
case is the request, then a later write to the same resource, then the request's
exact retry; the harness asserts the state after the retry equals the state before
it, and that the retry's answer is the route's current answer.

The harness drives whatever the caller supplies -- a real application through its
client, a real database -- and depends on no test framework: a failure is an
:class:`AssertionError`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

AnswerT = TypeVar("AnswerT")


class DoubleDispatchFailure(AssertionError):
    """A re-run route's exact retry changed state, or answered other than now."""


@dataclass(frozen=True)
class DoubleDispatchCase(Generic[AnswerT]):
    """One re-run operation's proof.

    ``request`` sends the request and answers what the caller received;
    ``later_write`` writes the same resource afterwards; ``exact_retry`` re-sends
    the first request exactly, re-signed where the caller signs, and answers
    what it received; ``current_answer`` answers what the route answers now, for
    comparison. Answers are compared as returned, so each callable returns only
    what the route's answer means -- not a signature or a send time.
    """

    operation: str
    request: Callable[[], Awaitable[AnswerT]]
    later_write: Callable[[], Awaitable[object]]
    exact_retry: Callable[[], Awaitable[AnswerT]]
    current_answer: Callable[[], Awaitable[AnswerT]]


async def run_double_dispatch(case: DoubleDispatchCase[AnswerT], *, snapshot: Callable[[], object]) -> None:
    """Run ``case``, comparing ``snapshot()`` of the state around its retry.

    ``snapshot`` reads the state the operation writes, excluding the replay
    table, whose rows a retry legitimately touches.
    """

    await case.request()
    await case.later_write()
    before = snapshot()
    answer = await case.exact_retry()
    after = snapshot()
    if after != before:
        raise DoubleDispatchFailure(
            f"{case.operation}: its exact retry after a later write changed the state\n"
            f"before the retry: {before!r}\nafter the retry:  {after!r}"
        )
    current = await case.current_answer()
    if answer != current:
        raise DoubleDispatchFailure(
            f"{case.operation}: its exact retry answered {answer!r}, "
            f"while the route now answers {current!r}"
        )


def assert_complete(rerun_operations: Iterable[str], cases: Iterable[DoubleDispatchCase[Any]]) -> None:
    """Fail naming every re-run operation no case proves."""

    covered = {case.operation for case in cases}
    missing = sorted(set(rerun_operations) - covered)
    if missing:
        raise DoubleDispatchFailure(
            "re-run operations with no double-dispatch case: " + ", ".join(missing)
        )


def sqlite_snapshot(
    connection: sqlite3.Connection, *, exclude: Collection[str] = ()
) -> dict[str, list[tuple[Any, ...]]]:
    """Every table's rows but those excluded, each table's rows in a fixed order."""

    names = sorted(
        str(name)
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        if name not in exclude
    )
    return {
        name: sorted((tuple(row) for row in connection.execute(f'SELECT * FROM "{name}"')), key=repr)
        for name in names
    }
