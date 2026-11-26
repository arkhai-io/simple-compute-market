"""The single subprocess boundary for Ansible invocations.

``AnsibleRunner`` spawns and streams ``ansible-playbook`` processes, renders a
transient inventory from registered hosts' ``ssh`` connections (decrypting an
embedded private key just in time, through the ``ssh`` codec, into an
owner-only file), runs ``ansible -m ping`` connectivity checks, and reads
the facts a playbook prints. It knows no domain: what a job's variables are
and what its output means belong to the domain whose playbook runs.

No inventory file is ever read as an execution source, and nothing else in the
codebase spawns ``ansible`` or ``ansible-playbook``.

Every playbook runs with the notification callback of ``failures`` on its
callback plugin path, recording each failed or unreachable task to an
owner-only file named for the run. ``wait_for_playbook`` reads those records
once the process has ended, attaches them to the result it returns or the
error it raises, and removes the file however the run ends: the records reach
their reader on the run's outcome, never through the file.
"""

from __future__ import annotations

import asyncio
import configparser
import json
import logging
import os
import re
import select
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning.jobs import ConfigurationRefusedError
from compute_provisioning_contracts import ConnectivityResult

from .connection import PRIVATE_KEY, SSH_CONNECTION_KIND, SshConnectionCodec
from .failures import (
    CALLBACK_PLUGINS_DIR,
    FAILURE_RECORDS_ENV,
    FailureRecord,
    read_failure_records,
)

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
    """The value of fact ``fact_name`` a ``debug: var:`` task printed, if any.

    Only the JSON result format quotes the fact's name, so only that format is
    read; ``read_fact`` also reads the fact a role prints for an action.
    """
    marker = f'"{fact_name}":'
    index = stdout.find(marker)
    if index == -1:
        return None
    return extract_json_block(stdout, index + len(marker))


#: The key line of a ``debug: msg:`` result the YAML result format prints as a
#: literal block, and the indentation of its key.
_MSG_BLOCK_KEY = re.compile(r"(?P<indent> *)msg: \|-?")


def _msg_blocks(stdout: str) -> Iterator[str]:
    """The text of each ``msg: |`` or ``msg: |-`` literal block in ``stdout``.

    A block is the lines after its key line, up to the first non-blank line
    indented no deeper than the key; its text has their common indentation
    removed. A block never extends into the output after it, so a block that
    is not a document cannot borrow a later task's.
    """
    lines = stdout.splitlines()
    index = 0
    while index < len(lines):
        key = _MSG_BLOCK_KEY.fullmatch(lines[index].rstrip())
        index += 1
        if key is None:
            continue
        key_indent = len(key.group("indent"))
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= key_indent:
                break
            body.append(line)
            index += 1
        yield textwrap.dedent("\n".join(body))


def read_fact(stdout: str, fact_name: str, *, action: str) -> Optional[dict]:
    """The fact a role printed for ``action``, whichever result format printed it.

    The fact ``fact_name`` printed by a ``debug: var:`` task in the JSON result
    format is taken first, as ``extract_fact`` reads it. The YAML result format
    prints that fact as YAML, which is not read: this kit declares a YAML parser
    for its tests only, and decoding the JSON copy of the fact a role also prints
    keeps reading to the standard library. A role prints that copy through a
    ``debug: msg:`` task, which the YAML format prints as a literal block. Each
    such block is parsed alone, as one JSON document, and
    one that is not JSON, not an object, names no ``action``, or names another
    action is ignored: a play prints other blocks, its human-readable summary
    among them. The last document naming ``action`` is the fact. With none,
    the fact is absent.

    Whether the fact belongs to the job, and what it means, is the caller's to
    judge. Only how many blocks were ignored, and why, is logged: a block may
    carry credentials.
    """
    fact = extract_fact(stdout, fact_name)
    if fact is not None:
        return fact
    ignored: Counter[str] = Counter()
    for block in _msg_blocks(stdout):
        try:
            document = json.loads(block)
        except (ValueError, RecursionError):
            ignored["not_json"] += 1
            continue
        if not isinstance(document, dict):
            ignored["not_object"] += 1
        elif "action" not in document:
            ignored["no_action"] += 1
        elif document["action"] != action:
            ignored["other_action"] += 1
        else:
            fact = document
    if ignored:
        logger.debug(
            "Reading fact %s for action %s: %s; %d ignored (%s)",
            fact_name,
            action,
            "found" if fact is not None else "absent",
            sum(ignored.values()),
            ", ".join(f"{reason}={count}" for reason, count in sorted(ignored.items())),
        )
    return fact


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
    #: The file the notification callback appends this run's failure records
    #: to; ``None`` for a run that records none.
    failures_path: Path | None = None


