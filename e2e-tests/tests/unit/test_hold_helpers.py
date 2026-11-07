"""The module-hold helpers, against fake service clients.

A hold waits until every held loop reports itself at its gate, and resumes in a
``finally`` that covers the wait as well as the module, so neither a failing
stage nor a hold that never reached its gate leaves a shared service paused.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.e2e.roles.helpers import compute_deal


class _Storefront:
    """An admin client whose lifecycle pause answers ``answers`` in turn."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.pauses = 0
        self.resumes = 0
        self.lifecycle: dict = {}

    def admin_pause_lifecycle_loops(self):
        self.pauses += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def admin_resume_lifecycle_loops(self):
        self.resumes += 1

    def get_system_status(self):
        return SimpleNamespace(lifecycle=self.lifecycle)


class _Provisioning:
    def __init__(self, pause_error: Exception | None = None, lease_watchdog: str = "paused"):
        self.pause_error = pause_error
        self.resumes = 0
        self.lease_watchdog = lease_watchdog

    def pause_lease_watchdog(self):
        if self.pause_error is not None:
            raise self.pause_error
        return SimpleNamespace(paused=True, at_gate=True)

    def resume_lease_watchdog(self):
        self.resumes += 1

    def get_system_status(self):
        return SimpleNamespace(checks={"lease_watchdog": self.lease_watchdog})


_HELD = {"paused": True, "loops": {"site-projections": "paused", "publication": "paused"}}
_CYCLING = {"paused": True, "loops": {"site-projections": "paused", "publication": "running"}}


def test_a_hold_repeats_the_pause_until_every_loop_is_at_its_gate():
    pause = iter([_CYCLING, _CYCLING, _HELD]).__next__
    slept: list[float] = []

    answer = compute_deal._until_held(
        pause, compute_deal._storefront_loops_at_gate, "a loop", sleep=slept.append
    )

    assert answer == _HELD
    assert len(slept) == 2


def test_a_hold_that_never_reaches_its_gate_fails_by_its_deadline():
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(AssertionError, match="a loop did not reach its gate within 2s"):
        compute_deal._until_held(
            lambda: _CYCLING,
            compute_deal._storefront_loops_at_gate,
            "a loop",
            timeout=2,
            clock=lambda: now[0],
            sleep=sleep,
        )
    assert now[0] == pytest.approx(2.0)


def test_the_storefront_hold_resumes_after_a_failing_module():
    storefront = _Storefront(_HELD)

    with pytest.raises(RuntimeError, match="stage failed"):
        with compute_deal.storefront_loops_held(storefront) as held:
            assert held == _HELD
            assert storefront.resumes == 0
            raise RuntimeError("stage failed")

    assert storefront.resumes == 1


def test_a_hold_whose_pause_fails_still_resumes():
    storefront = _Storefront(RuntimeError("pause refused"))
    provisioning = _Provisioning(pause_error=RuntimeError("worker not composed"))

    with pytest.raises(RuntimeError, match="pause refused"):
        with compute_deal.storefront_loops_held(storefront):
            pytest.fail("the module ran without its hold")
    with pytest.raises(RuntimeError, match="worker not composed"):
        with compute_deal.lease_watchdog_held(provisioning):
            pytest.fail("the module ran without its hold")

    assert (storefront.resumes, provisioning.resumes) == (1, 1)


def test_a_storefront_reporting_its_loops_unpaused_fails_the_hold_and_resumes():
    storefront = _Storefront({"paused": False, "loops": {}})

    with pytest.raises(AssertionError, match="did not report its loops paused"):
        with compute_deal.storefront_loops_held(storefront):
            pytest.fail("the module ran without its hold")

    assert storefront.resumes == 1


def test_the_storefront_hold_reads_back_every_timed_loop_and_skips_steps():
    storefront = _Storefront(_HELD)
    storefront.lifecycle = {
        "publication": {"state": "paused"},
        "introduction-retention": {"state": None},
    }

    compute_deal.assert_storefront_loops_held(storefront)

    storefront.lifecycle["capacity"] = {"state": "running"}
    with pytest.raises(AssertionError, match="capacity"):
        compute_deal.assert_storefront_loops_held(storefront)


def test_the_lease_watchdog_hold_reads_back_through_system_status():
    compute_deal.assert_lease_watchdog_held(_Provisioning())

    with pytest.raises(AssertionError, match="'running'"):
        compute_deal.assert_lease_watchdog_held(_Provisioning(lease_watchdog="running"))
