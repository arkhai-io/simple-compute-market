"""The Ansible implementation's readiness, as a system-status component.

The composition root builds the ``ansible`` component from the executors it
composed: whichever domains contributed them, every executor this distribution
built is reported with its offering mode and the playbook it runs by default,
together with the Ansible binary and the SSH keys the registered hosts
reference. Status reads the result as a neutral component; nothing outside this
distribution knows its detail's shape.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

from compute_provisioning.jobs.executor_mock import executor_is_mocked
from compute_provisioning_contracts import SystemStatusComponent
from market_core import envelope
from pydantic import BaseModel, Field

from .executor import AnsibleJobExecutor

#: The component's name in system status.
ANSIBLE_COMPONENT = "ansible"
#: The kind and schema version of the component's detail.
ANSIBLE_READINESS_KIND = "compute_provisioning.ansible.readiness"
ANSIBLE_READINESS_SCHEMA_VERSION = 1


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
            "For 'embedded': always True (key is stored in DB)."
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
    ``<encrypted>`` when the host record holds it.
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


def ansible_readiness_component(
    *,
    executors_by_offering_mode: Mapping[str, Sequence[Any]],
    list_hosts: Callable[[], Iterable[Any]],
    version_probe: Callable[[], Optional[str]] | None = None,
) -> SystemStatusComponent:
    """The ``ansible`` component over the composed executors and registered hosts.

    Ready when every Ansible executor runs the mock, or has its playbook with
    Ansible on ``PATH``. ``version_probe`` reports Ansible's version, ``None``
    without it; it runs ``ansible --version`` unless given. This performs
    filesystem and subprocess I/O; an async caller runs it in a thread.
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
        ssh_keys = collect_ssh_keys_from_hosts(list_hosts())
        readable = True
    except Exception:
        ssh_keys = []
        readable = False
    ready = all(
        playbook.mocked or (playbook.exists and version is not None)
        for playbook in playbooks
    )
    detail = AnsibleReadinessDetail(
        ansible_version=version,
        playbooks=playbooks,
        ssh_keys=ssh_keys,
        host_registry_readable=readable,
    )
    return SystemStatusComponent(
        name=ANSIBLE_COMPONENT,
        ready=ready,
        detail=envelope(
            ANSIBLE_READINESS_KIND,
            ANSIBLE_READINESS_SCHEMA_VERSION,
            detail.model_dump(mode="json"),
        ),
    )


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


def collect_ssh_keys_from_hosts(hosts: Iterable[Any]) -> list[SshKeyInfo]:
    """One ``SshKeyInfo`` per key reference among the registered hosts.

    Hosts naming a key file are grouped by its path, and the file is examined;
    each host with an embedded key appears on its own, as ``<encrypted>``.
    """
    path_to_hosts: dict[str, list[str]] = {}
    embedded_hosts: list[str] = []
    for host in hosts:
        key_path = host.connection.public.get("key_path")
        if key_path:
            path_to_hosts.setdefault(key_path, []).append(host.host_id)
        elif "private_key" in host.connection.protected:
            embedded_hosts.append(host.host_id)

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
    for host_id in embedded_hosts:
        results.append(
            SshKeyInfo(
                key_type="embedded",
                raw_path="<encrypted>",
                path="<encrypted>",
                exists=True,
                sha256=None,
                referenced_by=[host_id],
            )
        )
    return results


__all__ = [
    "ANSIBLE_COMPONENT",
    "ANSIBLE_READINESS_KIND",
    "ANSIBLE_READINESS_SCHEMA_VERSION",
    "AnsiblePlaybookInfo",
    "AnsibleReadinessDetail",
    "FileInfo",
    "SshKeyInfo",
    "ansible_readiness_component",
    "ansible_version",
    "collect_ssh_keys_from_hosts",
    "sha256_file",
]
