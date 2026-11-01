"""SSH access to a delivered machine, as a scenario's buyer exercises it.

Domain-neutral: a scenario hands it where to connect, as whom, and with which
key, and it reports what a connection shows. It knows nothing of how the
machine was sold or delivered.

One ``SshSession`` lives for one scenario run. Its owner-only directory holds
the keys it generates and its own ``known_hosts``, and is removed when the run
ends. A host's key is trusted on first use within the run and only for the run:
every later connection checks it against that one file, so a host presenting
another key mid-run fails rather than being trusted again. Where the operator
knows the host key, the session pins that key before first contact; an external
known_hosts file is read strictly and is never rewritten or removed.

Connections use the system ``ssh`` in batch mode, offering only the key they
are given (``IdentitiesOnly``) and reading no user or system SSH configuration,
so what a connection proves does not depend on the operator's machine. A
connection that cannot be made is retried within a bound, because a freshly
created guest refuses connections, and then the key it has not installed yet,
until its first boot and cloud-init's reboot are done.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Thread

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from e2e_harness.ssh_host_key import canonical_host_public_key

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


ACCESS_PROBE_OUTPUT = "arkhai-bare-metal-access-ok"


class SshOutcome(enum.Enum):
    """What one SSH attempt proved about the tenant's access."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


def classify_ssh(returncode: int, stdout: str, stderr: str) -> SshOutcome:
    """Read one attempt as access accepted or refused by authentication.

    SSH exits 255 for its own failures, a refused connection, a timeout, and a
    host-key mismatch among them, so the exit status alone cannot tell a revoked
    key from a host that could not be reached. Only the server's refusal of the
    public key proves revocation; every other failure is raised, never counted
    as revoked.
    """
    if returncode == 0 and stdout == ACCESS_PROBE_OUTPUT:
        return SshOutcome.ACCEPTED
    if returncode == 255 and "Permission denied" in stderr and "publickey" in stderr:
        return SshOutcome.REFUSED
    raise SshAccessError(
        f"SSH attempt proved neither access nor revocation: exit {returncode}, "
        f"stderr {stderr.strip()[-300:]!r}"
    )


class HostKeyChanged(SshAccessError):
    """A host presented another key than the one first seen in this run."""


@dataclass(frozen=True)
class SshKey:
    """A key offered during a run, generated there or supplied by its owner."""

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


def _failure(result: subprocess.CompletedProcess[str] | None) -> str:
    """What a failed attempt reported, or that it ran out of time."""
    return "the connection timed out" if result is None else result.stderr.strip()


