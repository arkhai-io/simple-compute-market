"""Host identity checks through a fake external SSH executable."""

import asyncio
import sys
from base64 import b64encode
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobFailure, JobRun, JobSuccess
from compute_provisioning_contracts import ResultEnvelope

from compute_provisioning_ansible import AnsibleJobExecutor, AnsibleJobInterpretation, AnsibleJobPlan
from compute_provisioning_ansible.host_keys import key_fingerprint
from compute_provisioning_ansible.runner import AnsibleResult, AnsibleRunner

_HOST = ExecutionHost(
    "fixture-node", "default",
    ConnectionEnvelope("ssh", 3, public={"ssh_host": "192.0.2.1", "key_path": "/fixture/id"}),
)


class _Codec:
    inventory_group = "test_nodes"
    secret_fields: frozenset[str] = frozenset()

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        return AnsibleJobPlan(variables={}, limit=run.host.host_id)

    def interpret(self, run, host, output) -> AnsibleJobInterpretation:
        return AnsibleJobInterpretation(result=ResultEnvelope(
            offering_mode=run.offering_mode, result_kind="test_result", value={"ok": True},
        ))


def _run(*, host: ExecutionHost, events: list[str]) -> JobRun:
    return JobRun(
        job_id="fixture-job", offering_mode="test", action="act", host=host, parameters={},
        report_starting=lambda: events.append("starting"),
        report_handle=lambda _handle: None,
        report_logs=lambda _logs: None,
    )


def _executor(runner, **options) -> AnsibleJobExecutor:
    return AnsibleJobExecutor(runner, _Codec(), Path("/fixture/playbook"), timeout_seconds=2, **options)


def _fixture_pin(byte: bytes) -> str:
    # Public test fixture only. No private key exists for this value.
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + byte * 32
    return "ssh-ed25519 " + b64encode(blob).decode("ascii")


def _execution_host_with_pin(pin: str | None, *, pending: bool = False) -> ExecutionHost:
    public = dict(_HOST.connection.public)
    if pin is not None:
        public["host_keys"] = [pin]
    return ExecutionHost(
        _HOST.host_id,
        _HOST.pool_id,
        ConnectionEnvelope(kind="ssh", version=3, public=public),
        host_key_adoption_pending=pending,
    )


def _do_not_spawn(runner, monkeypatch):
    start = MagicMock(side_effect=AssertionError("a refused job must not start a playbook"))
    monkeypatch.setattr(runner, "start_playbook", start)
    return start


def test_a_new_unpinned_host_does_not_connect(tmp_path, monkeypatch):
    runner = AnsibleRunner(SimpleNamespace())
    ssh_log = _ssh_fixture(tmp_path, monkeypatch, _fixture_pin(b"a"))
    start = _do_not_spawn(runner, monkeypatch)
    events: list = []
    run = _run(host=_execution_host_with_pin(None), events=events)

    outcome = asyncio.run(_executor(runner).execute(run))

    assert isinstance(outcome, JobFailure)
    assert outcome.error.code == "host_key_refused" and not outcome.error.retryable
    assert "pinned: none" in outcome.error.message
    assert "presented: unavailable" in outcome.error.message
    assert events == []
    assert not ssh_log.exists()
    start.assert_not_called()


def test_a_mismatched_host_reports_only_fingerprints_and_records_no_start(tmp_path, monkeypatch):
    command = tmp_path / "ssh"
    presented = _fixture_pin(b"b")
    command.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' 'debug1: Server host key: {key_fingerprint(presented)}' >&2\n"
        f"printf '%s\\n' 'fixture diagnostic: {presented}' >&2\n"
        "exit 255\n"
    )
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    runner = AnsibleRunner(SimpleNamespace())
    start = _do_not_spawn(runner, monkeypatch)
    pinned = _fixture_pin(b"a")
    events: list = []
    run = _run(host=_execution_host_with_pin(pinned), events=events)

    outcome = asyncio.run(_executor(runner).execute(run))

    assert isinstance(outcome, JobFailure)
    assert outcome.error.code == "host_key_refused" and not outcome.error.retryable
    assert key_fingerprint(pinned) in outcome.error.message
    assert key_fingerprint(presented) in outcome.error.message
    assert pinned not in outcome.error.message and presented not in outcome.error.message
    assert not outcome.logs
    assert events == []
    start.assert_not_called()

