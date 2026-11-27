"""The runner's spawn and cancellation over real processes.

A process here stands in for ``ansible-playbook``: the runner's handling of a
spawn that fails, and of a run cancelled while its wait watches it or outside
any wait, does not depend on what the process runs.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from compute_provisioning_ansible.runner import AnsibleError, AnsibleRun, AnsibleRunner


def test_a_playbook_that_cannot_be_spawned_leaves_no_records_file(tmp_path, monkeypatch) -> None:
    """No ``ansible-playbook`` on the path: the spawn fails and its file goes."""
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    with pytest.raises(FileNotFoundError):
        AnsibleRunner(SimpleNamespace()).start_playbook(
            Path("p.yml"), Path("i.ini"), tmp_path / "v.yml", "node-1"
        )

    assert list(temporary.iterdir()) == []


_EXITS_ON_TERM = (
    "import signal, sys\n"
    "signal.signal(signal.SIGTERM, lambda *_: sys.exit({code}))\n"
    "print('ready', flush=True)\n"
    "sys.stdin.read()\n"
)


def _process_run(tmp_path, *, exit_on_term: int) -> AnsibleRun:
    """A run over a process that blocks until signalled, then exits with
    ``exit_on_term``; it stands in for a playbook, and records nothing. It is
    returned once the process says its handler is installed."""
    process = subprocess.Popen(
        [sys.executable, "-c", _EXITS_ON_TERM.format(code=exit_on_term)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout.readline() == "ready\n"
    variables = tmp_path / "vars.yml"
    variables.write_text("{}\n")
    return AnsibleRun(process=process, process_id=process.pid, vars_path=variables)


async def test_a_run_that_exits_successfully_when_cancelled_is_a_success(tmp_path) -> None:
    runner = AnsibleRunner(SimpleNamespace())
    run = _process_run(tmp_path, exit_on_term=0)
    try:
        waiting = asyncio.ensure_future(runner.wait_for_playbook(run, timeout_seconds=30))
        await asyncio.sleep(0)
        await runner.cancel(runner.execution_handle(run))

        result = await asyncio.wait_for(waiting, timeout=30)
    finally:
        run.process.kill()
        run.process.wait()

    assert result.process_id == run.process_id


async def test_a_cancel_reaching_a_process_no_wait_watches_marks_nothing(tmp_path) -> None:
    """Only a run being waited on is marked cancelled, so the pid of a process
    signalled outside any wait is never taken for a cancelled run later."""
    runner = AnsibleRunner(SimpleNamespace())
    run = _process_run(tmp_path, exit_on_term=3)
    try:
        await runner.cancel(runner.execution_handle(run))
        run.process.wait(timeout=30)

        with pytest.raises(AnsibleError) as raised:
            await runner.wait_for_playbook(run, timeout_seconds=30)
    finally:
        if run.process.poll() is None:
            run.process.kill()
            run.process.wait()

    assert (raised.value.outcome, raised.value.returncode) == ("failed", 3)