def _fingerprint(key_base64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(key_base64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class SshHeartbeat:
    """One uninterrupted SSH process, drained while the scenario does other work.

    Local arrival times catch a stalled connection; remote timestamps also catch
    a remote pause hidden by buffered delivery. No reconnect can erase a gap.
    """

    def __init__(self, process: subprocess.Popen[str], *, clock: Callable[[], float]) -> None:
        self.process = process
        self._clock = clock
        self._condition = Condition()
        self._last_arrival: float | None = None
        self._last_remote: float | None = None
        self._longest_gap = 0.0
        self.sample_count = 0
        self._error: str | None = None
        self._ended = False
        self._reader = Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                with self._condition:
                    try:
                        remote = float(line.strip())
                        if not math.isfinite(remote):
                            raise ValueError("nonfinite timestamp")
                        now = self._clock()
                        if self._last_remote is not None:
                            assert self._last_arrival is not None
                            if remote < self._last_remote:
                                raise ValueError("remote time moved backwards")
                            self._longest_gap = max(
                                self._longest_gap, remote - self._last_remote,
                                now - self._last_arrival,
                            )
                        self._last_arrival, self._last_remote = now, remote
                        self.sample_count += 1
                    except ValueError as error:
                        self._error = f"invalid heartbeat timestamp: {error}"
                    self._condition.notify_all()
        finally:
            with self._condition:
                self._ended = True
                self._condition.notify_all()

    def wait_ready(self, *, min_samples: int = 1, timeout: float = CONNECT_TIMEOUT_SECONDS + COMMAND_SECONDS) -> None:
        """Require a first observation from this exact process within a bound."""
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self.sample_count >= min_samples or self._ended or self._error,
                timeout=timeout,
            )
            if not ready or self.sample_count < min_samples or self._error:
                raise SshAccessError(self._error or "heartbeat produced no timestamp before ending or timing out")
        self.assert_alive()

    @property
    def running(self) -> bool:
        return self.process.poll() is None and not self._ended

    @property
    def longest_gap(self) -> float:
        with self._condition:
            if self._last_arrival is None:
                return float("inf")
            return max(self._longest_gap, self._clock() - self._last_arrival)

    def assert_alive(self, *, max_gap: float = 5.0) -> None:
        """Require the original process still alive and no excessive heartbeat gap."""
        if self._error:
            raise SshAccessError(self._error)
        if not self.running:
            raise SshAccessError(f"heartbeat SSH process ended (exit={self.process.poll()})")
        gap = self.longest_gap
        if gap > max_gap:
            raise SshAccessError(f"heartbeat longest gap {gap:.3f}s exceeds {max_gap:.3f}s")

    def close(self) -> None:
        """End only this monitor's process and reap it before removing run keys."""
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self._reader.join(timeout=5)
        if self._reader.is_alive():
            raise SshAccessError("heartbeat reader did not stop after its process exited")
        if self.process.stdout is not None:
            self.process.stdout.close()


class SshSession:
    """One run's keys, known hosts, and connections."""

    def __init__(
        self,
        directory: Path,
        *,
        ssh: str = "ssh",
        host_key: str | None = None,
        known_hosts_file: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        connect_retry_seconds: float = CONNECT_RETRY_SECONDS,
        attempt_seconds: float = CONNECT_TIMEOUT_SECONDS + COMMAND_SECONDS,
    ) -> None:
        self.directory = directory
        if host_key is not None and known_hosts_file is not None:
            raise ValueError("select a pinned host key or known_hosts file, not both")
        self._pinned_host_key = canonical_host_public_key(host_key) if host_key is not None else None
        self._pinned = host_key is not None or known_hosts_file is not None
        self.known_hosts = known_hosts_file if known_hosts_file is not None else directory / "known_hosts"
        if known_hosts_file is not None and not known_hosts_file.is_file():
            raise ValueError("pinned known_hosts file does not exist")
        self._ssh = ssh
        self._clock = clock
        self._sleep = sleep
        self._connect_retry_seconds = connect_retry_seconds
        self._attempt_seconds = attempt_seconds
        self._heartbeats: list[SshHeartbeat] = []

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
        self._pin(endpoint)
        return [
            self._ssh,
            "-F", "/dev/null",
            "-i", str(key.private_key),
            "-p", str(endpoint.port),
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}",
            "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=yes" if self._pinned else "StrictHostKeyChecking=accept-new",
            "-o", "ControlMaster=no",
            "-o", "ControlPath=none",
            "-o", "PreferredAuthentications=publickey",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "UpdateHostKeys=no",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "HashKnownHosts=no",
            f"{endpoint.user}@{endpoint.host}",
            command,
        ]

    def _pin(self, endpoint: SshEndpoint) -> None:
        """Bind the operator's key to each delivered port before its first attempt."""
        if self._pinned_host_key is None:
            return
        name = endpoint.host if endpoint.port == 22 else f"[{endpoint.host}]:{endpoint.port}"
        lines = self.known_hosts.read_text().splitlines() if self.known_hosts.exists() else []
        matching = [line.split() for line in lines if line.split() and name in line.split()[0].split(",")]
        wanted = self._pinned_host_key.split()
        if matching:
            if any(fields[1:3] != wanted for fields in matching):
                raise HostKeyChanged(f"{name} already has another key pinned in this run")
            return
        with self.known_hosts.open("a") as stream:
            stream.write(f"{name} {self._pinned_host_key}\n")
        self.known_hosts.chmod(0o600)

    def heartbeat(self, endpoint: SshEndpoint, key: SshKey) -> SshHeartbeat:
        """Start one established session that stays open across other proxy changes."""
        command = "while :; do date +%s; sleep 1; done"
        argv = self.argv(endpoint, key, command)
        argv[-2:-2] = ["-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=3"]
        error_path = self.directory / f"heartbeat-{len(self._heartbeats)}.stderr"
        with error_path.open("w") as errors:
            process = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=errors, text=True, bufsize=1,
            )
        monitor = SshHeartbeat(process, clock=self._clock)
        self._heartbeats.append(monitor)
        try:
            monitor.wait_ready()
        except BaseException:
            monitor.close()
            raise
        return monitor

    def close(self) -> None:
        """Close every owned heartbeat, including one a failed stage left open."""
        failures = []
        for heartbeat in self._heartbeats:
            try:
                heartbeat.close()
            except Exception as error:
                failures.append(str(error))
        if failures:
            raise SshAccessError("; ".join(failures))

    def _attempt(
        self,
        endpoint: SshEndpoint,
        key: SshKey,
        command: str,
        *,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str] | None:
        """One ``ssh`` run, or ``None`` when it ran out of time.

        ``timeout`` defaults to a full attempt's time. ``ssh`` itself fails
        within its ``ConnectTimeout`` when the host does not answer, so an
        attempt runs out of time only once the host has answered and the
        connection has not finished.
        """
        try:
            result = subprocess.run(
                self.argv(endpoint, key, command),
                capture_output=True,
                text=True,
                timeout=self._attempt_seconds if timeout is None else timeout,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode == _SSH_FAILED and any(
            marker in result.stderr for marker in _HOST_KEY_REFUSED
        ):
            raise HostKeyChanged(
                f"{endpoint.host}:{endpoint.port} presented another host key than "
                f"{self.host_key_fingerprint(endpoint)!r}, the one first seen in this "
                f"run: {result.stderr.strip()}"
            )
        return result

    def _pause(self, deadline: float) -> None:
        """Wait the retry interval, or what is left before ``deadline`` if less."""
        self._sleep(max(0.0, min(RETRY_INTERVAL_SECONDS, deadline - self._clock())))

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
        closes. The window bounds when the last attempt starts, not when it
        ends: an attempt keeps its full time, since cutting a connected command
        short would fail it for a reason unrelated to connecting. A host key
        other than the one this run trusted fails at once, and so does the
        command failing once connected.
        """
        first_contact = self.host_key_fingerprint(endpoint) is None
        deadline = self._clock() + self._connect_retry_seconds
        while True:
            result = self._attempt(endpoint, key, command)
            if result is not None and result.returncode != _SSH_FAILED:
                break
            if self._clock() >= deadline:
                raise SshAccessError(
                    f"could not connect to {endpoint.user}@{endpoint.host}:"
                    f"{endpoint.port} within {self._connect_retry_seconds}s: "
                    f"{_failure(result)}"
                )
            self._pause(deadline)
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
        """Assert a connection with ``key`` is refused within ``bound``, and return why.

        Refused means ``ssh`` itself failed: the host refused the connection or
        the key, or ``ssh``'s own ``ConnectTimeout`` expired. An attempt that
        runs out of time is no refusal: given its full time it shows that
        something answered and the connection had not finished, since ``ssh``
        gives up within its ``ConnectTimeout`` when nothing answers, and cut
        short by the bound it shows nothing. It is retried like an accepted
        connection. The refusal must be seen by the time the bound closes: no
        attempt starts after it, an attempt is cut short where it would run past
        it, and a refusal that returns later fails. A connection still accepted,
        or whose last attempt had not finished, when the bound closes fails.
        """
        deadline = self._clock() + bound
        target = f"{endpoint.user}@{endpoint.host}:{endpoint.port}"
        unfinished = False
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                if unfinished:
                    raise SshAccessError(
                        f"{target} was not shown to refuse {key.private_key.name} "
                        f"within {bound}s: the last attempt had not finished when it "
                        f"ran out of time"
                    )
                raise SshAccessError(
                    f"{target} still accepted {key.private_key.name} after {bound}s"
                )
            limit = min(self._attempt_seconds, remaining)
            result = self._attempt(endpoint, key, "true", timeout=limit)
            unfinished = result is None
            if result is not None and result.returncode == _SSH_FAILED:
                reason = result.stderr.strip() or "refused"
                if self._clock() > deadline:
                    raise SshAccessError(
                        f"{target} refused {key.private_key.name} only after {bound}s: "
                        f"{reason}"
                    )
                log.info("%s refused the connection: %s", target, reason)
                return reason
            self._pause(deadline)

    def assert_key_refused(self, endpoint: SshEndpoint, key: SshKey) -> str:
        """Assert the host refuses ``key`` for ``endpoint.user``, and returns why.

        Stricter than ``assert_refused``: the host must be reached and must
        deny the key. A connection that cannot be made says nothing about the
        key, so it is retried within the connect window like any other, and
        fails at its end; as in ``run``, the window bounds when the last
        attempt starts.
        """
        deadline = self._clock() + self._connect_retry_seconds
        while True:
            result = self._attempt(endpoint, key, "true")
            if result is not None and result.returncode != _SSH_FAILED:
                raise SshAccessError(
                    f"{endpoint.user}@{endpoint.host}:{endpoint.port} accepted "
                    f"{key.private_key.name}, which it should refuse"
                )
            if result is not None and "Permission denied" in result.stderr and "publickey" in result.stderr:
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
                    f"{self._connect_retry_seconds}s: {_failure(result)}"
                )
            self._pause(deadline)

    def access_outcome(self, endpoint: SshEndpoint, key: SshKey) -> SshOutcome:
        """One pinned-key access probe; only authenticated key refusal is revocation.

        This performs no reconnect or retry: a transport failure remains a failed
        observation, preserving an installed buyer scenario's strict judgment.
        """
        result = self._attempt(endpoint, key, f"printf {ACCESS_PROBE_OUTPUT}", timeout=30)
        if result is None:
            raise SshAccessError("SSH attempt proved neither access nor revocation: timed out")
        return classify_ssh(result.returncode, result.stdout, result.stderr)

    def probe(self, endpoint: SshEndpoint, key: SshKey) -> GuestShape:
        """The user, vCPU count, memory, and root disk a connection shows."""
        return parse_probe(self.run(endpoint, key, _PROBE))


@contextmanager
def ssh_session(**options) -> Iterator[SshSession]:
    """A run's ``SshSession`` in an owner-only directory removed when the run ends."""
    directory = Path(tempfile.mkdtemp(prefix="e2e-ssh-"))
    try:
        directory.chmod(0o700)
        session = SshSession(directory, **options)
        try:
            yield session
        except BaseException:
            try:
                session.close()
            except Exception as error:
                log.warning("Could not close the run's heartbeat sessions: %s", error)
            raise
        else:
            session.close()
    finally:
        # Reported rather than raised, so a failure here cannot hide the run's
        # own outcome; the directory holds private keys, so it is never silent.
        try:
            shutil.rmtree(directory)
        except OSError as error:
            log.warning("Could not remove the run's SSH keys at %s: %s", directory, error)