@dataclass
class AnsibleResult:
    """Captured output from a completed ansible-playbook invocation.

    ``failures`` are the run's recorded task failures; a successful run's are
    all ignored or rescued.
    """

    stdout: str
    stderr: str
    process_id: int
    failures: tuple[FailureRecord, ...] = ()


#: How a failed run ended, as ``AnsibleError.outcome`` reports it.
#: ``failed``: the playbook exited non-zero. ``timed_out``: it ran past its
#: timeout and was killed. ``cancelled``: it was stopped through its
#: cancellation handle. ``error``: running or watching it raised.
RUN_OUTCOMES = frozenset({"failed", "timed_out", "cancelled", "error"})


class AnsibleError(RuntimeError):
    """Raised when ansible-playbook exits non-zero, times out, or is cancelled.

    ``outcome`` says how the run ended (one of ``RUN_OUTCOMES``),
    ``returncode`` is the process's exit status where it ended by itself, and
    ``failures`` are the task failures it recorded before it ended.
    """

    def __init__(
        self,
        message: str,
        stdout: str,
        stderr: str,
        *,
        outcome: str = "failed",
        returncode: int | None = None,
        failures: tuple[FailureRecord, ...] = (),
    ):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.outcome = outcome
        self.returncode = returncode
        self.failures = failures


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
    public_port: int | None = None
    host_keys: tuple[str, ...] = ()


def inventory_target(host: ExecutionHost, *, include_host_keys: bool = True) -> InventoryTarget:
    """What the runner needs from a host reached over an ``ssh`` connection.

    A host the runner cannot reach as registered — another kind of connection,
    or no key — is refused as ``ConfigurationRefusedError``.
    """
    connection = host.connection
    if connection.kind != SSH_CONNECTION_KIND:
        raise ConfigurationRefusedError(
            f"host {host.host_id!r} has a {connection.kind!r} connection; "
            "an Ansible job reaches its host over ssh"
        )
    ssh = SshConnectionCodec.parse(connection, include_host_keys=include_host_keys)
    private_key = connection.protected.get(PRIVATE_KEY)
    if ssh.key_path is not None:
        key_type, key_value = "path", ssh.key_path
    elif private_key is not None:
        key_type, key_value = "embedded", private_key.ciphertext
    else:
        raise ConfigurationRefusedError(f"host {host.host_id!r} has an ssh connection naming no key")
    return InventoryTarget(
        host_id=host.host_id,
        ssh_host=ssh.ssh_host,
        public_host=ssh.public_host,
        ssh_port=ssh.ssh_port,
        ssh_user=ssh.ssh_user,
        ssh_key_type=key_type,
        ssh_key_value=key_value,
        public_port=ssh.public_port,
        host_keys=tuple(ssh.host_keys or ()),
    )


@dataclass
class MaterializedInventory:
    """A rendered inventory and the key files and host pins it references.

    The key files hold plaintext private keys, so this object owns their
    lifetime: ``cleanup()`` removes the inventory and every key file, and it is
    safe to call more than once. Use it as a context manager, or call
    ``cleanup()`` in a ``finally``.
    """

    path: Path
    key_paths: list[Path] = field(default_factory=list)
    known_hosts_paths: list[Path] = field(default_factory=list)

    def cleanup(self) -> None:
        for leftover in (*self.key_paths, *self.known_hosts_paths, self.path):
            try:
                leftover.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", leftover, exc)

    def __enter__(self) -> "MaterializedInventory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()


