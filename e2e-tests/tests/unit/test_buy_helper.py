"""`buy_to_ready` steps a background `market buy` and never leaves it running.

The helper's sequence runs here over a fake run and recording clients: the
buyer CLI that starts the run, the storefront's stage-event log and the buyer's
settle status, the mock provisioning job queue, and fulfillment convergence.
Its cleanup also runs once over a real child process standing in for the buy,
since reaping crosses the process boundary a fake run cannot.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.e2e.roles.buyer_cli import MarketRun
from tests.e2e.roles.helpers.buy import buy_to_ready

ESCROW = "escrow-1"
NEGOTIATION = "negotiation-agreed"
FULFILLMENT = "fulfillment-1"
BUY_ARGS = ("--resource", 'gpu_model="RTX 4090"', "--yes")


class FakeRun:
    """A background `market buy`: its run-log events, and the events each wait
    finds. A wait for an event in ``missing`` fails as the real wait does when
    its bound passes or the process exits without it."""

    def __init__(self, calls: list, *, terminal: dict, missing: frozenset[str] = frozenset(),
                 exited: bool = False) -> None:
        self.calls = calls
        self.answers = {
            "escrow_created": {"event": "escrow_created", "escrow_uid": ESCROW},
            "settlement_submitted": {"event": "settlement_submitted", "escrow_uid": ESCROW},
            "run_ended": terminal,
        }
        self.missing = missing
        self.exited = exited
        self.terminations = 0
        self.run_id = "run-1"

    def events_or_empty(self) -> list[dict]:
        return [
            {"event": "negotiation_completed", "status": "rejected", "negotiation_id": "negotiation-earlier"},
            {"event": "negotiation_completed", "status": "agreed", "negotiation_id": NEGOTIATION},
            self.answers["escrow_created"],
        ]

    def wait_for_event(self, name: str, *, timeout: float) -> dict:
        self.calls.append(("wait_for_event", name))
        if name in self.missing:
            raise AssertionError(f"Did not see event {name!r} within {timeout}s")
        return self.answers[name]

    def wait(self, timeout: float) -> int:
        self.calls.append(("exit",))
        self.exited = True
        return 0

    def terminate(self) -> None:
        self.calls.append(("terminate",))
        self.terminations += 1
        self.exited = True

    def stdout(self) -> str:
        return "buy stdout"

    def stderr(self) -> str:
        return "buy stderr"


class FakeBuyerCli:
    def __init__(self, run: FakeRun) -> None:
        self.run_handle = run

    def run(self, args, *, background: bool = False) -> FakeRun:
        self.run_handle.calls.append(("start", tuple(args), background))
        return self.run_handle


class FakeStorefrontAdmin:
    """The storefront's stage-event wait, which times out, as the typed
    client's does, when ``logged`` is false."""

    def __init__(self, calls: list, *, logged: bool = True) -> None:
        self.calls = calls
        self.logged = logged

    def wait_for_stage_event(self, stage, event, *, listing_id=None, negotiation_id=None,
                             since_id=0, timeout=30.0):
        self.calls.append(("stage_event", stage, event, negotiation_id))
        if not self.logged:
            raise TimeoutError(f"{stage}/{event} not seen within {timeout}s")
        return SimpleNamespace(stage=stage, event=event, negotiation_id=negotiation_id)


class FakeBuyerStorefront:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def get_settle_status(self, escrow_uid):
        self.calls.append(("settle_status", escrow_uid))
        return SimpleNamespace(status="provisioning", fulfillment_id=FULFILLMENT)


class FakeProvisioningTest:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def drain(self, *, timeout: float) -> dict:
        self.calls.append(("drain",))
        return {}


class FakeProvisioning:
    """Fulfillment convergence: one advance takes the fulfillment to ``active``,
    unless ``converges`` is false, when it stays ``dispatching``."""

    def __init__(self, calls: list, *, converges: bool = True) -> None:
        self.calls = calls
        self.converges = converges
        self.state = "dispatching"

    def get_fulfillment_status(self, fulfillment_id):
        state = self.state
        return SimpleNamespace(
            model_dump=lambda mode: {"fulfillment_id": fulfillment_id, "state": state}
        )

    def advance_fulfillment_convergence_cycle(self) -> None:
        self.calls.append(("advance",))
        if self.converges:
            self.state = "active"


def _buy(run: FakeRun, *, converges: bool = True, logged: bool = True):
    calls = run.calls
    return buy_to_ready(
        FakeBuyerCli(run),
        BUY_ARGS,
        storefront_admin_client=FakeStorefrontAdmin(calls, logged=logged),
        storefront_client=FakeBuyerStorefront(calls),
        provisioning_client=FakeProvisioning(calls, converges=converges),
        provisioning_test_client=FakeProvisioningTest(calls),
    )


