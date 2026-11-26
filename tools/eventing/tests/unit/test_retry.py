"""The retry policy's backoff."""

from __future__ import annotations

from datetime import timedelta

from eventing import RetryPolicy


def test_the_backoff_doubles_up_to_its_maximum() -> None:
    policy = RetryPolicy(initial=timedelta(seconds=10), maximum=timedelta(seconds=60))

    assert [policy.delay(n).total_seconds() for n in range(1, 6)] == [10, 20, 40, 60, 60]
