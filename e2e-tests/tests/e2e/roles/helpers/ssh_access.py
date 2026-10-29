"""SSH access to a delivered machine, as a scenario's buyer exercises it.

Domain-neutral: a scenario hands it where to connect, as whom, and with which
key, and it reports what a connection shows. It knows nothing of how the
machine was sold or delivered.

One ``SshSession`` lives for one scenario run. Its owner-only directory holds
the keys it generates and its own ``known_hosts``, and is removed when the run
ends. A host's key is trusted on first use within the run and only for the run:
every later connection checks it against that one file, so a host presenting
another key mid-run fails rather than being trusted again. The delivered
machine's host key is not delivered with its access, so nothing earlier could
pin it.

Connections use the system ``ssh`` in batch mode, offering only the key they
are given (``IdentitiesOnly``) and reading no user or system SSH configuration,
so what a connection proves does not depend on the operator's machine. A
connection that cannot be made is retried within a bound, because a freshly
created guest refuses connections, and then the key it has not installed yet,
until its first boot and cloud-init's reboot are done.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

log = logging.getLogger(__name__)

#: How long one connection attempt waits for the host to answer.
CONNECT_TIMEOUT_SECONDS = 10
#: How long a connection that cannot be made is retried: a new guest's first
#: boot, its cloud image's setup, and cloud-init's reboot all happen inside it.
CONNECT_RETRY_SECONDS = 600
#: The pause between attempts within a retry or refusal window.
RETRY_INTERVAL_SECONDS = 5
#: How long a connection that should be refused has to be refused within: an
#: unrelated key at once, and delivered access once teardown has removed it.
REFUSAL_BOUND_SECONDS = 120
#: How far below the negotiated memory a guest's ``MemTotal`` may fall, as a
#: fraction of it. The guest kernel keeps some memory for itself, so the two
#: are never equal; a guest further short than this was given less than was
#: sold.
MEMORY_SHORTFALL_TOLERANCE = 0.05
#: How long a command may run once connected, beyond the connection itself.
COMMAND_SECONDS = 60

#: `ssh` exits with this status when it, rather than the remote command, failed:
#: no connection, authentication refused, or a host key it would not accept.
_SSH_FAILED = 255
_HOST_KEY_REFUSED = ("REMOTE HOST IDENTIFICATION HAS CHANGED", "Host key verification failed")
_GIB = 1024**3

#: Prints the guest's user, vCPU count, memory, and root disk, one labelled line
#: each. The root disk is the whole device holding `/`, not its partition or
#: filesystem, which are smaller than the disk the guest was given.
_PROBE = (
    "printf 'user=%s\\n' \"$(id -un)\"; "
    "printf 'vcpus=%s\\n' \"$(nproc)\"; "
    "grep -m1 '^MemTotal:' /proc/meminfo; "
    "src=$(findmnt -no SOURCE /); "
    "parent=$(lsblk -no PKNAME \"$src\" 2>/dev/null | head -n1); "
    "printf 'root_disk_bytes=%s\\n' \"$(lsblk -bdno SIZE \"/dev/${parent:-${src#/dev/}}\")\""
)


class SshAccessError(AssertionError):
    """What a scenario expected of an SSH connection did not happen."""


class HostKeyChanged(SshAccessError):
    """A host presented another key than the one first seen in this run."""


@dataclass(frozen=True)
class SshKey:
    """A key pair generated for this run."""

    private_key: Path
    #: The OpenSSH public line, as a buyer negotiates it.
    public_line: str


@dataclass(frozen=True)
class SshEndpoint:
    """Where to connect, and as whom."""

    host: str
    port: int
    user: str


@dataclass(frozen=True)
class GuestShape:
    """What a connection shows of the machine behind it."""

    user: str
    vcpu_count: int
    memory_gib: float
    root_disk_gib: float


def memory_within_tolerance(memory_gib: float, ram_gb: int) -> bool:
    """Whether a guest's memory is the negotiated amount, less what its kernel keeps."""
    return ram_gb * (1 - MEMORY_SHORTFALL_TOLERANCE) <= memory_gib <= ram_gb