def _default_callback_paths(environment: Mapping[str, str], config: Path | None) -> list[str]:
    """Ansible's default callback plugin directories, searched when neither the
    environment nor the configuration names any: ``plugins/callback`` under Ansible's
    home — ``ANSIBLE_HOME``, else the configuration's ``home``, else ``~/.ansible`` —
    then the system directory."""
    home = environment.get("ANSIBLE_HOME")
    if not home and config is not None:
        configured = _config_value(config, "home")
        home = _resolve_config_path(configured, config) if configured else None
    return [f"{home or '~/.ansible'}/plugins/callback", "/usr/share/ansible/plugins/callback"]


def _create_records_file() -> Path:
    """Create an empty, owner-only file for one run's failure records.

    It stays writable, since the callback appends to it, and is created before
    the playbook starts, so the callback never creates it with wider
    permissions.
    """
    path = Path(tempfile.gettempdir()) / f"ansible_failures_{uuid.uuid4().hex}.jsonl"
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    return path


def _ansible_config_file(environment: Mapping[str, str]) -> Path | None:
    """The configuration file Ansible reads, found in Ansible's own order.

    ``ANSIBLE_CONFIG`` (a directory meaning the ``ansible.cfg`` in it), then the
    working directory's ``ansible.cfg`` unless that directory is world-writable,
    then ``~/.ansible.cfg``, then ``/etc/ansible/ansible.cfg``: the first that
    exists and is readable.
    """
    candidates: list[Path] = []
    named = environment.get("ANSIBLE_CONFIG")
    if named is not None:
        path = Path(os.path.expanduser(os.path.expandvars(named)))
        candidates.append(path / "ansible.cfg" if path.is_dir() else path)
    try:
        cwd = Path.cwd()
        if not cwd.stat().st_mode & stat.S_IWOTH:
            candidates.append(cwd / "ansible.cfg")
    except OSError:
        pass
    candidates += [Path("~/.ansible.cfg").expanduser(), Path("/etc/ansible/ansible.cfg")]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.R_OK):
            return candidate
    return None


def _config_value(config: Path, key: str) -> str | None:
    """``config``'s ``[defaults]`` value for ``key``, read as Ansible reads the
    file, or ``None`` when it names none or cannot be read — in which case Ansible
    applies its default, or reports the file itself."""
    parser = configparser.ConfigParser(inline_comment_prefixes=(";",))
    try:
        parser.read(config, encoding="utf-8")
        value = parser.get("defaults", key, raw=True, fallback=None)
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None
    return value.strip() if value and value.strip() else None


def _resolve_config_path(entry: str, config: Path) -> str:
    """A path ``config`` names, resolved as Ansible resolves it: ``{{CWD}}`` the
    working directory, ``~`` and variables expanded, a relative path taken from the
    directory the file is named in, its links not followed."""
    base = os.path.dirname(os.path.abspath(config))
    entry = entry.replace("{{CWD}}", os.getcwd())
    return os.path.normpath(os.path.join(base, os.path.expanduser(os.path.expandvars(entry))))


def _configured_callback_paths(config: Path) -> list[str] | None:
    """The ``callback_plugins`` directories ``config`` names, resolved, or ``None``
    when it names none."""
    value = _config_value(config, "callback_plugins")
    if value is None:
        return None
    return [
        _resolve_config_path(entry.strip(), config)
        for entry in value.split(os.pathsep)
        if entry.strip()
    ]


