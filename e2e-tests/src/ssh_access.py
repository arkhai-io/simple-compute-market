"""SSH access probing for whole-host lease evidence.

Revocation evidence is the one assertion in a whole-host scenario that is easy
to satisfy for the wrong reason. `ssh` exits 255 for a rejected key, a dropped
tunnel, a dead host, an unresolvable name, and a changed host key alike, so a
bare non-zero exit proves only that the command did not run.

This module separates the two questions the scenario actually asks: did the
authority reject this key, and is the host still there to reject it.
"""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AccessVerdict(str, Enum):
    GRANTED = "granted"
    KEY_REJECTED = "key_rejected"
    HOST_UNREACHABLE = "host_unreachable"
    HOST_KEY_CHANGED = "host_key_changed"
    # The lease credential could not be read or parsed locally, so the server
    # never judged it. Indistinguishable from revocation by exit status alone.
    LOCAL_KEY_ERROR = "local_key_error"
    # Authentication succeeded and the remote command failed. Proves the
    # opposite of revocation.
    REMOTE_COMMAND_FAILED = "remote_command_failed"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class SshProbeResult:
    returncode: int
    stdout: str
    stderr: str


# OpenSSH's own denial lines. A bare "permission denied" is not usable: the
# remote command emits it too, and so does a failed local key load.
_KEY_REJECTED_MARKERS = (
    "permission denied (",
    "no supported authentication methods",
    "too many authentication failures",
)

# Emitted when ssh cannot read or parse the identity it was given. It then
# continues and still ends in a publickey denial, which is why this is checked
# before the denial markers.
_LOCAL_KEY_ERROR_MARKERS = (
    "load key",
    "invalid format",
    "bad permissions",
    "unprotected private key file",
    "no such identity",
    "error loading key",
    "key_load_public",
)

# ssh exits 255 for its own failures and passes through the remote command's
# status otherwise.
_SSH_TRANSPORT_EXIT = 255

_UNREACHABLE_MARKERS = (
    "connection timed out",
    "connection refused",
    "no route to host",
    "network is unreachable",
    "could not resolve hostname",
    "name or service not known",
    "operation timed out",
    "kex_exchange_identification",
    "connection closed by",
    "broken pipe",
)

# Proof that the server accepted a credential during this attempt.
_AUTHENTICATED_MARKERS = (
    "authenticated to",
    "authentication succeeded",
    "authenticated using",
)

_HOST_KEY_MARKERS = (
    "host identification has changed",
    "host key verification failed",
    "remote host identification",
)


def classify_ssh_probe(
    result: SshProbeResult,
    *,
    offered_fingerprint: str,
) -> AccessVerdict:
    """Classify one probe against the key that was supposed to be offered.

    The fingerprint is required, not optional: without it a denial only shows
    that *some* attempt failed, which is satisfied by never presenting the lease
    key at all. Anything unrecognised stays indeterminate — folding it into
    ``KEY_REJECTED`` is the defect this classification exists to prevent.
    """
    stderr = result.stderr.lower()

    # Checked before the denial markers: ssh reports an unreadable or malformed
    # identity and then still ends in an ordinary publickey denial, which would
    # otherwise read as revocation of a key the server never saw.
    if any(marker in stderr for marker in _LOCAL_KEY_ERROR_MARKERS):
        return AccessVerdict.LOCAL_KEY_ERROR

    if result.returncode == 0:
        return AccessVerdict.GRANTED

    if any(marker in stderr for marker in _HOST_KEY_MARKERS):
        return AccessVerdict.HOST_KEY_CHANGED
    if any(marker in stderr for marker in _UNREACHABLE_MARKERS):
        return AccessVerdict.HOST_UNREACHABLE

    # A trace that shows the session authenticated cannot be revocation,
    # whatever it exits with. A forced command or shell startup script can exit
    # 255 and print denial-shaped text, and ssh passes that status through.
    if any(marker in stderr for marker in _AUTHENTICATED_MARKERS):
        return AccessVerdict.REMOTE_COMMAND_FAILED

    if result.returncode != _SSH_TRANSPORT_EXIT:
        return AccessVerdict.REMOTE_COMMAND_FAILED

    if any(marker in stderr for marker in _KEY_REJECTED_MARKERS):
        if not _offered(result.stderr, offered_fingerprint):
            return AccessVerdict.INDETERMINATE
        return AccessVerdict.KEY_REJECTED
    return AccessVerdict.INDETERMINATE


