"""The single subprocess boundary for Ansible invocations.

``AnsibleRunner`` spawns and streams ``ansible-playbook`` processes, renders a
transient inventory from registered hosts' ``ssh`` connections (decrypting an
embedded private key just in time, through the ``ssh`` codec, into an
owner-only file), runs ``ansible -m ping`` connectivity checks, and extracts
JSON blocks a playbook prints. It knows no domain: what a job's variables are
and what its output means belong to the domain whose playbook runs.

No inventory file is ever read as an execution source, and nothing else in the
codebase spawns ``ansible`` or ``ansible-playbook``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning_contracts import ConnectivityResult

from .connection import PRIVATE_KEY, SSH_CONNECTION_KIND, SshConnectionCodec

logger = logging.getLogger(__name__)


#: Variable names whose values are secret in any playbook's output.
GENERIC_SECRET_FIELDS = frozenset({"password"})


def redact_ansible_output(text: str, secret_fields: Iterable[str] = ()) -> str:
    """Scrub credential-shaped content out of raw Ansible stdout and stderr.

    Ansible echoes a task's rendered value in its own output unless the task
    sets ``no_log``, and a playbook that reports its result through a printed
    fact does so by design, so a secret can reach this function's input
    whatever the playbook does. This is defense in depth, not a substitute for
    ``no_log`` on the playbook side.

    The value of every field named in ``GENERIC_SECRET_FIELDS`` or
    ``secret_fields`` is replaced, both in the JSON form a printed fact takes
    (literal, or backslash-escaped inside Ansible's own result dictionary,
    depending on the callback and Ansible version) and in the bare YAML form a
    ``debug: var:`` task produces. A domain names the further fields its own
    playbooks print. An SSH identity-file argument and an ``sshpass``
    password are always replaced.
    """
    if not text:
        return text
    names = "|".join(
        re.escape(name) for name in sorted({*GENERIC_SECRET_FIELDS, *secret_fields})
    )
    redacted = re.sub(
        rf'(\\?"(?:{names})\\?":\s*)\\?"[^"\\]*\\?"',
        r'\1"[REDACTED]"',
        text,
    )
    redacted = re.sub(
        rf"((?:{names}):\s*)(?!\[REDACTED\]).+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"-i\s+\S+\.ssh/\S+", "-i [REDACTED]", redacted)
    redacted = re.sub(r"sshpass\s+-p\s+\S+", "sshpass -p [REDACTED]", redacted)
    return redacted


def extract_json_block(text: str, search_start: int) -> Optional[dict]:
    """The first balanced JSON object in ``text`` at or after ``search_start``."""
    brace_start = text.find("{", search_start)
    if brace_start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i in range(brace_start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace_start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_fact(stdout: str, fact_name: str) -> Optional[dict]:
    """The value of fact ``fact_name`` a ``debug: var:`` task printed, if any."""
    marker = f'"{fact_name}":'
    index = stdout.find(marker)
    if index == -1:
        return None
    return extract_json_block(stdout, index + len(marker))


@dataclass
class AnsibleRun:
    """Handle to a running ansible-playbook process.

    ``job_parameters`` are the stored parameters of the job the run serves.
    The runner never reads them; a stand-in that keys its behaviour on the job
    (the mock runner's rules) does.
    """

    process: subprocess.Popen
    process_id: int
    vars_path: Path
    job_parameters: Mapping[str, Any] | None = None


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


@dataclass(frozen=True)
class InventoryTarget:
    """The host attributes the runner renders one inventory line from.

    A protected private key reaches the runner still protected; the runner
    decrypts it only to write the transient key file the playbook uses.
    """

    host_id: str
    ssh_host: str
    public_host: str | None
    ssh_port: int
    ssh_user: str
    ssh_key_type: str
    ssh_key_value: str = field(repr=False)


def inventory_target(host: ExecutionHost) -> InventoryTarget:
    """What the runner needs from a host reached over an ``ssh`` connection."""
    connection = host.connection
    if connection.kind != SSH_CONNECTION_KIND:
        raise ValueError(
            f"host {host.host_id!r} has a {connection.kind!r} connection; "
            "an Ansible job reaches its host over ssh"
        )
    ssh = SshConnectionCodec.parse(connection)
    private_key = connection.protected.get(PRIVATE_KEY)
    if ssh.key_path is not None:
        key_type, key_value = "path", ssh.key_path
    elif private_key is not None:
        key_type, key_value = "embedded", private_key.ciphertext
    else:
        raise ValueError(f"host {host.host_id!r} has an ssh connection naming no key")
    return InventoryTarget(
        host_id=host.host_id,
        ssh_host=ssh.ssh_host,
        public_host=ssh.public_host,
        ssh_port=ssh.ssh_port,
        ssh_user=ssh.ssh_user,
        ssh_key_type=key_type,
        ssh_key_value=key_value,
    )


@dataclass
class MaterializedInventory:
    """A rendered inventory and the decrypted key files it references.

    The key files hold plaintext private keys, so this object owns their
    lifetime: ``cleanup()`` removes the inventory and every key file, and it is
    safe to call more than once. Use it as a context manager, or call
    ``cleanup()`` in a ``finally``.
    """

    path: Path
    key_paths: list[Path] = field(default_factory=list)

    def cleanup(self) -> None:
        for leftover in (*self.key_paths, self.path):
            try:
                leftover.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", leftover, exc)

    def __enter__(self) -> "MaterializedInventory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()


def _write_owner_only(path: Path, text: str) -> None:
    """Create ``path`` readable only by its owner, then write ``text``.

    The file never exists with wider permissions: it is created with mode
    0600 and made read-only once written.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o400)