def _ready() -> dict:
    return {"event": "run_ended", "status": "ready", "escrow_uid": ESCROW,
            "negotiation_id": NEGOTIATION}


def test_a_buy_is_stepped_in_order_and_returns_its_terminal_event():
    calls: list = []
    run = FakeRun(calls, terminal=_ready())

    returned, terminal = _buy(run)

    assert returned is run
    assert terminal == _ready()
    assert calls == [
        ("start", ("buy", *BUY_ARGS), True),
        ("wait_for_event", "escrow_created"),
        ("wait_for_event", "settlement_submitted"),
        ("stage_event", "provision", "job_submitted", NEGOTIATION),
        ("settle_status", ESCROW),
        ("drain",),
        ("advance",),
        ("wait_for_event", "run_ended"),
        ("exit",),
    ]
    assert run.terminations == 0


def test_a_missing_settlement_submitted_event_names_its_step_and_terminates_once():
    calls: list = []
    run = FakeRun(calls, terminal=_ready(), missing=frozenset({"settlement_submitted"}))

    with pytest.raises(AssertionError, match="stalled at the run-log's settlement_submitted event") as raised:
        _buy(run)

    assert "negotiation_id='negotiation-agreed'" in str(raised.value)
    assert ("stage_event", "provision", "job_submitted", NEGOTIATION) not in calls
    assert run.terminations == 1


def test_a_dispatch_the_storefront_never_logs_names_its_step_and_terminates_once():
    calls: list = []
    run = FakeRun(calls, terminal=_ready())

    with pytest.raises(AssertionError, match="stalled at the storefront's provision/job_submitted event"):
        _buy(run, logged=False)

    assert ("settle_status", ESCROW) not in calls
    assert run.terminations == 1


def test_a_failed_advance_names_its_step_and_terminates_once():
    calls: list = []
    run = FakeRun(calls, terminal=_ready())

    with pytest.raises(AssertionError, match=f"stalled at advancing fulfillment {FULFILLMENT} to active"):
        _buy(run, converges=False)

    assert ("wait_for_event", "run_ended") not in calls
    assert run.terminations == 1


def test_a_buy_ending_other_than_ready_names_its_step_and_terminates_once():
    calls: list = []
    run = FakeRun(calls, terminal={"event": "run_ended", "status": "timeout", "reason": "polls exhausted"})

    with pytest.raises(AssertionError, match="stalled at the run-log's run_ended event with status ready") as raised:
        _buy(run)

    assert "'timeout'" in str(raised.value)
    assert run.terminations == 1


def test_a_buy_that_ended_is_not_terminated_again():
    calls: list = []
    run = FakeRun(
        calls, terminal={"event": "run_ended", "status": "exited", "reason": "no agreement"}, exited=True,
    )

    with pytest.raises(AssertionError, match="run_ended event with status ready") as raised:
        _buy(run)

    assert "stdout (tail): buy stdout" in str(raised.value)
    assert run.terminations == 0


class RealBuyerCli:
    """Starts a real child interpreter in place of `market buy`: it ignores
    SIGTERM, writes the run-log events of a buy that submitted its settlement,
    and then sleeps, as a buy polling a settlement no one steps does."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.started: list[subprocess.Popen] = []

    def run(self, args, *, background: bool = False) -> MarketRun:
        assert background
        events = [
            {"event": "negotiation_completed", "status": "agreed", "negotiation_id": NEGOTIATION},
            {"event": "escrow_created", "escrow_uid": ESCROW},
            {"event": "settlement_submitted", "escrow_uid": ESCROW},
        ]
        # The handler is installed before any event is written, and the helper
        # terminates only after reading them, so SIGTERM always meets it.
        script = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as log:\n"
            "    log.write(sys.argv[2])\n"
            "time.sleep(600)\n"
        )
        popen = subprocess.Popen(
            [sys.executable, "-c", script, str(self.run_dir / "run-1.jsonl"),
             "".join(json.dumps(event) + "\n" for event in events)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.started.append(popen)
        return MarketRun(run_dir=self.run_dir, popen=popen)


def test_a_failed_buy_kills_and_reaps_a_process_that_ignores_sigterm(tmp_path: Path):
    calls: list = []
    cli = RealBuyerCli(tmp_path)
    try:
        with pytest.raises(AssertionError, match="stalled at the storefront's provision/job_submitted event"):
            buy_to_ready(
                cli,
                BUY_ARGS,
                storefront_admin_client=FakeStorefrontAdmin(calls, logged=False),
                storefront_client=FakeBuyerStorefront(calls),
                provisioning_client=FakeProvisioning(calls),
                provisioning_test_client=FakeProvisioningTest(calls),
            )

        (process,) = cli.started
        # `returncode` is set only once the child is reaped, and SIGKILL is the
        # only signal this child does not survive.
        assert process.returncode == -signal.SIGKILL
    finally:
        for process in cli.started:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
