"""A finished playbook run leaves none of its own processes behind.

``start_playbook`` puts every run in its own session, so the run is one process
group this service created and owns. Ending the ansible-playbook process alone
is not enough: its workers fork ssh clients that hold connections to managed
hosts, and those outlive their parent. Once the leader has been reaped its
group can no longer be looked up from its pid, so the group identity has to be
the one recorded when the session was created.

These regressions use a disposable stand-in ``ansible-playbook`` that starts a
sleeping descendant and then exits, reaches a non-zero exit, or lingers. No SSH,
no Ansible and no network are involved. Each test asserts the production
outcome first and cleans up only the processes it started itself.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vm_provisioning_adapter.services.ansible_service import AnsibleError, AnsibleService

# A leader that starts a descendant outliving it, as an ansible worker's ssh
# child does. The descendant gets its own standard streams: holding the run's
# pipes open is a separate concern and would mask this one.
_LEADER = '''#!{python}
import subprocess
import sys
import time

child = subprocess.Popen(
    ["/bin/sleep", "600"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
with open({marker!r}, "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
sys.stdout.write("leader started\\n")
sys.stdout.flush()
time.sleep({linger})
sys.exit({exit_code})
'''

_DESCENDANT_TIMEOUT = 10.0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until_gone(pid: int, timeout: float = _DESCENDANT_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _reap(pid: int | None) -> None:
    """Kill one process this test started, and nothing else."""
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


class _Run:
    """One stand-in playbook run through the real service."""

    def __init__(self, tmp_path: Path, monkeypatch, *, linger: float = 0.0, exit_code: int = 0):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        self.marker = tmp_path / "descendant.pid"
        leader = bin_dir / "ansible-playbook"
        leader.write_text(
            _LEADER.format(
                python=sys.executable,
                marker=str(self.marker),
                linger=linger,
                exit_code=exit_code,
            ),
            encoding="utf-8",
        )
        leader.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
        self.vars_path = tmp_path / "vars.yml"
        self.vars_path.write_text("{}\n", encoding="utf-8")
        self.service = AnsibleService(MagicMock())
        self.tmp_path = tmp_path

    def start(self):
        return self.service.start_playbook(
            playbook_path=self.tmp_path / "playbook.yaml",
            inventory_path=self.tmp_path / "inventory.ini",
            extra_vars_path=self.vars_path,
            limit="bm1",
        )

    def descendant(self) -> int:
        deadline = time.monotonic() + _DESCENDANT_TIMEOUT
        while time.monotonic() < deadline:
            if self.marker.exists():
                text = self.marker.read_text(encoding="utf-8").strip()
                if text:
                    return int(text)
            time.sleep(0.02)
        raise AssertionError("the stand-in never recorded its descendant")


async def test_the_run_group_receipt_is_recorded_when_the_session_is_created(
    tmp_path, monkeypatch
):
    """The group is known from the spawn, not looked up from the pid later."""
    runner = _Run(tmp_path, monkeypatch, linger=0.0)
    spawned = runner.start()
    descendant = runner.descendant()
    try:
        assert spawned.process_group == spawned.process.pid
        assert spawned.process_group not in (None, 0, os.getpgrp())
        await runner.service.wait_for_playbook(spawned, timeout_seconds=30)
    finally:
        _reap(descendant)


async def test_a_reaped_leader_still_has_its_descendants_ended(tmp_path, monkeypatch):
    """The exact reviewed case: the leader exits and is reaped, a child sleeps."""
    runner = _Run(tmp_path, monkeypatch, linger=0.0, exit_code=0)
    spawned = runner.start()
    descendant = runner.descendant()
    try:
        await runner.service.wait_for_playbook(spawned, timeout_seconds=30)

        assert _wait_until_gone(descendant), (
            f"descendant {descendant} outlived a successful run"
        )
    finally:
        _reap(descendant)


async def test_a_nonzero_leader_exit_still_ends_its_descendants(tmp_path, monkeypatch):
    runner = _Run(tmp_path, monkeypatch, linger=0.0, exit_code=3)
    spawned = runner.start()
    descendant = runner.descendant()
    try:
        with pytest.raises(AnsibleError):
            await runner.service.wait_for_playbook(spawned, timeout_seconds=30)

        assert _wait_until_gone(descendant), (
            f"descendant {descendant} outlived a failed run"
        )
    finally:
        _reap(descendant)


async def test_a_timed_out_run_ends_its_leader_and_descendants(tmp_path, monkeypatch):
    runner = _Run(tmp_path, monkeypatch, linger=600, exit_code=0)
    spawned = runner.start()
    descendant = runner.descendant()
    try:
        with pytest.raises(AnsibleError, match="timed out"):
            await runner.service.wait_for_playbook(spawned, timeout_seconds=1)

        assert _wait_until_gone(descendant), (
            f"descendant {descendant} outlived a timed-out run"
        )
        assert _wait_until_gone(spawned.process.pid)
    finally:
        _reap(descendant)
        _reap(spawned.process.pid)


async def test_cancellation_during_the_final_log_callback_ends_descendants(
    tmp_path, monkeypatch
):
    """Cancelling while the last callback is awaited is how the leader gets reaped.

    The streaming loop has already reaped the leader by then, so cleanup that
    looks the group up from its pid has nothing left to find.
    """
    runner = _Run(tmp_path, monkeypatch, linger=0.0, exit_code=0)
    spawned = runner.start()
    descendant = runner.descendant()
    entered = threading.Event()
    release = threading.Event()

    def log_callback(stdout: str, stderr: str) -> None:
        entered.set()
        release.wait(timeout=30)

    task = asyncio.create_task(
        runner.service.wait_for_playbook(
            spawned, timeout_seconds=30, log_callback=log_callback
        )
    )
    try:
        deadline = time.monotonic() + 30
        while not entered.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert entered.is_set(), "the log callback was never reached"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert _wait_until_gone(descendant), (
            f"descendant {descendant} outlived a cancelled run"
        )
    finally:
        release.set()
        _reap(descendant)


async def test_cleanup_never_signals_a_process_outside_the_run(tmp_path, monkeypatch):
    """Only the run's own group is ended; this process's group is untouched."""
    unrelated = subprocess.Popen(
        ["/bin/sleep", "30"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    runner = _Run(tmp_path, monkeypatch, linger=0.0, exit_code=0)
    spawned = runner.start()
    descendant = runner.descendant()
    try:
        # The unrelated process shares this test's group, which the run's
        # cleanup must never signal.
        assert os.getpgid(unrelated.pid) == os.getpgrp()

        await runner.service.wait_for_playbook(spawned, timeout_seconds=30)

        assert _wait_until_gone(descendant)
        assert unrelated.poll() is None, "cleanup reached a process outside the run"
    finally:
        _reap(descendant)
        unrelated.kill()
        unrelated.wait(timeout=10)