class AnsibleRunner:
    """Runs playbooks and connectivity checks; see the module docstring.

    ``settings`` supplies ``ansible_timeout_seconds`` for connectivity checks;
    ``ssh_codec`` decrypts embedded private keys, built from the settings'
    ``ssh_decryption_key`` when not given.
    """

    def __init__(self, settings: Any, *, ssh_codec: SshConnectionCodec | None = None) -> None:
        self._settings = settings
        self._ssh_codec = ssh_codec or SshConnectionCodec(
            getattr(settings, "ssh_decryption_key", "") or None
        )

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
        job_parameters: Mapping[str, Any] | None = None,
    ) -> AnsibleRun:
        """Spawn ansible-playbook and return immediately with a process handle.

        The caller must pass the returned handle to ``await wait_for_playbook``
        to collect the result.  ``extra_vars_path`` is cleaned up inside
        ``wait_for_playbook``.
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
            job_parameters=job_parameters,
        )

    @staticmethod
    def execution_handle(run: AnsibleRun) -> dict[str, Any]:
        """What the job authority stores to stop ``run`` later: its process id."""
        return {"pid": run.process_id}

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """Stop the playbook a handle from ``execution_handle`` names.

        The process is sent ``SIGTERM``; its wait then ends as a failed run.
        A process id of zero or less names a process group (zero is this
        service's own), never a playbook, and is refused.
        """
        pid = int(handle["pid"])
        if pid <= 0:
            logger.warning("Refusing to signal process id %d for handle %s", pid, dict(handle))
            return
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to process %d", pid)
        except ProcessLookupError:
            logger.warning("Process %d not found (already terminated)", pid)

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable[[str, str], None]] = None,
        redact: Callable[[str], str] = redact_ansible_output,
    ) -> AnsibleResult:
        """Wait for a running playbook to finish, streaming output to log_callback.

        ``redact`` scrubs each line this method logs; the caller passes one
        that knows its playbook's secret fields. What ``log_callback`` and the
        result receive is raw: their consumer redacts it.

        Cleans up ``run.vars_path`` on exit regardless of success or failure.
        Raises ``AnsibleError`` on non-zero exit or timeout.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _stream() -> None:
            last_callback = time.time()
            while True:
                if run.process.poll() is not None:
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
                                    logger.debug(
                                        "ansible stdout: %s",
                                        redact(line.rstrip()),
                                    )
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
                                    logger.debug(
                                        "ansible stderr: %s",
                                        redact(line.rstrip()),
                                    )
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
            raise AnsibleError(
                f"Playbook error: {exc}", stdout, stderr or str(exc)
            ) from exc
        finally:
            try:
                run.vars_path.unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "Failed to delete temp vars file: %s", run.vars_path
                )

        return AnsibleResult(
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            process_id=run.process_id,
        )

    # ------------------------------------------------------------------
    # Inventory rendering
    # ------------------------------------------------------------------

    def write_inventory(self, hosts: list, *, group: str) -> "MaterializedInventory":
        """Write a temporary Ansible INI inventory for ``InventoryTarget``s.

        Every host is listed under ``group``, the group the playbook that runs
        against this inventory targets; the caller names it, because which
        group a playbook targets is part of that playbook.

        A ``path`` key is referenced where it lies. An ``embedded`` key is
        decrypted just in time into an owner-only temporary file the inventory
        references. The returned ``MaterializedInventory`` owns the inventory
        and every such key file: the caller must ``cleanup()`` it in a
        ``finally`` (or use it as a context manager), and if writing fails
        part way, what was already written is removed before the error
        propagates.
        """
        nonce = uuid.uuid4().hex
        directory = Path(tempfile.gettempdir())
        inventory = MaterializedInventory(path=directory / f"inventory_{nonce}.ini")
        try:
            lines = [f"[{group}]"]
            for host in hosts:
                if host.ssh_key_type == "path":
                    key_ref = host.ssh_key_value
                else:
                    key_file = directory / f"{host.host_id}_key_{nonce}"
                    inventory.key_paths.append(key_file)
                    _write_owner_only(
                        key_file, self._ssh_codec.decrypt_private_key(host.ssh_key_value)
                    )
                    key_ref = str(key_file)

                # public_host is the tenant-facing address; emit it as a host
                # var so the playbook can use it for the connection strings it
                # returns.
                public_seg = (
                    f"  public_host={host.public_host}"
                    if getattr(host, "public_host", None)
                    else ""
                )
                # ansible_port is emitted for every host, including port 22:
                # the registry always holds a port, and the inventory states it
                # rather than leaving 22 implied by an absent variable.
                lines.append(
                    f"{host.host_id}"
                    f"  ansible_host={host.ssh_host}"
                    f"{public_seg}"
                    f"  ansible_port={host.ssh_port}"
                    f"  ansible_user={host.ssh_user}"
                    f"  ansible_ssh_private_key_file={key_ref}"
                )
            inventory.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except BaseException:
            inventory.cleanup()
            raise
        logger.debug(
            "Wrote inventory to %s (%d host(s), %d key file(s))",
            inventory.path,
            len(hosts),
            len(inventory.key_paths),
        )
        return inventory

    async def check_connectivity_with_inventory(
        self, host: str, inventory_path: Path
    ) -> ConnectivityResult:
        """Run ``ansible -m ping`` using the supplied *inventory_path*.

        The caller renders the inventory and is responsible for cleaning it up.
        """
        cmd = [
            "ansible",
            "-i", str(inventory_path),
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


__all__ = [
    "AnsibleError",
    "AnsibleResult",
    "AnsibleRun",
    "AnsibleRunner",
    "InventoryTarget",
    "GENERIC_SECRET_FIELDS",
    "MaterializedInventory",
    "extract_fact",
    "extract_json_block",
    "inventory_target",
    "redact_ansible_output",
]
