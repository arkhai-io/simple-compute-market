"""Observe one SSH host key without starting a session or sending login credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .runner import InventoryTarget, _write_owner_only


_KEY_LINE = re.compile(r"^debug1: Server host key: ([A-Za-z0-9@_.+-]+) (SHA256:[A-Za-z0-9+/]+)$", re.M)
_NEW_KEYS_LINE = re.compile(r"^debug1: SSH2_MSG_NEWKEYS received(?:\r)?$", re.M)
_NO_AUTH = (
    "SessionType=none",
    "BatchMode=yes",
    "NumberOfPasswordPrompts=0",
    "PubkeyAuthentication=no",
    "PasswordAuthentication=no",
    "KbdInteractiveAuthentication=no",
    "GSSAPIAuthentication=no",
    "HostbasedAuthentication=no",
    "IdentityAgent=none",
    "IdentityFile=none",
    "CertificateFile=none",
    "ForwardAgent=no",
    "ClearAllForwardings=yes",
    "ControlMaster=no",
    "ControlPath=none",
    "UpdateHostKeys=no",
    "GlobalKnownHostsFile=/dev/null",
    "CheckHostIP=no",
    "FingerprintHash=sha256",
)


@dataclass(frozen=True)
class HostKeyObservation:
    endpoint: str
    presented: str | None
    verified: bool
    key: str | None = None
    reason: str | None = None


class HostKeyRefusal(ValueError):
    """The SSH endpoint did not prove a trusted host identity."""

    def __init__(
        self, target: InventoryTarget, presented: str | None, reason: str | None = None,
    ) -> None:
        pinned = ", ".join(key_fingerprint(pin) for pin in target.host_keys) or "none"
        endpoint = f"[{target.ssh_host}]:{target.ssh_port}"
        super().__init__(
            f"host {target.host_id!r} at {endpoint!r}: SSH host key verification refused "
            f"(presented: {presented or 'unavailable'}; pinned: {pinned}). "
            + (f"{reason} " if reason else "")
            + "Verify the host fingerprint independently and capture or state its host key."
        )


def key_fingerprint(key: str) -> str:
    key_type, encoded = key.split()
    digest = hashlib.sha256(base64.b64decode(encoded, validate=True)).digest()
    return f"{key_type} SHA256:{base64.b64encode(digest).decode('ascii').rstrip('=')}"


async def observe_host_key(
    target: InventoryTarget, *, pins: tuple[str, ...] | None, timeout_seconds: int
) -> HostKeyObservation:
    """Require KEX to complete, plus a verified pin or a captured key in the file."""
    if re.search(r"[^a-zA-Z0-9.:%_-]", target.ssh_host):
        raise HostKeyRefusal(target, None)
    endpoint = f"[{target.ssh_host}]:{target.ssh_port}"
    with tempfile.TemporaryDirectory(prefix="ssh-host-key-") as directory:
        path = Path(directory) / "known_hosts"
        if pins is None:
            path.touch(mode=0o600)
        else:
            _write_owner_only(path, "".join(f"{endpoint} {pin}\n" for pin in pins))
        options = (
            *_NO_AUTH,
            f"HostKeyAlias={endpoint}",
            f"UserKnownHostsFile={path}",
            f"StrictHostKeyChecking={'accept-new' if pins is None else 'yes'}",
            f"ConnectTimeout={timeout_seconds}",
        )
        argv = ["ssh", "-F", "/dev/null", "-v", "-T", "-p", str(target.ssh_port)]
        for option in options:
            argv.extend(("-o", option))
        argv.extend(("-l", target.ssh_user, "--", target.ssh_host))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "LC_ALL": "C"},
            )
        except OSError:
            return HostKeyObservation(endpoint, None, False, reason="OpenSSH could not start.")
        try:
            async with asyncio.timeout(timeout_seconds):
                _, diagnostics = await process.communicate()
        except TimeoutError:
            return HostKeyObservation(endpoint, None, False, reason="The SSH check timed out.")
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.communicate()
        stderr = diagnostics.decode("ascii", errors="replace").replace("\r\n", "\n")
        found = _KEY_LINE.search(stderr)
        if found is None:
            return HostKeyObservation(
                endpoint, None, False, reason="The SSH handshake presented no key."
            )
        presented = " ".join(found.groups())
        completed = _NEW_KEYS_LINE.search(stderr, found.end()) is not None
        if pins is not None:
            verified = completed and presented in {key_fingerprint(pin) for pin in pins}
            return HostKeyObservation(endpoint, presented, verified)
        if completed:
            for line in path.read_text(encoding="utf-8").splitlines():
                alias, _, key = line.partition(" ")
                if alias == endpoint and key and key_fingerprint(key) == presented:
                    return HostKeyObservation(endpoint, presented, True, key)
        return HostKeyObservation(endpoint, presented, False)
