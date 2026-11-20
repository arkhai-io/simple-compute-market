"""The Ansible job executor over a codec it knows nothing about.

The codec here is a stand-in: what the executor must do — render the plan,
run the playbook against the job's host under the codec's group, report the
handle, the codec's result, and redacted logs, classify failures, and leave no
file behind — holds for any domain's codec.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from compute_provisioning_contracts import CredentialEnvelope, ResultEnvelope
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from compute_provisioning.jobs import JobFailure, JobRun, JobSuccess
from cryptography.fernet import Fernet
from market_config import encrypt_secret

from compute_provisioning_ansible import (
    AnsibleJobExecutor,
    AnsibleJobInterpretation,
    AnsibleJobPlan,
    ProtectedKeyUnreadableError,
    SshConnectionCodec,
)
from compute_provisioning_ansible.runner import (
    AnsibleError,
    AnsibleResult,
    AnsibleRunner,
    MaterializedInventory,
)

_HOST = ExecutionHost(
    host_id="node-1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=3,
        public={
            "ssh_host": "10.0.0.1",
            "public_host": "203.0.113.1",
            "ssh_port": 22,
            "ssh_user": "root",
            "key_path": "/keys/id_ed25519",
        },
    ),
)


@dataclass
class _Codec:
    inventory_group: str = "test_nodes"
    secret_fields: frozenset[str] = frozenset({"token"})
    variables: dict = field(default_factory=lambda: {"host_id": "node-1", "token": "t0k"})
    extra_variables: dict = field(default_factory=dict)
    playbook_path: Path | None = None
    retryable: bool = True
    interpreted: list = field(default_factory=list)

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        return AnsibleJobPlan(
            variables=self.variables,
            extra_variables=self.extra_variables,
            limit=run.host.host_id,
            playbook_path=self.playbook_path,
        )

    def interpret(self, run, host, output) -> AnsibleJobInterpretation:
        self.interpreted.append((host, output))
        return AnsibleJobInterpretation(
            result=ResultEnvelope(
                offering_mode=run.offering_mode, result_kind="test_result", value={"ok": True}
            ),
            credentials=(
                CredentialEnvelope(
                    offering_mode=run.offering_mode, credential_kind="access", value={"k": "v"}
                ),
            ),
        )

    def is_retryable(self, message: str) -> bool:
        return self.retryable


def _runner(*, failure: Exception | None = None, seen: dict | None = None):
    runner = MagicMock()
    runner.write_inventory.return_value = MaterializedInventory(
        path=Path("/tmp/does-not-exist.ini")
    )
    runner.start_playbook.return_value = SimpleNamespace(process_id=4242)
    runner.execution_handle = AnsibleRunner.execution_handle

    async def wait(run, timeout_seconds, log_callback=None, redact=None):
        variables_path = runner.start_playbook.call_args.kwargs["extra_vars_path"]
        if seen is not None:
            seen["variables"] = yaml.safe_load(variables_path.read_text())
            seen["variables path"] = variables_path
        log_callback("token: t0k", "")
        if failure is not None:
            raise failure
        return AnsibleResult(stdout="token: t0k", stderr="", process_id=4242)

    runner.wait_for_playbook = wait
    return runner


def _run(*, events: list | None = None, **overrides) -> tuple[JobRun, list, list]:
    """A run whose reports are recorded; ``events`` receives ``"starting"``
    each time the executor reports its start."""
    handles: list = []
    logs: list = []
    events = [] if events is None else events
    values = dict(
        job_id="job-1",
        offering_mode="test",
        action="act",
        host=_HOST,
        parameters={"anything": "the codec reads"},
        report_starting=lambda: events.append("starting"),
        report_handle=handles.append,
        report_logs=logs.append,
    )
    values.update(overrides)
    return JobRun(**values), handles, logs


def _recording_start(runner, events: list) -> None:
    """Record ``"start_playbook"`` in ``events`` when the runner is asked to spawn."""
    spawned = runner.start_playbook.return_value

    def start(**kwargs):
        events.append("start_playbook")
        return spawned

    runner.start_playbook.side_effect = start


def _executor(runner, codec=None, **kwargs) -> AnsibleJobExecutor:
    return AnsibleJobExecutor(
        runner,
        codec or _Codec(),
        Path("/playbooks/default.yaml"),
        timeout_seconds=30,
        **kwargs,
    )


def test_a_successful_run_reports_the_codecs_result_and_redacted_logs() -> None:
    seen: dict = {}
    runner = _runner(seen=seen)
    codec = _Codec()
    run, handles, logs = _run()

    outcome = asyncio.run(_executor(runner, codec).execute(run))

    assert isinstance(outcome, JobSuccess)
    assert handles == [{"pid": 4242}]
    assert outcome.result.result_kind == "test_result"
    assert [c.credential_kind for c in outcome.credentials] == ["access"]
    assert logs and "t0k" not in logs[0]
    assert "t0k" not in outcome.logs
    # The codec interprets the raw output; only what is reported is redacted.
    host, output = codec.interpreted[0]
    assert (host.host_id, host.public_host) == ("node-1", "203.0.113.1")
    assert output.stdout == "token: t0k"
    assert seen["variables"] == codec.variables
    start = runner.start_playbook.call_args.kwargs
    assert start["playbook_path"] == Path("/playbooks/default.yaml")
    assert start["limit"] == "node-1"
    assert runner.write_inventory.call_args.kwargs["group"] == "test_nodes"
    assert runner.write_inventory.call_args.args[0][0].ssh_host == "10.0.0.1"


def test_the_start_is_reported_once_immediately_before_the_playbook_is_spawned() -> None:
    events: list = []
    runner = _runner()
    _recording_start(runner, events)
    run, _, _ = _run(events=events)

    asyncio.run(_executor(runner).execute(run))

    assert events == ["starting", "start_playbook"]


def test_a_start_that_cannot_be_recorded_spawns_nothing_and_leaves_no_file(
    tmp_path, monkeypatch
) -> None:
    """The job authority raises when it cannot record the start; the error
    leaves ``execute`` for the engine to record, and nothing was spawned."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    runner = _runner()

    def refuse() -> None:
        raise RuntimeError("start not recorded")

    run, _, _ = _run(report_starting=refuse)

    with pytest.raises(RuntimeError, match="start not recorded"):
        asyncio.run(_executor(runner).execute(run))

    runner.start_playbook.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_a_plan_may_name_its_own_playbook() -> None:
    runner = _runner()
    run, _, _ = _run()

    asyncio.run(_executor(runner, _Codec(playbook_path=Path("/custom.yaml"))).execute(run))

    assert runner.start_playbook.call_args.kwargs["playbook_path"] == Path("/custom.yaml")


