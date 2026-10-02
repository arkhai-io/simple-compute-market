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
import re
import select
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from compute_provisioning.hosts import ExecutionHost
from pydantic import BaseModel, Field

from .connection import PRIVATE_KEY, SSH_CONNECTION_KIND, SshConnectionCodec

logger = logging.getLogger(__name__)


def redact_ansible_output(text: str) -> str:
    """Scrub credential-shaped content out of raw Ansible stdout/stderr.

    Shared by every consumer of Ansible subprocess output — this module's
    own real-time debug logging, and ``job_service.py``'s persisted
    ``job.logs`` — so there is exactly one place that defines what
    "credential-shaped" means. Ansible's default behavior echoes a
    ``set_fact``/``debug`` task's rendered value in its own "ok" output;
    without ``no_log: true`` on the task itself (the primary defense, kept
    current in ``vm-create.yml``/``vm-reset-password.yml``), that value
    reaches this function's input. This is defense in depth, not a
    substitute for ``no_log`` on the playbook side.

    ``vm-management/tasks/json-output.yml``'s ``debug: var:``/``debug:
    msg:`` tasks are a deliberate exception that MUST NOT gain `no_log`:
    they are the literal transport `_extract_ansible_json` parses by
    searching raw stdout for a `"<fact_name>":` marker, so credentials
    reach this function's input by design on every VM create. Ansible can
    render that debug-msg'd JSON string either as literal text or as a
    backslash-escaped string nested inside its own outer result dict
    (depends on ``stdout_callback``/``callback_result_format`` and the
    installed Ansible version) as well as the bare YAML `password: value`
    shape `debug: var:` produces — the JSON-shaped pattern below matches
    both the escaped and unescaped forms.
    """
    if not text:
        return text
    redacted = re.sub(
        r'(\\?"(?:password|ssh_key_path_host|frp_auth_token)\\?":\s*)\\?"[^"\\]*\\?"',
        r'\1"[REDACTED]"',
        text,
    )
    redacted = re.sub(
        r"(password:\s*)(?!\[REDACTED\]).+",
        r"\1[REDACTED]",
        redacted,
    )
    # A relay's admission token is a credential of the same class as the two
    # above. It reaches this function through the same route: the extra-vars
    # file is rendered into a command line, and json-output.yml echoes facts by
    # design. Matching the bare YAML form as well, since that is what a
    # ``debug: var:`` task produces.
    redacted = re.sub(
        r"(frp_auth_token:\s*)(?!\[REDACTED\]).+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"-i\s+\S+\.ssh/\S+", "-i [REDACTED]", redacted)
    redacted = re.sub(r"sshpass\s+-p\s+\S+", "sshpass -p [REDACTED]", redacted)
    return redacted


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


class ConnectivityResult(BaseModel):
    """Result of running ``ansible -m ping`` against a single inventory host."""

    host: str = Field(description="Host alias that was tested.")
    reachable: bool = Field(
        description="True if Ansible could authenticate and execute on the host."
    )
    detail: str = Field(
        description="Ansible stdout on success, or the error message on failure."
    )


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
        )

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> AnsibleResult:
        """Wait for a running playbook to finish, streaming output to log_callback.

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
                                        redact_ansible_output(line.rstrip()),
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
                                        redact_ansible_output(line.rstrip()),
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

    def write_inventory(self, hosts: list) -> Path:
        """Write a temporary Ansible INI inventory file from DB host rows.

        Accepts ``InventoryTarget``s built from the host authority's execution
        hosts with ``inventory_target``.
        ``embedded``-key hosts have their key material decrypted and written
        to additional temp files; the INI references those temp paths.

        The returned ``Path`` is a temp file that the caller must delete in
        a ``finally`` block — identical contract to ``build_vars_file``.

        For ``embedded`` hosts, companion key files are written alongside
        the inventory file (same temp directory, named
        ``<host_id>_key``).  They are also deleted when the caller deletes
        the inventory file's parent directory, or the caller may choose to
        clean them up individually.
        """
        import tempfile
        from pathlib import Path as _Path

        nonce = uuid.uuid4().hex
        inv_path = _Path(tempfile.gettempdir()) / f"inventory_{nonce}.ini"

        lines = ["[kvm_hosts]"]
        companion_key_paths: list[_Path] = []

        for host in hosts:
            if host.ssh_key_type == "path":
                key_ref = host.ssh_key_value
            else:
                # Decrypt just in time into a companion temp key file.
                plaintext = self._ssh_codec.decrypt_private_key(host.ssh_key_value)
                key_file = _Path(tempfile.gettempdir()) / f"{host.host_id}_key_{nonce}"
                key_file.write_text(plaintext, encoding="utf-8")
                key_file.chmod(0o400)
                companion_key_paths.append(key_file)
                key_ref = str(key_file)

            # public_host is the tenant-facing address; emit it as a host var
            # so the playbook can use it for the connection strings it returns.
            public_seg = (
                f"  public_host={host.public_host}"
                if getattr(host, "public_host", None)
                else ""
            )
            # ansible_port is emitted for every host, including port 22: the
            # registry always holds a port, and the inventory states it rather
            # than leaving 22 implied by an absent variable.
            lines.append(
                f"{host.host_id}"
                f"  ansible_host={host.ssh_host}"
                f"{public_seg}"
                f"  ansible_port={host.ssh_port}"
                f"  ansible_user={host.ssh_user}"
                f"  ansible_ssh_private_key_file={key_ref}"
            )

        inv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.debug(
            "Wrote inventory to %s (%d host(s), %d companion key file(s))",
            inv_path,
            len(hosts),
            len(companion_key_paths),
        )
        return inv_path

    @staticmethod
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
                    json_str = text[brace_start: i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        return None
        return None

    async def check_connectivity_with_inventory(
        self, host: str, inventory_path: Path
    ) -> ConnectivityResult:
        """Run ``ansible -m ping`` using the supplied *inventory_path*.

        Used by ``HostController`` after rendering a temp inventory from DB rows.
        The caller is responsible for cleaning up any temp file.
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
    "ConnectivityResult",
    "InventoryTarget",
    "inventory_target",
    "redact_ansible_output",
]