def _ssh_fixture(tmp_path, monkeypatch, pin):
    command = tmp_path / "ssh"
    invocation_log = tmp_path / "ssh.log"
    command.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import os\n"
        "import sys\n"
        "options = dict(arg.split('=', 1) for arg in sys.argv[1:] if '=' in arg)\n"
        "with open(os.environ['SSH_FIXTURE_LOG'], 'a') as log:\n"
        "    print('StrictHostKeyChecking=' + options['StrictHostKeyChecking'], file=log)\n"
        "path = Path(options['UserKnownHostsFile'])\n"
        "if not path.stat().st_size:\n"
        f"    path.write_text(options['HostKeyAlias'] + ' ' + {pin!r} + '\\n')\n"
        f"print('debug1: Server host key: ' + {key_fingerprint(pin)!r}, file=sys.stderr)\n"
        "print('debug1: SSH2_MSG_NEWKEYS received', file=sys.stderr)\n"
        "raise SystemExit(255)\n"
    )
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("SSH_FIXTURE_LOG", str(invocation_log))
    return invocation_log


@pytest.mark.parametrize('pending', [False, True])
def test_job_checks_a_pinned_key_before_it_records_its_start(tmp_path, monkeypatch, pending):
    pinned = _fixture_pin(b"a")
    ssh_log = _ssh_fixture(tmp_path, monkeypatch, pinned)
    host = _execution_host_with_pin(None if pending else pinned, pending=pending)
    committed = _execution_host_with_pin(pinned)
    adopt = MagicMock(return_value=committed)
    runner = AnsibleRunner(SimpleNamespace())
    events: list[str] = []
    run = _run(host=host, events=events)
    written: list[Path] = []

    def start(**kwargs):
        assert events == ["starting"]
        expected = ["StrictHostKeyChecking=yes"]
        if pending:
            expected.insert(0, "StrictHostKeyChecking=accept-new")
        assert ssh_log.read_text().splitlines() == expected
        return SimpleNamespace(process_id=4242)

    write_inventory = runner.write_inventory

    def capture_inventory(*args, **kwargs):
        rendered = write_inventory(*args, **kwargs)
        written.extend(rendered.known_hosts_paths)
        assert all(pinned in path.read_text() for path in written)
        return rendered

    async def wait(*args, **kwargs):
        return AnsibleResult(stdout="", stderr="", process_id=4242)

    monkeypatch.setattr(runner, "start_playbook", start)
    monkeypatch.setattr(runner, "write_inventory", capture_inventory)
    monkeypatch.setattr(runner, "wait_for_playbook", wait)
    outcome = asyncio.run(_executor(runner, adopt_host_key=adopt).execute(run))

    if pending:
        adopt.assert_called_once_with(host, pinned)
    else:
        adopt.assert_not_called()
    assert isinstance(outcome, JobSuccess)
    assert all(not path.exists() for path in written)


def test_a_losing_adoption_stops_before_recording_a_start(tmp_path, monkeypatch):
    presented = _fixture_pin(b"a")
    ssh_log = _ssh_fixture(tmp_path, monkeypatch, presented)
    runner = AnsibleRunner(SimpleNamespace())
    start = _do_not_spawn(runner, monkeypatch)
    committed = _fixture_pin(b"b")
    adopt = MagicMock(return_value=_execution_host_with_pin(committed))
    events: list[str] = []
    run = _run(host=_execution_host_with_pin(None, pending=True), events=events)

    outcome = asyncio.run(_executor(runner, adopt_host_key=adopt).execute(run))

    assert isinstance(outcome, JobFailure)
    assert key_fingerprint(committed) in outcome.error.message
    assert key_fingerprint(presented) in outcome.error.message
    assert ssh_log.read_text().splitlines() == ["StrictHostKeyChecking=accept-new"]
    assert events == []
    start.assert_not_called()
