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
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from compute_provisioning.contracts import CredentialEnvelope, ResultEnvelope
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from compute_provisioning.jobs import JobFailure, JobRun, JobSuccess
from cryptography.fernet import Fernet
from market_config import encrypt_secret

from compute_provisioning_ansible import (
    AnsibleJobExecutor,
    AnsibleJobInterpretation,
    AnsibleJobPlan,
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
        version=1,
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


def _run(**overrides) -> tuple[JobRun, list, list]:
    handles: list = []
    logs: list = []
    values = dict(
        job_id="job-1",
        offering_mode="test",
        action="act",
        host=_HOST,
        parameters={"anything": "the codec reads"},
        report_handle=handles.append,
        report_logs=logs.append,
    )
    values.update(overrides)
    return JobRun(**values), handles, logs


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
        non_retryable_errors=operator,
    )

    outcome = asyncio.run(executor.execute(run))

    assert isinstance(outcome, JobFailure)
    assert outcome.error.message == message
    assert outcome.error.retryable is retryable
    assert "token: x" not in outcome.logs


def test_an_extra_variable_naming_a_job_variable_is_refused_before_anything_runs() -> None:
    runner = _runner()
    run, _, _ = _run()
    codec = _Codec(extra_variables={"host_id": "elsewhere"})

    with pytest.raises(ValueError, match="host_id"):
        asyncio.run(_executor(runner, codec).execute(run))
    runner.start_playbook.assert_not_called()


def test_a_host_reached_other_than_over_ssh_is_refused_before_anything_runs() -> None:
    runner = _runner()
    run, _, _ = _run(
        host=ExecutionHost("node-1", "default", ConnectionEnvelope(kind="cloud_api", version=1))
    )

    with pytest.raises(ValueError, match="over ssh"):
        asyncio.run(_executor(runner).execute(run))
    runner.start_playbook.assert_not_called()


def test_cancel_stops_the_reported_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        asyncio.run(_executor(_runner()).cancel({"pid": process.pid}))
        assert process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.kill()


def test_cancelling_a_process_that_already_ended_is_not_an_error() -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)

    asyncio.run(_executor(_runner()).cancel({"pid": process.pid}))


@pytest.mark.parametrize("ending", ["success", "failure", "timeout", "cancelled"])
def test_no_file_outlives_its_run(ending) -> None:
    """Whatever ends the run, the variables file, the decrypted key, and the
    inventory are removed."""
    key = Fernet.generate_key().decode()
    seen: dict = {}
    runner = _runner(seen=seen)
    runner.write_inventory = AnsibleRunner(
        SimpleNamespace(), ssh_codec=SshConnectionCodec(key)
    ).write_inventory
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
            version=1,
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
    variables_path = runner.start_playbook.call_args.kwargs["extra_vars_path"]
    assert not variables_path.exists()