def parse_probe(output: str) -> GuestShape:
    """The shape the probe command printed."""
    values: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("MemTotal:"):
            fields = line.split()
            if len(fields) != 3:
                raise SshAccessError(f"MemTotal is not an amount in kB: {line!r}")
            amount, unit = fields[1:]
            if unit != "kB":
                raise SshAccessError(f"MemTotal is in {unit!r}, not kB: {line!r}")
            values["memory_kib"] = amount
        elif "=" in line:
            name, _, value = line.partition("=")
            values[name] = value
    missing = {"user", "vcpus", "memory_kib", "root_disk_bytes"} - {
        name for name, value in values.items() if value
    }
    if missing:
        raise SshAccessError(f"the probe reported no {sorted(missing)}: {output!r}")
    return GuestShape(
        user=values["user"],
        vcpu_count=int(values["vcpus"]),
        memory_gib=int(values["memory_kib"]) * 1024 / _GIB,
        root_disk_gib=int(values["root_disk_bytes"]) / _GIB,
    )


def _fingerprint(key_base64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(key_base64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class SshSession:
    """One run's keys, known hosts, and connections."""

    def __init__(
        self,
        directory: Path,
        *,
        ssh: str = "ssh",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        connect_retry_seconds: float = CONNECT_RETRY_SECONDS,
        attempt_seconds: float = CONNECT_TIMEOUT_SECONDS + COMMAND_SECONDS,
    ) -> None:
        self.directory = directory
        self.known_hosts = directory / "known_hosts"
        self._ssh = ssh
        self._clock = clock
        self._sleep = sleep
        self._connect_retry_seconds = connect_retry_seconds
        self._attempt_seconds = attempt_seconds

    # -- keys ---------------------------------------------------------------

    def new_key(self, name: str) -> SshKey:
        """Generate an ed25519 key pair, its private half readable by its owner alone."""
        private = Ed25519PrivateKey.generate()
        path = self.directory / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                private.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
            )
        public = private.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
        return SshKey(private_key=path, public_line=f"{public.decode()} e2e-{name}")

    # -- connections ------------------------------------------------------

    def argv(self, endpoint: SshEndpoint, key: SshKey, command: str) -> list[str]:
        """The ``ssh`` invocation for one attempt."""
        return [
            self._ssh,
            "-F", "/dev/null",
            "-i", str(key.private_key),
            "-p", str(endpoint.port),
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
            "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "HashKnownHosts=no",
            f"{endpoint.user}@{endpoint.host}",
            command,
        ]

    def _attempt(
        self, endpoint: SshEndpoint, key: SshKey, command: str
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                self.argv(endpoint, key, command),
                capture_output=True,
                text=True,
                timeout=self._attempt_seconds,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                [], _SSH_FAILED, "", "the connection timed out"
            )
        if result.returncode == _SSH_FAILED and any(
            marker in result.stderr for marker in _HOST_KEY_REFUSED
        ):
            raise HostKeyChanged(
                f"{endpoint.host}:{endpoint.port} presented another host key than "
                f"{self.host_key_fingerprint(endpoint)!r}, the one first seen in this "
                f"run: {result.stderr.strip()}"
            )
        return result

    def host_key_fingerprint(self, endpoint: SshEndpoint) -> str | None:
        """The SHA256 fingerprint of the host key this run trusted for ``endpoint``."""
        if not self.known_hosts.exists():
            return None
        name = endpoint.host if endpoint.port == 22 else f"[{endpoint.host}]:{endpoint.port}"
        for line in self.known_hosts.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 3 and name in fields[0].split(","):
                return _fingerprint(fields[2])
        return None

    def run(self, endpoint: SshEndpoint, key: SshKey, command: str) -> str:
        """Run ``command`` as ``endpoint.user`` and return its output.

        A connection that cannot be made is retried until the retry window
        closes. A host key other than the one this run trusted fails at once,
        and so does the command failing once connected.
        """
        first_contact = self.host_key_fingerprint(endpoint) is None
        deadline = self._clock() + self._connect_retry_seconds
        while True:
            result = self._attempt(endpoint, key, command)
            if result.returncode != _SSH_FAILED:
                break
            if self._clock() >= deadline:
                raise SshAccessError(
                    f"could not connect to {endpoint.user}@{endpoint.host}:"
                    f"{endpoint.port} within {self._connect_retry_seconds}s: "
                    f"{result.stderr.strip()}"
                )
            self._sleep(RETRY_INTERVAL_SECONDS)
        if first_contact:
            log.info(
                "Trusting %s:%s's host key for this run: %s",
                endpoint.host, endpoint.port, self.host_key_fingerprint(endpoint),
            )
        if result.returncode != 0:
            raise SshAccessError(
                f"{command!r} failed on {endpoint.host}:{endpoint.port} with exit "
                f"{result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout

    def assert_refused(
        self,
        endpoint: SshEndpoint,
        key: SshKey,
        *,
        bound: float = REFUSAL_BOUND_SECONDS,
    ) -> str:
        """Assert a connection with ``key`` is refused, or times out, within ``bound``.

        Returns why it was refused. A connection still accepted when the bound
        closes fails.
        """
        deadline = self._clock() + bound
        while True:
            result = self._attempt(endpoint, key, "true")
            if result.returncode == _SSH_FAILED:
                reason = result.stderr.strip() or "refused"
                log.info(
                    "%s@%s:%s refused the connection: %s",
                    endpoint.user, endpoint.host, endpoint.port, reason,
                )
                return reason
            if self._clock() >= deadline:
                raise SshAccessError(
                    f"{endpoint.user}@{endpoint.host}:{endpoint.port} still accepted "
                    f"{key.private_key.name} after {bound}s"
                )
            self._sleep(RETRY_INTERVAL_SECONDS)

    def assert_key_refused(self, endpoint: SshEndpoint, key: SshKey) -> str:
        """Assert the host refuses ``key`` for ``endpoint.user``, and returns why.

        Stricter than ``assert_refused``: the host must be reached and must
        deny the key. A connection that cannot be made says nothing about the
        key, so it is retried within the connect window like any other, and
        fails at its end.
        """
        deadline = self._clock() + self._connect_retry_seconds
        while True:
            result = self._attempt(endpoint, key, "true")
            if result.returncode != _SSH_FAILED:
                raise SshAccessError(
                    f"{endpoint.user}@{endpoint.host}:{endpoint.port} accepted "
                    f"{key.private_key.name}, which it should refuse"
                )
            if "Permission denied" in result.stderr:
                reason = result.stderr.strip()
                log.info(
                    "%s@%s:%s refused %s: %s",
                    endpoint.user, endpoint.host, endpoint.port,
                    key.private_key.name, reason,
                )
                return reason
            if self._clock() >= deadline:
                raise SshAccessError(
                    f"could not reach {endpoint.host}:{endpoint.port} to show it "
                    f"refuses {key.private_key.name} within "
                    f"{self._connect_retry_seconds}s: {result.stderr.strip()}"
                )
            self._sleep(RETRY_INTERVAL_SECONDS)

    def probe(self, endpoint: SshEndpoint, key: SshKey) -> GuestShape:
        """The user, vCPU count, memory, and root disk a connection shows."""
        return parse_probe(self.run(endpoint, key, _PROBE))


@contextmanager
def ssh_session(**options) -> Iterator[SshSession]:
    """A run's ``SshSession`` in an owner-only directory removed when the run ends."""
    directory = Path(tempfile.mkdtemp(prefix="e2e-ssh-"))
    try:
        directory.chmod(0o700)
        yield SshSession(directory, **options)
    finally:
        # Reported rather than raised, so a failure here cannot hide the run's
        # own outcome; the directory holds private keys, so it is never silent.
        try:
            shutil.rmtree(directory)
        except OSError as error:
            log.warning("Could not remove the run's SSH keys at %s: %s", directory, error)