@pytest.mark.parametrize(
    "message,codec_retryable,operator,retryable",
    [
        ("host UNREACHABLE", True, (), False),
        ("Permission denied (publickey)", True, (), False),
        ("disk quota exceeded", True, ("quota exceeded",), False),
        ("domain refused", False, (), False),
        ("connection reset", True, (), True),
    ],
    ids=["transport", "authentication", "operator", "codec", "retryable"],
)
def test_a_failure_is_classified(message, codec_retryable, operator, retryable) -> None:
    run, _, _ = _run()
    executor = _executor(
        _runner(failure=AnsibleError(message, stdout="token: x", stderr="")),
        _Codec(retryable=codec_retryable),
        additional_non_retryable_errors=operator,
    )

    outcome = asyncio.run(executor.execute(run))

    assert isinstance(outcome, JobFailure)
    assert outcome.error.message == message
    assert outcome.error.retryable is retryable
    assert "token: x" not in outcome.logs


def test_a_job_the_codec_refuses_to_prepare_records_no_start() -> None:
    """A codec refusing the job's parameters — its relay, say — raises from
    ``prepare``, before the start is reported."""
    events: list = []
    runner = _runner()
    codec = _Codec()

    def refuse(run):
        raise ValueError("relay 'site-a' holds no lease")

    codec.prepare = refuse
    run, _, _ = _run(events=events)

    with pytest.raises(ValueError, match="holds no lease"):
        asyncio.run(_executor(runner, codec).execute(run))
    runner.start_playbook.assert_not_called()
    assert events == []


def test_an_extra_variable_naming_a_job_variable_is_refused_before_anything_runs() -> None:
    """The variables file's refusal comes before the start, so no start is
    recorded."""
    events: list = []
    runner = _runner()
    run, _, _ = _run(events=events)
    codec = _Codec(extra_variables={"host_id": "elsewhere"})

    with pytest.raises(ValueError, match="host_id"):
        asyncio.run(_executor(runner, codec).execute(run))
    runner.start_playbook.assert_not_called()
    assert events == []


def test_a_host_reached_other_than_over_ssh_is_refused_before_anything_runs() -> None:
    events: list = []
    runner = _runner()
    run, _, _ = _run(
        events=events,
        host=ExecutionHost("node-1", "default", ConnectionEnvelope(kind="cloud_api", version=1)),
    )

    with pytest.raises(ValueError, match="over ssh"):
        asyncio.run(_executor(runner).execute(run))
    runner.start_playbook.assert_not_called()
    assert events == []


