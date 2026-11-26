"""The runner's failure records through a real ``ansible-playbook`` run.

Each test runs the runner against a local target — the controller itself over
Ansible's ``local`` connection, or an SSH port nothing listens on — and asserts
the records the notification callback wrote reach the result or error the
runner hands back, and that the run's records file is gone afterwards.
"""

from __future__ import annotations

import asyncio
import os
import socket
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from compute_provisioning_ansible.runner import AnsibleError, AnsibleRunner


@pytest.fixture
def scratch(tmp_path, monkeypatch) -> Path:
    """The run's temporary files land in a directory of the test's own."""
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    return temporary


def _local_inventory(tmp_path: Path) -> Path:
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        "[nodes]\nnode-1 ansible_connection=local ansible_python_interpreter=auto_silent\n"
    )
    return inventory


def _playbook(tmp_path: Path, tasks: str) -> Path:
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        "- name: Operate\n  hosts: nodes\n  gather_facts: false\n  tasks:\n" + tasks
    )
    return playbook


async def _run(
    tmp_path: Path, inventory: Path, playbook: Path, *, timeout: int = 60, **wait
):
    runner = AnsibleRunner(SimpleNamespace())
    variables = tmp_path / "vars.yml"
    variables.write_text("{}\n")
    run = runner.start_playbook(playbook, inventory, variables, "node-1")
    assert run.failures_path is not None
    assert stat.S_IMODE(run.failures_path.stat().st_mode) == 0o600
    try:
        return run, await runner.wait_for_playbook(run, timeout_seconds=timeout, **wait)
    except AnsibleError as error:
        return run, error


def _assert_cleaned(run, scratch: Path) -> None:
    """The records file is gone, and so is the variables file the run was given."""
    assert not run.failures_path.exists()
    assert list(scratch.iterdir()) == []
    assert not run.vars_path.exists()


async def test_a_failing_task_is_recorded_on_the_error(tmp_path, scratch) -> None:
    playbook = _playbook(
        tmp_path,
        "    - name: Fail with output\n"
        "      ansible.builtin.shell: |\n"
        "        echo out; echo '{\"version\": 1}' >&2; exit 3\n"
        "      tags: [\"failure_class:example\"]\n",
    )

    run, error = await _run(tmp_path, _local_inventory(tmp_path), playbook)

    assert isinstance(error, AnsibleError)
    assert (error.outcome, error.returncode) == ("failed", 2)
    (record,) = error.failures
    assert (record.host, record.play, record.task) == ("node-1", "Operate", "Fail with output")
    assert record.module == "ansible.builtin.shell"
    assert record.rc == 3
    assert (record.stdout, record.stderr) == ("out", '{"version": 1}')
    assert record.failure_classes == ("example",)
    assert not (record.ignored or record.rescued or record.unreachable)
    _assert_cleaned(run, scratch)


async def test_a_failure_under_no_log_records_only_that_it_was_censored(
    tmp_path, scratch
) -> None:
    playbook = _playbook(
        tmp_path,
        "    - name: Fail quietly\n"
        "      ansible.builtin.shell: echo secret-value >&2; exit 1\n"
        "      no_log: true\n",
    )

    run, error = await _run(tmp_path, _local_inventory(tmp_path), playbook)

    (record,) = error.failures
    assert "no_log: true" in record.msg
    assert "secret-value" not in str(record.to_mapping())
    _assert_cleaned(run, scratch)


async def test_ignored_and_rescued_failures_are_recorded_on_a_successful_run(
    tmp_path, scratch
) -> None:
    playbook = _playbook(
        tmp_path,
        "    - name: Ignored\n"
        "      ansible.builtin.command: /bin/false\n"
        "      ignore_errors: true\n"
        "    - block:\n"
        "        - name: Rescued\n"
        "          ansible.builtin.fail:\n"
        "            msg: taken over\n"
        "      rescue:\n"
        "        - name: Recover\n"
        "          ansible.builtin.debug:\n"
        "            msg: recovered\n",
    )

    run, result = await _run(tmp_path, _local_inventory(tmp_path), playbook)

    assert not isinstance(result, AnsibleError)
    ignored, rescued = result.failures
    assert (ignored.task, ignored.ignored, ignored.rescued) == ("Ignored", True, False)
    assert (rescued.task, rescued.msg, rescued.rescued, rescued.ignored) == (
        "Rescued", "taken over", True, False,
    )
    _assert_cleaned(run, scratch)


async def test_a_failure_in_a_role_an_include_or_a_nested_block_is_recorded_as_such(
    tmp_path, scratch
) -> None:
    """Its role is named, a short module name is resolved, and a rescue that
    encloses the failure through an include or a nested block is seen."""
    tasks = tmp_path / "roles" / "access" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "main.yml").write_text(
        "- name: Fail in the role\n  command: /bin/false\n  ignore_errors: true\n"
    )
    (tmp_path / "included.yml").write_text(
        "- name: Fail in the include\n  ansible.builtin.fail:\n    msg: included\n"
    )
    playbook = _playbook(
        tmp_path,
        "    - ansible.builtin.include_role:\n"
        "        name: access\n"
        "    - block:\n"
        "        - ansible.builtin.include_tasks: included.yml\n"
        "      rescue:\n"
        "        - ansible.builtin.debug:\n"
        "            msg: recovered\n"
        "    - block:\n"
        "        - block:\n"
        "            - name: Fail in a nested block\n"
        "              ansible.builtin.fail:\n"
        "                msg: nested\n"
        "      rescue:\n"
        "        - ansible.builtin.debug:\n"
        "            msg: recovered\n",
    )

    run, result = await _run(tmp_path, _local_inventory(tmp_path), playbook)

    assert not isinstance(result, AnsibleError)
    in_role, included, nested = result.failures
    assert (in_role.task, in_role.role, in_role.module) == (
        "Fail in the role", "access", "ansible.builtin.command",
    )
    assert in_role.ignored
    assert (included.task, included.rescued) == ("Fail in the include", True)
    assert (nested.task, nested.rescued) == ("Fail in a nested block", True)
    _assert_cleaned(run, scratch)


