from __future__ import annotations

import asyncio
import logging
import select
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Settings
from models.ansible import (
    ConnectivityResult,
    InventoryHost,
    InventoryResponse,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process handle types — owned by AnsibleService, consumed by callers
# ---------------------------------------------------------------------------


@dataclass
class AnsibleRun:
    """Handle to a running ansible-playbook process."""
    process: subprocess.Popen
    process_id: int
    vars_path: Path


@dataclass
class AnsibleResult:
    """Captured output from a completed ansible-playbook invocation."""
    stdout: str
    stderr: str
    process_id: int


class AnsibleError(RuntimeError):
    """Raised when ansible-playbook exits non-zero or times out."""
    def __init__(self, message: str, stdout: str, stderr: str):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnsibleService:
    """Single subprocess boundary for all Ansible invocations.

    This is the only class in the codebase that spawns ansible or
    ansible-playbook processes.  Higher-level services (e.g.
    ``ProvisioningService``) call into this class and work with
    ``AnsibleRun`` / ``AnsibleResult`` — they never touch subprocess
    directly.  This makes it straightforward to mock all ansible
    execution in tests by replacing a single service.

    The service is deliberately playbook-agnostic.  It accepts paths
    and extra-vars files prepared by callers; it does not know about
    the VM operations playbook schema.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Playbook execution — async streaming interface
    # ------------------------------------------------------------------

    def start_playbook(
        self,
        playbook_path: Path,
        inventory_path: Path,
        extra_vars_path: Path,
        limit: str,
        extra_cli_vars: dict[str, str] | None = None,
    ) -> AnsibleRun:
        """Spawn ansible-playbook and return immediately with a process handle.

        The caller is responsible for calling ``await wait_for_playbook``
        with the returned handle.  ``extra_vars_path`` is a temporary file
        written by the caller; cleanup is handled inside ``wait_for_playbook``.
        """
        cmd = [
            "ansible-playbook",
            "-i", str(inventory_path),
            str(playbook_path),
            "--extra-vars", f"@{extra_vars_path}",
            "--limit", limit,
        ]
        for k, v in (extra_cli_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        logger.info(
            "Started ansible-playbook: PID=%d cmd=%s", process.pid, " ".join(cmd)
        )

        return AnsibleRun(
            process=process,
            process_id=process.pid,
            vars_path=extra_vars_path,
        )

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> AnsibleResult:
        """Wait for a running playbook to finish, streaming output to log_callback.

        Cleans up the ``run.vars_path`` temporary file on exit regardless
        of success or failure.

        Raises ``AnsibleError`` on non-zero exit or timeout.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _stream() -> None:
            last_callback = time.time()
            while True:
                if run.process.poll() is not None:
                    # Drain remaining output after process exits.
                    if run.process.stdout:
                        tail = run.process.stdout.read()
                        if tail:
                            stdout_lines.append(tail)
                    if run.process.stderr:
                        tail = run.process.stderr.read()
                        if tail:
                            stderr_lines.append(tail)
                    break

                if run.process.stdout:
                    try:
                        if sys.platform != "win32":
                            readable, _, _ = select.select(
                                [run.process.stdout], [], [], 0.1
                            )
                            if readable:
                                line = run.process.stdout.readline()
                                if line:
                                    stdout_lines.append(line)
                                    logger.debug("ansible stdout: %s", line.rstrip())
                        else:
                            line = run.process.stdout.readline()
                            if line:
                                stdout_lines.append(line)
                    except Exception:
                        pass

                if run.process.stderr:
                    try:
                        if sys.platform != "win32":
                            readable, _, _ = select.select(
                                [run.process.stderr], [], [], 0.1
                            )
                            if readable:
                                line = run.process.stderr.readline()
                                if line:
                                    stderr_lines.append(line)
                                    logger.debug("ansible stderr: %s", line.rstrip())
                        else:
                            line = run.process.stderr.readline()
                            if line:
                                stderr_lines.append(line)
                    except Exception:
                        pass

                now = time.time()
                if log_callback and (now - last_callback) >= 2.0:
                    try:
                        await asyncio.to_thread(
                            log_callback,
                            "".join(stdout_lines),
                            "".join(stderr_lines),
                        )
                    except Exception as exc:
                        logger.warning("Log callback failed: %s", exc)
                    last_callback = now

                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_stream(), timeout=timeout_seconds)

            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)

            if log_callback:
                try:
                    await asyncio.to_thread(log_callback, stdout, stderr)
                except Exception as exc:
                    logger.warning("Final log callback failed: %s", exc)

            if run.process.returncode != 0:
                raise AnsibleError("Playbook failed", stdout, stderr)

        except asyncio.TimeoutError:
            run.process.kill()
            run.process.wait()
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            raise AnsibleError("Playbook timed out", stdout, stderr)
        except AnsibleError:
            raise
        except Exception as exc:
            try:
                run.process.kill()
                run.process.wait()
            except Exception:
                pass
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            raise AnsibleError(f"Playbook error: {exc}", stdout, stderr or str(exc)) from exc
        finally:
            try:
                run.vars_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("Failed to delete temp vars file: %s", run.vars_path)

        return AnsibleResult(
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            process_id=run.process_id,
        )

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def parse_inventory(self, search: str | None = None) -> list[InventoryHost]:
        """Parse the Ansible INI inventory and return a list of hosts.

        Skips group headers (``[group_name]``) and comment lines.
        Each host line has the format::

            hostname  var1=val1  var2=val2  ...

        If *search* is provided, only hosts whose name contains the
        string (case-insensitive) are returned.

        Raises ``FileNotFoundError`` if the inventory file does not exist.
        """
        inventory_path = self._settings.resolved_inventory_path
        if not inventory_path.exists():
            raise FileNotFoundError(f"Inventory not found at {inventory_path}")

        hosts: list[InventoryHost] = []
        for line in inventory_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue

            parts = stripped.split()
            name = parts[0]

            if search and search.lower() not in name.lower():
                continue

            host_vars: dict[str, str] = {}
            for part in parts[1:]:
                if "=" in part:
                    k, _, v = part.partition("=")
                    host_vars[k] = v

            hosts.append(
                InventoryHost(
                    name=name,
                    ansible_host=host_vars.pop("ansible_host", None),
                    vars=host_vars,
                )
            )

        return hosts

    def get_inventory(self, search: str | None = None) -> InventoryResponse:
        """Return an ``InventoryResponse`` for the current inventory file."""
        hosts = self.parse_inventory(search=search)
        return InventoryResponse(
            inventory_path=str(self._settings.resolved_inventory_path),
            hosts=hosts,
        )

    def lookup_host_ip(self, vm_host: str) -> Optional[str]:
        """Return the ``ansible_host`` value for *vm_host* from the inventory.

        Returns ``None`` if the host is not found or the inventory is unreadable.
        Called by ``ProvisioningService`` to resolve a host alias to an IP.
        """
        try:
            for host in self.parse_inventory():
                if host.name == vm_host:
                    return host.ansible_host
        except Exception as exc:
            logger.warning("Failed to read inventory: %s", exc)
        logger.warning("No ansible_host found for %s in inventory", vm_host)
        return None

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Run ``ansible -m ping`` against a single named inventory host.

        Exercises the full Ansible auth path: inventory parses correctly,
        the host exists, the SSH key is valid, and Ansible can execute on
        the target.

        Returns a ``ConnectivityResult`` with ``reachable=False`` if the
        host is unreachable or the ping fails — **not** a 404.  The caller
        is responsible for verifying the host exists before calling this.
        """
        cmd = [
            "ansible",
            "-i", str(self._settings.resolved_inventory_path),
            host,
            "-m", "ping",
        ]

        logger.info("Running connectivity check: %s", " ".join(cmd))

        def _run() -> tuple[int, str, str]:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._settings.ansible_timeout_seconds,
            )
            return result.returncode, result.stdout, result.stderr

        try:
            returncode, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=self._settings.ansible_timeout_seconds + 5,
            )
        except asyncio.TimeoutError:
            return ConnectivityResult(
                host=host, reachable=False, detail="Connectivity check timed out"
            )
        except Exception as exc:
            return ConnectivityResult(
                host=host, reachable=False, detail=f"Failed to run ansible ping: {exc}"
            )

        reachable = returncode == 0
        detail = stdout.strip() if reachable else (stderr.strip() or stdout.strip())
        logger.info("Connectivity check for %s: reachable=%s", host, reachable)
        return ConnectivityResult(host=host, reachable=reachable, detail=detail)
