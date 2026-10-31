"""The real-host bare-metal deal's commands, teardown wait, and SSH judgement.

The scenario itself runs only against a real host. What it asks of the installed
buyer commands, of the harness's run binding, and of SSH is held here, at the
lowest level that proves each: the installed bare-metal contribution's own Typer
parser reads every argument list the scenario builds, without running a command.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

import click
import pytest
import typer

from tests.e2e.roles.buyer_cli import MarketRun, run_id_from_args
from tests.e2e.roles.helpers.bare_metal_access import (
    ACCESS_PROBE_OUTPUT,
    BUY_EVENTS,
    RECOVERY_COMMANDS,
    SshOutcome,
    assert_purchase_recorded,
    classify_ssh,
    recovery_command,
    ssh_command,
    wait_for_release,
)

_RUN_ID = "run-0000"


def _market_command() -> click.Command:
    """The ``market`` group as the installed bare-metal contribution registers it."""
    (registration,) = [
        item
        for item in entry_points(group="market.buyer_domains")
        if item.name == "bare-metal"
    ]
    root = typer.Typer()
    registration.load().buyer.register_commands(root)
    return typer.main.get_command(root)


def _parse(arguments: tuple[str, ...] | list[str]) -> click.Context:
    """Parse ``market <arguments>`` down to its leaf command, running nothing."""
    command = _market_command()
    remaining = list(arguments)
    while isinstance(command, click.Group):
        name, *remaining = remaining
        found = command.get_command(click.Context(command), name)
        if found is None:
            raise click.UsageError(f"no command {name!r}")
        command = found
    return command.make_context(command.name or "market", remaining)


@pytest.mark.parametrize("command", RECOVERY_COMMANDS)
def test_each_recovery_command_parses_under_the_installed_cli(command) -> None:
    arguments = recovery_command(command, _RUN_ID)

    context = _parse(arguments)

    assert arguments[:2] == ("bare-metal", command)
    assert context.params["run_id"] == _RUN_ID


@pytest.mark.parametrize(
    "arguments",
    [
        ("bare-metal", "result", "--from", _RUN_ID, "--json"),
        ("bare-metal", "access", "--from", _RUN_ID, "--json"),
        ("bare-metal", "teardown", "request", "--from", _RUN_ID, "--json"),
        ("bare-metal", "teardown", "status", "--run-id", _RUN_ID),
        ("bare-metal", "access", "--run-id", _RUN_ID, "--json"),
    ],
    ids=["result --from", "access --from", "teardown request", "teardown status", "--json"],
)
def test_the_forms_the_scenario_used_to_pass_are_refused(arguments) -> None:
    """These are what the scenario passed before; the command refuses each, so a
    regression to any of them fails here rather than on a real host."""
    with pytest.raises(click.UsageError):
        _parse(arguments)


def test_a_recovery_command_names_a_known_command_and_a_run() -> None:
    with pytest.raises(ValueError):
        recovery_command("status", _RUN_ID)
    with pytest.raises(ValueError):
        recovery_command("access", "")


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (("bare-metal", "teardown", "--run-id", _RUN_ID), _RUN_ID),
        (("bare-metal", "teardown", f"--run-id={_RUN_ID}"), _RUN_ID),
        (("settle", "--from", _RUN_ID), _RUN_ID),
        (("settle", f"--from={_RUN_ID}"), _RUN_ID),
        (("bare-metal", "buy", "listing-1"), None),
        (("bare-metal", "teardown", "--run-id="), None),
        (("bare-metal", "teardown", "--run-id"), None),
    ],
)
def test_a_command_is_bound_to_the_run_it_names(arguments, expected) -> None:
    assert run_id_from_args(arguments) == expected


def test_a_recovery_reads_the_run_buy_recorded_not_a_log_it_writes(tmp_path: Path) -> None:
    """``buy``'s run is the one log it added; a recovery naming that run reads it,
    even if another log appears beside it while the recovery runs."""
    run_dir = tmp_path / "arkhai" / "buy-runs"
    run_dir.mkdir(parents=True)
    (run_dir / "earlier.jsonl").write_text("")
    (run_dir / f"{_RUN_ID}.jsonl").write_text("")
    bought = MarketRun(run_dir=run_dir, pre_existing_run_ids=frozenset({"earlier"}))
    assert bought.run_id == _RUN_ID

    (run_dir / "later.jsonl").write_text("")
    recovery = MarketRun(
        run_dir=run_dir,
        pre_existing_run_ids=frozenset({"earlier", _RUN_ID}),
        _run_id=run_id_from_args(recovery_command("teardown", bought.run_id)),
    )
    assert recovery.run_id == _RUN_ID


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _scripted(*views: dict):
    calls = iter(views)
    issued: list[dict] = []

    def teardown() -> dict:
        view = next(calls)
        issued.append(view)
        return view

    return teardown, issued


def test_teardown_is_repeated_until_the_lease_is_released() -> None:
    clock = _Clock()
    teardown, issued = _scripted(
        {"state": "terminating"},
        {"state": "tearing_down"},
        {"state": "torn_down"},
        {"state": "released"},
    )

    view = wait_for_release(
        teardown,
        timeout_seconds=60,
        poll_interval_seconds=2,
        clock=clock,
        sleep=clock.sleep,
    )

    assert view == {"state": "released"}
    assert len(issued) == 4
    assert clock.slept == [2, 2, 2]


def test_a_failed_teardown_fails_at_once_naming_its_reason() -> None:
    clock = _Clock()
    teardown, issued = _scripted(
        {"state": "terminating"},
        {"state": "teardown_failed", "failure_reason": "reclaim job failed"},
        {"state": "released"},
    )

    with pytest.raises(AssertionError, match="teardown_failed.*reclaim job failed"):
        wait_for_release(
            teardown,
            timeout_seconds=60,
            poll_interval_seconds=2,
            clock=clock,
            sleep=clock.sleep,
        )
    assert len(issued) == 2


def test_a_teardown_that_never_releases_fails_at_its_bound_naming_the_last_state() -> None:
    clock = _Clock()

    with pytest.raises(AssertionError, match="within 6s; last state 'torn_down'"):
        wait_for_release(
            lambda: {"state": "torn_down"},
            timeout_seconds=6,
            poll_interval_seconds=2,
            clock=clock,
            sleep=clock.sleep,
        )
    assert clock.now == 6


# A documentation address, a synthetic tenant, and placeholder key paths: fixture
# values only, never a real host, account, or key.
_ACCESS = {"host": "192.0.2.10", "port": 22, "username": "tenant0000"}


def test_each_ssh_attempt_is_fresh_and_trusts_only_the_pinned_host_key() -> None:
    command = ssh_command(
        _ACCESS,
        private_key_file=Path("/keys/tenant"),
        known_hosts_file=Path("/pins/known_hosts"),
    )

    assert command[:3] == ["ssh", "-F", "none"]
    options = {command[i + 1] for i, part in enumerate(command) if part == "-o"}
    assert {
        "BatchMode=yes",
        "ControlMaster=no",
        "ControlPath=none",
        "IdentitiesOnly=yes",
        "IdentityAgent=none",
        "PreferredAuthentications=publickey",
        "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "StrictHostKeyChecking=yes",
        "UserKnownHostsFile=/pins/known_hosts",
        "GlobalKnownHostsFile=/dev/null",
        "UpdateHostKeys=no",
    } <= options
    assert not any("accept-new" in option for option in options)
    assert command[command.index("-i") + 1] == "/keys/tenant"
    assert command[command.index("-p") + 1] == "22"
    assert command[-2:] == ["tenant0000@192.0.2.10", f"printf {ACCESS_PROBE_OUTPUT}"]


def test_an_access_view_without_its_route_is_refused() -> None:
    with pytest.raises(AssertionError, match="omitted host or username"):
        ssh_command(
            {"port": 22},
            private_key_file=Path("/keys/tenant"),
            known_hosts_file=Path("/pins/known_hosts"),
        )


def test_access_is_accepted_only_with_the_probe_output() -> None:
    assert classify_ssh(0, ACCESS_PROBE_OUTPUT, "") is SshOutcome.ACCEPTED
    with pytest.raises(AssertionError):
        classify_ssh(0, "", "")


def test_only_the_hosts_refusal_of_the_key_is_revocation() -> None:
    refused = "tenant0000@192.0.2.10: Permission denied (publickey).\r\n"

    assert classify_ssh(255, "", refused) is SshOutcome.REFUSED


@pytest.mark.parametrize(
    "stderr",
    [
        "ssh: connect to host 192.0.2.10 port 22: Connection refused\r\n",
        "ssh: connect to host 192.0.2.10 port 22: Connection timed out\r\n",
        "ssh: connect to host 192.0.2.10 port 22: No route to host\r\n",
        "No ED25519 host key is known for 192.0.2.10 and you have requested strict "
        "checking.\r\nHost key verification failed.\r\n",
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\r\n"
        "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\r\n"
        "Host key verification failed.\r\n",
        "ssh: Could not resolve hostname tenant-host: Name or service not known\r\n",
    ],
    ids=["refused", "timed out", "unreachable", "unknown key", "changed key", "unresolved"],
)
def test_no_other_ssh_failure_counts_as_revocation(stderr) -> None:
    with pytest.raises(AssertionError, match="neither access nor revocation"):
        classify_ssh(255, "", stderr)


def _run(*names: str, status: str = "agreed") -> list[dict]:
    return [
        {"event": name, **({"status": status} if name == "run_ended" else {})}
        for name in names
    ]


def test_a_completed_purchase_is_what_buy_records() -> None:
    """The sequence the bare-metal buyer's run-log test pins on a real ``buy``."""
    assert BUY_EVENTS == ("run_started", "agreement_accepted", "payment_approved", "run_ended")
    assert_purchase_recorded(_run(*BUY_EVENTS))


@pytest.mark.parametrize(
    "events",
    [
        _run("run_started", "agreement_accepted", "run_ended"),
        _run(*BUY_EVENTS, status="exited"),
        _run("discover", "negotiation_completed", "settlement_submitted", "run_ended"),
        _run("run_started", "payment_approved", "agreement_accepted", "run_ended"),
    ],
    ids=["no approval", "exited", "another command's events", "out of order"],
)
def test_anything_else_is_not_a_completed_purchase(events) -> None:
    with pytest.raises(AssertionError):
        assert_purchase_recorded(events)