def playbook_environment(failures_path: Path) -> dict[str, str]:
    """The environment a playbook runs in: this process's, with the callback.

    Ansible has no setting that adds a callback directory: ``ANSIBLE_CALLBACK_PLUGINS``
    replaces the search path, outranking an ``ansible.cfg``'s ``callback_plugins``
    and Ansible's default directories. So the variable is the path Ansible would
    otherwise search, with the callback's directory in front: a value this
    process's environment already gives; else the ``callback_plugins`` of the
    configuration file Ansible reads; else Ansible's defaults. A stdout or
    notification callback an operator's configuration loads from its own
    directory is still found. The callback needs no enabling, so the runner sets
    no enabled callbacks and no stdout callback.
    """
    environment = dict(os.environ)
    existing = environment.get("ANSIBLE_CALLBACK_PLUGINS")
    if existing:
        searched = [existing]
    else:
        config = _ansible_config_file(environment)
        configured = _configured_callback_paths(config) if config is not None else None
        searched = (
            configured if configured is not None else _default_callback_paths(environment, config)
        )
    environment["ANSIBLE_CALLBACK_PLUGINS"] = os.pathsep.join(
        [str(CALLBACK_PLUGINS_DIR), *searched]
    )
    environment[FAILURE_RECORDS_ENV] = str(failures_path)
    return environment


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
        # Process ids of the playbooks this runner is waiting on, and those of
        # them it signalled through ``cancel``, so the wait on each reports
        # its run as cancelled rather than failed. Only a pid being waited on
        # is marked, and the wait forgets it, so a later process reusing the
        # pid is never taken for a cancelled run.
        self._waiting: set[int] = set()
        self._cancelled: set[int] = set()

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
        to collect the result.  ``extra_vars_path`` and the run's failure
        records file are cleaned up inside ``wait_for_playbook``; if the
        process cannot be spawned, the records file is removed here.
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

        failures_path = _create_records_file()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=playbook_environment(failures_path),
            )
        except BaseException:
            failures_path.unlink(missing_ok=True)
            raise

        logger.info(
            "Started ansible-playbook: PID=%d cmd=%s", process.pid, " ".join(cmd)
        )

        return AnsibleRun(
            process=process,
            process_id=process.pid,
            vars_path=extra_vars_path,
            job_parameters=job_parameters,
            failures_path=failures_path,
        )

    @staticmethod
    def execution_handle(run: AnsibleRun) -> dict[str, Any]:
        """What the job authority stores to stop ``run`` later: its process id."""
        return {"pid": run.process_id}

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """Stop the playbook a handle from ``execution_handle`` names.

        The process is sent ``SIGTERM``; its wait then ends as a cancelled
        run, unless it had already exited successfully. A process id of zero
        or less names a process group (zero is this service's own), never a
        playbook, and is refused.
        """
        pid = int(handle["pid"])
        if pid <= 0:
            logger.warning("Refusing to signal process id %d for handle %s", pid, dict(handle))
            return
        if pid in self._waiting:
            self._cancelled.add(pid)
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to process %d", pid)
        except ProcessLookupError:
            self._cancelled.discard(pid)
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

        The run's failure records are read once the process has ended and
        attached to the result or the error. ``run.vars_path`` and the records
        file are removed on exit however the run ends: success, failure,
        timeout, or cancellation, the wait's own included. Raises
        ``AnsibleError`` on non-zero exit, timeout, or cancellation.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        self._waiting.add(run.process_id)

        async def _stream() -> None:
            # The log flush interval is a duration of this wait, on the
            # monotonic clock.
            last_callback = time.monotonic()
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

                now = time.monotonic()
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

        def _records() -> tuple[FailureRecord, ...]:
            # Read only once the process has ended, so every record is written.
            if run.failures_path is None:
                return ()
            return read_failure_records(run.failures_path)

        try:
            await asyncio.wait_for(_stream(), timeout=timeout_seconds)

            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)

            if log_callback:
                try:
                    await asyncio.to_thread(log_callback, stdout, stderr)
                except Exception as exc:
                    logger.warning("Final log callback failed: %s", exc)

            failures = _records()
            returncode = run.process.returncode
            if returncode != 0 and run.process_id in self._cancelled:
                raise AnsibleError(
                    "Playbook cancelled", stdout, stderr,
                    outcome="cancelled", returncode=returncode, failures=failures,
                )
            if returncode != 0:
                raise AnsibleError(
                    "Playbook failed", stdout, stderr,
                    outcome="failed", returncode=returncode, failures=failures,
                )

        except asyncio.TimeoutError:
            run.process.kill()
            run.process.wait()
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            raise AnsibleError(
                "Playbook timed out", stdout, stderr,
                outcome="timed_out", failures=_records(),
            )
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
                f"Playbook error: {exc}", stdout, stderr or str(exc),
                outcome="error", failures=_records(),
            ) from exc
        finally:
            self._waiting.discard(run.process_id)
            self._cancelled.discard(run.process_id)
            for leftover in (run.vars_path, run.failures_path):
                if leftover is None:
                    continue
                try:
                    leftover.unlink(missing_ok=True)
                except Exception:
                    logger.warning("Failed to delete temporary file: %s", leftover)

        return AnsibleResult(
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            process_id=run.process_id,
            failures=failures,
        )

    # ------------------------------------------------------------------
    # Inventory rendering
    # ------------------------------------------------------------------

    def validate_authentication_key(self, target: InventoryTarget) -> None:
        """Check that an embedded identity can be read without writing it to a file."""
        if target.ssh_key_type == "embedded":
            self._ssh_codec.decrypt_private_key(target.ssh_key_value, host_id=target.host_id)

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
        propagates. A key that cannot be decrypted raises
        ``ProtectedKeyUnreadableError`` naming its host.
        """
        nonce = uuid.uuid4().hex
        directory = Path(tempfile.gettempdir())
        inventory = MaterializedInventory(path=directory / f"inventory_{nonce}.ini")
        try:
            lines = [f"[{group}]"]
            for index, host in enumerate(hosts):
                if re.search(r"[^a-zA-Z0-9.:%_-]", host.ssh_host):
                    raise ConfigurationRefusedError(
                        f"host {host.host_id!r} has an invalid SSH endpoint"
                    )
                endpoint = f"[{host.ssh_host}]:{host.ssh_port}"
                pins_path = directory / f"known_hosts_{nonce}_{index}"
                inventory.known_hosts_paths.append(pins_path)
                _write_owner_only(
                    pins_path,
                    "".join(f"{endpoint} {key}\n" for key in getattr(host, "host_keys", ())),
                )
                # A multiplexed connection could skip host-key verification.
                ssh_args = "-F /dev/null -C -o ControlMaster=no -o ControlPath=none"
                # Use the same explicit alias at every port, including 22.
                strict_args = shlex.join((
                    "-o", f"HostKeyAlias={endpoint}",
                    "-o", f"UserKnownHostsFile={pins_path}",
                    "-o", "GlobalKnownHostsFile=/dev/null",
                    "-o", "StrictHostKeyChecking=yes",
                    "-o", "UpdateHostKeys=no",
                ))
                if host.ssh_key_type == "path":
                    key_ref = host.ssh_key_value
                else:
                    key_file = directory / f"{host.host_id}_key_{nonce}"
                    inventory.key_paths.append(key_file)
                    _write_owner_only(
                        key_file,
                        self._ssh_codec.decrypt_private_key(
                            host.ssh_key_value, host_id=host.host_id
                        ),
                    )
                    key_ref = str(key_file)

                # public_host and public_port are the tenant-facing route; emit
                # each the connection states as a host var so a playbook can use
                # it for the connection strings it returns. One it does not
                # state is the connection's own ansible_host or ansible_port.
                public_seg = (
                    f"  public_host={host.public_host}"
                    if getattr(host, "public_host", None)
                    else ""
                )
                if getattr(host, "public_port", None) is not None:
                    public_seg += f"  public_port={host.public_port}"
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
                    "  ansible_connection=ssh"
                    "  ansible_host_key_checking=true"
                    f"  ansible_ssh_args={shlex.quote(ssh_args)}"
                    f"  ansible_ssh_common_args={shlex.quote(strict_args)}"
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
        The result's ``detail`` leaves the service, so it is redacted, with the
        generic secret fields only, since a probe runs no domain's playbook:
        Ansible's output and the text of an error running it alike.
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
                host=host,
                reachable=False,
                detail=redact_ansible_output(f"Failed to run ansible ping: {exc}"),
            )

        reachable = returncode == 0
        detail = stdout.strip() if reachable else (stderr.strip() or stdout.strip())
        logger.info("Connectivity check for %s: reachable=%s", host, reachable)
        return ConnectivityResult(
            host=host, reachable=reachable, detail=redact_ansible_output(detail)
        )


__all__ = [
    "AnsibleError",
    "AnsibleResult",
    "AnsibleRun",
    "AnsibleRunner",
    "InventoryTarget",
    "GENERIC_SECRET_FIELDS",
    "MaterializedInventory",
    "RUN_OUTCOMES",
    "extract_fact",
    "extract_json_block",
    "inventory_target",
    "playbook_environment",
    "read_fact",
    "redact_ansible_output",
]