def _offered(stderr: str, fingerprint: str) -> bool:
    """Whether an actual offering line names this exact key.

    Scoped to the offering line itself. OpenSSH also prints `Will attempt key:`
    for identities it merely intends to try, so a fingerprint appearing anywhere
    in the trace does not mean that key was the one presented.
    """
    if not fingerprint:
        return False
    for line in stderr.splitlines():
        lowered = line.lower()
        if "offering public key" in lowered and fingerprint in line:
            return True
    return False


def buyer_ssh_argv(
    *,
    host: str,
    port: int,
    username: str,
    private_key_file: str,
    known_hosts_file: str,
    strict_host_key_checking: str,
    command: str,
    verbose: bool = True,
) -> list[str]:
    """Build an argv that can only authenticate with *private_key_file*.

    The buyer session must not be able to succeed through an agent, a default
    identity, a password, or an operator `ssh_config` entry: any of those would
    let an unrelated credential answer the challenge, and a scenario that
    proves "someone can log in" proves nothing about the lease.
    """
    if strict_host_key_checking not in {"yes", "accept-new"}:
        raise ValueError(
            "host key checking must stay enabled; use 'accept-new' to pin on "
            "first contact and 'yes' afterwards"
        )
    return [
        "ssh",
        # -v prints which identity was offered, which is what lets a denial be
        # attributed to the lease key rather than to no key at all.
        *(["-v"] if verbose else []),
        # Ignore any operator ssh_config: it may supply an alias, a proxy, or
        # another identity for this host.
        "-F",
        "/dev/null",
        # IdentityFile=none must precede -i. OpenSSH silently drops an
        # unreadable -i identity and then falls back to the invoking account's
        # default ~/.ssh/id_* list, which on an operator workstation is the
        # management keys. Verified with `ssh -G`: without this line an absent
        # -i path expands to that default list even with IdentitiesOnly=yes.
        "-o",
        "IdentityFile=none",
        "-i",
        private_key_file,
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "IdentityAgent=none",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        f"StrictHostKeyChecking={strict_host_key_checking}",
        "-o",
        f"UserKnownHostsFile={known_hosts_file}",
        # The system known-hosts files stay active under -F /dev/null, so a key
        # already trusted there would satisfy strict checking that the pinned
        # file never authorised.
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        f"{username}@{host}",
        command,
    ]


@dataclass(frozen=True)
class LeaseKeyMaterial:
    """The buyer's private key, proven loadable and pinned before any effect.

    A public fingerprint is not this. `ssh-keygen -l` reads the public half and
    succeeds on a public-only or encrypted file, so a run could "freeze" material
    that can never authenticate — and a later denial would then look exactly like
    revocation. What is pinned here is that the *private* key loads unattended,
    which public key it derives, and the exact bytes on disk.
    """

    private_key_file: Path
    public_key: str
    fingerprint: str
    digest: str


def _derived_public_key(private_key_file: Path) -> str:
    """Derive the public key from the private half, unattended.

    `-P ''` supplies an empty passphrase rather than prompting, so an encrypted
    key fails here instead of blocking or silently passing. A public-only file
    fails too, which is the point.
    """
    completed = subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(private_key_file)],
        capture_output=True,
        text=True,
        timeout=30,
        env=buyer_probe_environment(),
    )
    if completed.returncode != 0:
        raise ValueError(
            f"lease key {private_key_file} is not an unencrypted, loadable "
            "private key usable without a prompt"
        )
    derived = completed.stdout.strip()
    if not derived:
        raise ValueError(f"lease key {private_key_file} derived no public key")
    return derived


def _key_body(public_key: str) -> str:
    """The algorithm and base64 body, without comment or options."""
    fields = public_key.split()
    if len(fields) < 2:
        raise ValueError("public key material is not in authorized-keys form")
    return f"{fields[0]} {fields[1]}"