async def test_an_unreachable_host_is_recorded(tmp_path, scratch) -> None:
    # A port bound and never listened on refuses the connection.
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        inventory = tmp_path / "inventory.ini"
        inventory.write_text(
            "[nodes]\nnode-1 ansible_host=127.0.0.1 "
            f"ansible_port={port} ansible_user=nobody ansible_connection=ssh "
            "ansible_ssh_common_args='-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null -o ConnectTimeout=5'\n"
        )
        playbook = _playbook(tmp_path, "    - name: Reach\n      ansible.builtin.ping:\n")

        run, error = await _run(tmp_path, inventory, playbook)

    assert isinstance(error, AnsibleError)
    (record,) = error.failures
    assert (record.task, record.unreachable, record.ignored) == ("Reach", True, False)
    assert record.msg
    _assert_cleaned(run, scratch)


async def test_an_operators_stdout_callback_does_not_change_the_records(
    tmp_path, scratch, monkeypatch
) -> None:
    config = tmp_path / "ansible.cfg"
    config.write_text(
        "[defaults]\nstdout_callback = minimal\ncallback_plugins = /nonexistent\n"
    )
    monkeypatch.setenv("ANSIBLE_CONFIG", str(config))
    playbook = _playbook(
        tmp_path,
        "    - name: Fail\n      ansible.builtin.fail:\n        msg: under another callback\n",
    )

    run, error = await _run(tmp_path, _local_inventory(tmp_path), playbook)

    assert isinstance(error, AnsibleError)
    (record,) = error.failures
    assert (record.task, record.msg, record.module) == (
        "Fail", "under another callback", "ansible.builtin.fail",
    )
    # The minimal callback prints a result as ``host | FAILED! => {...}``.
    assert "node-1 | FAILED!" in error.stdout
    _assert_cleaned(run, scratch)


async def test_a_run_cancelled_through_its_handle_keeps_what_it_recorded(
    tmp_path, scratch
) -> None:
    """The playbook's second task reads a FIFO: the test's open for writing
    returns exactly when that task opens it, so the first task's record is
    written, and the task then blocks until the test closes its end."""
    gate = tmp_path / "gate"
    os.mkfifo(gate)
    playbook = _playbook(
        tmp_path,
        "    - name: Ignored\n"
        "      ansible.builtin.command: /bin/false\n"
        "      ignore_errors: true\n"
        "    - name: Wait at the gate\n"
        f"      ansible.builtin.command: cat {gate}\n",
    )
    runner = AnsibleRunner(SimpleNamespace())
    variables = tmp_path / "vars.yml"
    variables.write_text("{}\n")
    run = runner.start_playbook(playbook, _local_inventory(tmp_path), variables, "node-1")
    assert stat.S_IMODE(run.failures_path.stat().st_mode) == 0o600
    waiting = asyncio.ensure_future(runner.wait_for_playbook(run, timeout_seconds=120))
    writer = await asyncio.wait_for(asyncio.to_thread(open, gate, "w"), timeout=60)
    try:
        await runner.cancel(runner.execution_handle(run))
        with pytest.raises(AnsibleError) as raised:
            await asyncio.wait_for(waiting, timeout=60)
    finally:
        writer.close()

    assert raised.value.outcome == "cancelled"
    (record,) = raised.value.failures
    assert (record.task, record.ignored) == ("Ignored", True)
    _assert_cleaned(run, scratch)


async def test_a_run_past_its_timeout_is_killed_and_leaves_no_records_file(
    tmp_path, scratch
) -> None:
    """The one test spending real time: the runner's timeout is a real wait.

    Killing ``ansible-playbook`` does not stop a task it already forked, so the
    task waits only a few seconds, outliving the test by no more.
    """
    playbook = _playbook(tmp_path, "    - name: Wait\n      ansible.builtin.command: sleep 3\n")

    run, error = await _run(tmp_path, _local_inventory(tmp_path), playbook, timeout=1)

    assert isinstance(error, AnsibleError)
    assert error.outcome == "timed_out"
    assert run.process.poll() is not None
    _assert_cleaned(run, scratch)


async def test_a_wait_that_is_itself_cancelled_removes_the_records_file(
    tmp_path, scratch
) -> None:
    """The process is killed once the test is done; as above, a task already
    forked waits only a few seconds."""
    playbook = _playbook(tmp_path, "    - name: Wait\n      ansible.builtin.command: sleep 3\n")
    runner = AnsibleRunner(SimpleNamespace())
    variables = tmp_path / "vars.yml"
    variables.write_text("{}\n")
    run = runner.start_playbook(playbook, _local_inventory(tmp_path), variables, "node-1")
    assert stat.S_IMODE(run.failures_path.stat().st_mode) == 0o600
    try:
        waiting = asyncio.ensure_future(runner.wait_for_playbook(run, timeout_seconds=120))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        _assert_cleaned(run, scratch)
    finally:
        run.process.kill()
        run.process.wait()
