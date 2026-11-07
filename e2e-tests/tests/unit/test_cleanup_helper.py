"""Scenario cleanup attempts every owned step and always resumes what it held."""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers.cleanup import CleanupFailed, run_cleanup


def _record(calls: list[str], name: str, error: BaseException | None = None):
    def step() -> None:
        calls.append(name)
        if error is not None:
            raise error

    return name, step


def test_a_failing_step_stops_neither_later_steps_nor_the_always_run_ones():
    calls: list[str] = []

    with pytest.raises(CleanupFailed) as failed:
        run_cleanup(
            [
                _record(calls, "refund", RuntimeError("payments unavailable")),
                _record(calls, "drain", TimeoutError("still draining")),
                _record(calls, "remove override"),
            ],
            always=[
                _record(calls, "resume watchdog", RuntimeError("refused")),
                _record(calls, "resume loops"),
            ],
        )

    assert calls == [
        "refund", "drain", "remove override", "resume watchdog", "resume loops",
    ]
    assert [name for name, _ in failed.value.failures] == [
        "refund", "drain", "resume watchdog",
    ]
    assert "payments unavailable" in str(failed.value)


def test_a_step_failed_through_pytest_does_not_stop_the_later_steps():
    calls: list[str] = []

    with pytest.raises(CleanupFailed) as failed:
        run_cleanup(
            [
                _record(calls, "release", pytest.fail.Exception("host not released")),
                _record(calls, "remove override"),
            ],
            always=[_record(calls, "resume loops")],
        )

    assert calls == ["release", "remove override", "resume loops"]
    assert [name for name, _ in failed.value.failures] == ["release"]


def test_a_clean_run_raises_nothing():
    calls: list[str] = []

    run_cleanup([_record(calls, "drain")], always=[_record(calls, "resume loops")])

    assert calls == ["drain", "resume loops"]


def test_an_interrupt_still_resumes_before_it_propagates():
    calls: list[str] = []

    with pytest.raises(KeyboardInterrupt):
        run_cleanup(
            [_record(calls, "drain", KeyboardInterrupt()), _record(calls, "remove override")],
            always=[_record(calls, "resume loops")],
        )

    assert calls == ["drain", "resume loops"]
