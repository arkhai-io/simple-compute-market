"""The Ansible implementation's readiness, as a system-status component.

The composition root builds the ``ansible`` component from the executors it
composed: whichever domains contributed them, every executor this distribution
built is reported with its offering mode and the playbook it runs by default,
together with the Ansible binary and each enabled host's stored ``ssh``
connection, read as execution reads it: refused where execution would refuse
it, its key file examined, its embedded key decrypted in memory and discarded.
Status reads the result as a neutral component; nothing outside this
distribution knows its detail's shape.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning.jobs.executor_mock import executor_is_mocked
from compute_provisioning_contracts import SystemStatusComponent
from market_core import envelope
from pydantic import BaseModel, Field

from .connection import SSH_CONNECTION_KIND, ProtectedKeyUnreadableError, SshConnectionCodec
from .executor import AnsibleJobExecutor
from .runner import inventory_target

#: The component's name in system status.
ANSIBLE_COMPONENT = "ansible"
#: The kind and schema version of the component's detail. At version 2 an
#: embedded key's ``exists`` says whether it decrypts under the configured key,
#: and a host whose stored connection execution refuses has no ``ssh_keys``
#: entry. This distribution produces only version 2; a version-1 detail reports
#: embedded keys present without trying them, so a reader of version 1 refuses
#: version 2.
ANSIBLE_READINESS_KIND = "compute_provisioning.ansible.readiness"
ANSIBLE_READINESS_SCHEMA_VERSION = 2


class FileInfo(BaseModel):
    path: str = Field(description="Absolute (expanded) filesystem path")
    exists: bool
    sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hex digest of the file contents (None if file absent)",
    )


class AnsiblePlaybookInfo(FileInfo):
    """The playbook one offering mode's Ansible executor runs by default."""

    offering_mode: str
    mocked: bool = Field(description="True when the executor runs the mock")


class SshKeyInfo(BaseModel):
    """One key an enabled host's served ``ssh`` connection names.

    A host whose stored connection execution refuses has no entry: its key
    reference was never read at a version the codec serves.
    """

    key_type: str = Field(description="'path' or 'embedded'")
    raw_path: str = Field(
        description=(
            "For 'path': the configured key path. "
            "For 'embedded': '<encrypted>' sentinel."
        ),
    )
    path: str = Field(description="Expanded path (path-type) or '<encrypted>'")
    exists: bool = Field(
        description=(
            "For 'path': whether the key file exists on disk. "
            "For 'embedded': whether the protected key decrypts under the "
            "configured key."
        )
    )
    sha256: Optional[str] = Field(
        default=None,
        description=(
            "SHA-256 of the key file (path-type only; None for embedded or absent files)."
        ),
    )
    referenced_by: list[str] = Field(
        description="Host aliases that use this key configuration.",
    )


class AnsibleReadinessDetail(BaseModel):
    """What the ``ansible`` component reports.

    Credentials never appear: a key is reported by its path and digest, or as
    ``<encrypted>`` when the host record holds it, never by its plaintext or
    its ciphertext.
    """

    ansible_version: Optional[str] = Field(
        default=None,
        description="ansible --version first line (None if ansible not on PATH)",
    )
    playbooks: list[AnsiblePlaybookInfo] = Field(default_factory=list)
    ssh_keys: list[SshKeyInfo] = Field(default_factory=list)
    host_registry_readable: bool = Field(
        description="False when the registered hosts could not be listed",
    )
    not_ready_reasons: list[str] = Field(
        default_factory=list,
        description="Why the component is not ready; empty when it is",
    )


def ansible_readiness_component(
    *,
    executors_by_offering_mode: Mapping[str, Sequence[Any]],
    execution_hosts: Callable[[], Iterable[ExecutionHost]],
    ssh_codec: SshConnectionCodec,
    version_probe: Callable[[], Optional[str]] | None = None,
) -> SystemStatusComponent:
    """The ``ansible`` component over the composed executors and the enabled hosts.

    Ready means a job can run through every composed Ansible executor:

    - the host registry is readable, whatever runs, because every job resolves
      its host there, and an unreadable registry leaves the hosts' credentials
      unverified;
    - when any Ansible executor is real, Ansible is on ``PATH``, every real
      executor's playbook exists, and every enabled ``ssh`` host can be
      executed against: execution does not refuse its stored connection, the
      key file it names exists, and the protected key it holds decrypts. A
      host's offering mode is its pool's, which this component does not see, so
      a host's problem counts once any executor is real.

    Mocked executors need neither Ansible, nor playbooks, nor keys; a key file
    that is missing, or an embedded key that does not decrypt, is still
    reported in its entry, while a host whose connection execution refuses has
    no entry and goes unreported. ``execution_hosts`` lists the
    enabled hosts with their full connection envelopes, and ``ssh_codec`` is
    the codec execution decrypts embedded keys with. ``version_probe`` reports
    Ansible's version, ``None`` without it; it runs ``ansible --version`` unless
    given. This performs filesystem and subprocess I/O; an async caller runs it
    in a thread.
    """
    version = (version_probe or ansible_version)()
    playbooks: list[AnsiblePlaybookInfo] = []
    for offering_mode, executors in executors_by_offering_mode.items():
        for executor in executors:
            if not isinstance(executor, AnsibleJobExecutor):
                continue
            path = Path(executor.playbook_path)
            exists = path.exists()
            playbooks.append(
                AnsiblePlaybookInfo(
                    offering_mode=offering_mode,
                    mocked=executor_is_mocked(executor),
                    path=str(path),
                    exists=exists,
                    sha256=sha256_file(path) if exists else None,
                )
            )
    try:
        hosts = list(execution_hosts())
        readable = True
    except Exception:
        hosts = []
        readable = False
    report = collect_ssh_keys_from_hosts(hosts, ssh_codec)
    ssh_keys = report.ssh_keys
    reasons = _not_ready_reasons(
        version=version,
        playbooks=playbooks,
        ssh_keys=ssh_keys,
        host_reasons=report.host_reasons,
        readable=readable,
    )
    detail = AnsibleReadinessDetail(
        ansible_version=version,
        playbooks=playbooks,
        ssh_keys=ssh_keys,
        host_registry_readable=readable,
        not_ready_reasons=reasons,
    )
    return SystemStatusComponent(
        name=ANSIBLE_COMPONENT,
        ready=not reasons,
        detail=envelope(
            ANSIBLE_READINESS_KIND,
            ANSIBLE_READINESS_SCHEMA_VERSION,
            detail.model_dump(mode="json"),
        ),
    )