def test_cancel_stops_the_reported_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        asyncio.run(_executor(AnsibleRunner(SimpleNamespace())).cancel({"pid": process.pid}))
        assert process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.kill()


def test_cancelling_a_process_that_already_ended_is_not_an_error() -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)

    asyncio.run(_executor(AnsibleRunner(SimpleNamespace())).cancel({"pid": process.pid}))


@pytest.mark.parametrize("pid", [0, -1])
def test_a_process_group_is_never_signalled(pid, monkeypatch) -> None:
    """Zero and negative ids name process groups (zero is this service's own)."""
    signalled: list = []
    monkeypatch.setattr("os.kill", lambda *args: signalled.append(args))

    asyncio.run(_executor(AnsibleRunner(SimpleNamespace())).cancel({"pid": pid}))

    assert signalled == []


@pytest.mark.parametrize("ending", ["success", "failure", "timeout", "cancelled"])
def test_no_file_outlives_its_run(ending) -> None:
    """Whatever ends the run, the variables file, the decrypted key, and the
    inventory and known-hosts files are removed."""
    key = Fernet.generate_key().decode()
    seen: dict = {}
    runner = _runner(seen=seen)
    real_runner = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(key))

    def write_inventory(*args, **kwargs):
        inventory = real_runner.write_inventory(*args, **kwargs)
        (seen["known_hosts"],) = inventory.known_hosts_paths
        assert seen["known_hosts"].is_file()
        return inventory

    runner.write_inventory = write_inventory
    inner_wait = runner.wait_for_playbook

    async def wait(run, timeout_seconds, log_callback=None, redact=None):
        inventory_path = runner.start_playbook.call_args.kwargs["inventory_path"]
        reference = inventory_path.read_text().split("ansible_ssh_private_key_file=")[1]
        seen["inventory"] = inventory_path
        seen["key"] = Path(reference.split()[0])
        seen["key existed"] = seen["key"].exists()
        if ending == "failure":
            raise AnsibleError("boom", stdout="", stderr="")
        if ending == "timeout":
            raise AnsibleError("Playbook timed out", stdout="", stderr="")
        if ending == "cancelled":
            raise asyncio.CancelledError()
        return await inner_wait(run, timeout_seconds, log_callback, redact)

    runner.wait_for_playbook = wait
    host = ExecutionHost(
        host_id="node-1",
        pool_id="default",
        connection=ConnectionEnvelope(
            kind="ssh",
            version=3,
            public={"ssh_host": "10.0.1.1", "ssh_port": 22, "ssh_user": "ops", "key_path": None},
            protected={"private_key": ProtectedValue("fernet-v1", encrypt_secret("PEM", key))},
        ),
    )
    run, _, _ = _run(host=host)

    if ending == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_executor(runner).execute(run))
    else:
        asyncio.run(_executor(runner).execute(run))

    assert seen["key existed"]
    assert not seen["key"].exists()
    assert not seen["inventory"].exists()
    assert not seen["known_hosts"].exists()
    variables_path = runner.start_playbook.call_args.kwargs["extra_vars_path"]
    assert not variables_path.exists()


def test_a_key_that_cannot_be_decrypted_fails_the_run_naming_the_host(
    tmp_path, monkeypatch
) -> None:
    """The typed error leaves ``execute`` for the job engine to record, before
    any playbook starts, and nothing the run wrote remains. Both keys are
    generated for this test and protect nothing real."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    configured, other = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    runner = _runner()
    runner.write_inventory = AnsibleRunner(
        SimpleNamespace(), ssh_codec=SshConnectionCodec(configured)
    ).write_inventory
    ciphertext = encrypt_secret("PEM", other)
    host = ExecutionHost(
        host_id="node-1",
        pool_id="default",
        connection=ConnectionEnvelope(
            kind="ssh",
            version=3,
            public={"ssh_host": "10.0.1.1", "ssh_port": 22, "ssh_user": "ops", "key_path": None},
            protected={"private_key": ProtectedValue("fernet-v1", ciphertext)},
        ),
    )
    events: list = []
    run, _, _ = _run(host=host, events=events)

    with pytest.raises(ProtectedKeyUnreadableError) as raised:
        asyncio.run(_executor(runner).execute(run))

    assert raised.value.host_id == "node-1"
    assert ciphertext not in str(raised.value)
    runner.start_playbook.assert_not_called()
    # The inventory's refusal comes before the start, so none is recorded.
    assert events == []
    assert list(tmp_path.iterdir()) == []