def freeze_lease_key(
    private_key_file: Path,
    *,
    expected_public_key: str | None = None,
) -> LeaseKeyMaterial:
    """Prove the private key is usable and pin it.

    When *expected_public_key* is given — the public key the purchase actually
    requested — the derived key must match it, so the run cannot authenticate
    with a credential the seller was never asked to authorize.
    """
    path = Path(private_key_file)
    if not path.is_file():
        raise ValueError(f"lease key {path} is not a file")
    raw = path.read_bytes()
    derived = _derived_public_key(path)

    if expected_public_key is not None:
        if _key_body(derived) != _key_body(expected_public_key):
            raise ValueError(
                "lease private key does not correspond to the public key the "
                "purchase requested"
            )

    listed = subprocess.run(
        ["ssh-keygen", "-l", "-f", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        env=buyer_probe_environment(),
    )
    fingerprint = next(
        (f for f in listed.stdout.split() if f.startswith("SHA256:")), ""
    )
    if listed.returncode != 0 or not fingerprint:
        raise ValueError(f"could not read a fingerprint for lease key {path}")

    return LeaseKeyMaterial(
        private_key_file=path,
        public_key=derived,
        fingerprint=fingerprint,
        digest=hashlib.sha256(raw).hexdigest(),
    )


def assert_lease_key_unchanged(material: LeaseKeyMaterial) -> None:
    """Re-prove usability and byte-identity before an attempt.

    Both matter. Equal fingerprints would still pass if the private file were
    replaced by its own public half, which is exactly the substitution that
    turns a denial into a false revocation result.
    """
    current = freeze_lease_key(material.private_key_file)
    if (
        current.digest != material.digest
        or current.fingerprint != material.fingerprint
        or current.public_key != material.public_key
    ):
        raise AssertionError(
            "lease key changed during the run, so no attempt after this point "
            "is evidence about the key that was granted"
        )


def buyer_probe_environment() -> dict[str, str]:
    """A minimal environment for the buyer's SSH attempts.

    The operator's environment carries agent sockets and credential paths.
    Inheriting it would let an unrelated credential answer the challenge, so
    the probe is given an allowlist rather than a filtered copy: a filter has
    to predict every name worth removing, an allowlist does not.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C"),
        # A real HOME is deliberately absent: ssh must not resolve any
        # per-account default identity, config, or known-hosts file.
        "HOME": "/nonexistent",
    }


def run_ssh_probe(
    argv: list[str],
    *,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> SshProbeResult:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env if env is not None else buyer_probe_environment(),
        )
    except subprocess.TimeoutExpired:
        # A client-side timeout is a transport observation, not an auth one.
        return SshProbeResult(
            returncode=255, stdout="", stderr="ssh: connection timed out (client)"
        )
    return SshProbeResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def tcp_reachable(host: str, port: int, *, timeout: float = 10.0) -> bool:
    """Whether the SSH endpoint still accepts a connection.

    Used to corroborate a `KEY_REJECTED` verdict: the rejection is only
    meaningful while the host is still answering on the same endpoint.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class HostKeyTrust:
    """Where this run's belief about the host's identity came from.

    Trust on first use is not identity verification: the first connection
    accepts whatever key answers, so a party already on the path is recorded
    as the host and every later probe then agrees with it. It is still worth
    pinning, because it detects a key that changes mid-run, but a scenario
    that reports it as a verified identity overstates its evidence.
    """

    known_hosts_file: Path
    independently_verified: bool
    strict_host_key_checking: str
    caveat: str


_FIRST_USE_CAVEAT = (
    "host identity was accepted on first use and is not independently "
    "verified; supply an operator-managed known_hosts file to verify it"
)


def resolve_host_key_trust(
    *,
    known_hosts_file: Path | None,
    session_known_hosts: Path | None = None,
) -> HostKeyTrust:
    """Prefer an operator-managed known_hosts file over first-use acceptance."""
    if known_hosts_file is not None:
        path = Path(known_hosts_file)
        if not path.is_file():
            raise ValueError(
                f"known_hosts file {path} does not exist; refusing to fall back "
                "to first-use acceptance, which would silently weaken the check"
            )
        if not path.read_text().strip():
            raise ValueError(
                f"known_hosts file {path} is empty, so it authorises no host key"
            )
        return HostKeyTrust(
            known_hosts_file=path,
            independently_verified=True,
            strict_host_key_checking="yes",
            caveat="",
        )
    if session_known_hosts is None:
        raise ValueError("a session known_hosts path is required for first-use trust")
    return HostKeyTrust(
        known_hosts_file=Path(session_known_hosts),
        independently_verified=False,
        strict_host_key_checking="accept-new",
        caveat=_FIRST_USE_CAVEAT,
    )


__all__ = [
    "AccessVerdict",
    "HostKeyTrust",
    "LeaseKeyMaterial",
    "assert_lease_key_unchanged",
    "buyer_probe_environment",
    "freeze_lease_key",
    "SshProbeResult",
    "buyer_ssh_argv",
    "classify_ssh_probe",
    "resolve_host_key_trust",
    "run_ssh_probe",
    "tcp_reachable",
]