def _not_ready_reasons(
    *,
    version: Optional[str],
    playbooks: Sequence[AnsiblePlaybookInfo],
    ssh_keys: Sequence[SshKeyInfo],
    host_reasons: Sequence[str],
    readable: bool,
) -> list[str]:
    reasons: list[str] = []
    if not readable:
        reasons.append("the host registry could not be read")
    real = [playbook for playbook in playbooks if not playbook.mocked]
    if not real:
        return reasons
    if version is None:
        reasons.append("ansible is not on PATH")
    reasons.extend(
        f"the {playbook.offering_mode} playbook is missing: {playbook.path}"
        for playbook in real
        if not playbook.exists
    )
    reasons.extend(
        f"the key file {key.path} is missing (hosts: {', '.join(key.referenced_by)})"
        for key in ssh_keys
        if key.key_type == "path" and not key.exists
    )
    reasons.extend(host_reasons)
    return reasons


def sha256_file(path: Path) -> Optional[str]:
    """The SHA-256 hex digest of ``path``, or ``None`` if it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def ansible_version() -> Optional[str]:
    """The first line of ``ansible --version``, or ``None`` without Ansible."""
    try:
        result = subprocess.run(
            ["ansible", "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.splitlines()[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


@dataclass(frozen=True)
class HostKeyReport:
    """The enabled hosts' keys as execution would read them.

    ``host_reasons`` names each host execution could not run against, in host
    order: a stored connection it refuses, or a protected key that does not
    decrypt. Each is a reason once any Ansible executor is real.
    """

    ssh_keys: list[SshKeyInfo] = field(default_factory=list)
    host_reasons: list[str] = field(default_factory=list)


def collect_ssh_keys_from_hosts(
    hosts: Iterable[ExecutionHost], ssh_codec: SshConnectionCodec
) -> HostKeyReport:
    """One ``SshKeyInfo`` per key reference among the hosts, read as execution
    reads them.

    A host of another connection kind is skipped: no Ansible executor reaches
    it. Every ``ssh`` host is read through ``inventory_target``, the function
    execution renders a host from, so a connection it refuses, such as one
    stored at a version other than the one the codec serves, gives a reason naming the
    host and has no entry. Hosts naming a key file are grouped by its path, and
    the file is examined. Each host with an embedded key appears on its own, as
    ``<encrypted>``, and its key is decrypted in memory and the plaintext
    discarded at once, nothing written: one that does not decrypt is reported
    as not existing, with the codec's message as its reason. One host's problem
    leaves every other host's entry as it would be without it.
    """
    path_to_hosts: dict[str, list[str]] = {}
    embedded: list[tuple[str, bool]] = []
    host_reasons: list[str] = []
    for host in hosts:
        if host.connection.kind != SSH_CONNECTION_KIND:
            continue
        try:
            target = inventory_target(host)
        except ValueError as exc:
            refusal = str(exc)
            # A refusal naming no key already names the host; one for a version
            # or a malformed public field does not, so it is given the host.
            if repr(host.host_id) not in refusal:
                refusal = f"host {host.host_id!r} cannot be executed against: {refusal}"
            host_reasons.append(refusal)
            continue
        if target.ssh_key_type == "path":
            path_to_hosts.setdefault(target.ssh_key_value, []).append(host.host_id)
            continue
        try:
            # The plaintext is not bound to any name, so it is discarded as
            # soon as the call returns.
            ssh_codec.decrypt_private_key(target.ssh_key_value, host_id=host.host_id)
        except ProtectedKeyUnreadableError as exc:
            embedded.append((host.host_id, False))
            host_reasons.append(str(exc))
        else:
            embedded.append((host.host_id, True))

    results: list[SshKeyInfo] = []
    for raw_path, host_ids in path_to_hosts.items():
        expanded = Path(os.path.expanduser(raw_path))
        exists = expanded.exists()
        results.append(
            SshKeyInfo(
                key_type="path",
                raw_path=raw_path,
                path=str(expanded),
                exists=exists,
                sha256=sha256_file(expanded) if exists else None,
                referenced_by=sorted(host_ids),
            )
        )
    for host_id, decrypts in embedded:
        results.append(
            SshKeyInfo(
                key_type="embedded",
                raw_path="<encrypted>",
                path="<encrypted>",
                exists=decrypts,
                sha256=None,
                referenced_by=[host_id],
            )
        )
    return HostKeyReport(ssh_keys=results, host_reasons=host_reasons)


__all__ = [
    "ANSIBLE_COMPONENT",
    "ANSIBLE_READINESS_KIND",
    "ANSIBLE_READINESS_SCHEMA_VERSION",
    "AnsiblePlaybookInfo",
    "AnsibleReadinessDetail",
    "FileInfo",
    "HostKeyReport",
    "SshKeyInfo",
    "ansible_readiness_component",
    "ansible_version",
    "collect_ssh_keys_from_hosts",
    "sha256_file",
]
