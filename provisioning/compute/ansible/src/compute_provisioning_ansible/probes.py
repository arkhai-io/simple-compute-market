"""What the Ansible implementation can say about its own readiness.

``probe_connectivity`` runs ``ansible -m ping`` against one registered host,
rendered from its connection the way a job's inventory is. ``ansible_readiness``
reports the Ansible binary, the host registry the inventories are rendered
from, a playbook, and the SSH keys the registered hosts reference. Both are
the Ansible implementation's diagnostics, whichever domain's playbooks it runs.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from compute_provisioning.hosts import ExecutionHost

from .runner import ConnectivityResult, inventory_target

#: The inventory group a connectivity probe lists its one host under. A ping
#: names the host itself, so the group only has to exist.
PROBE_INVENTORY_GROUP = "connectivity_probe"


class FileInfo(BaseModel):
    path: str = Field(description="Absolute (expanded) filesystem path")
    exists: bool
    sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hex digest of the file contents (None if file absent)",
    )


class InventoryInfo(BaseModel):
    """Host inventory diagnostics.

    ``source`` is ``'database'``: inventories are rendered from the registered
    hosts. ``host_count`` is the number of enabled hosts found. ``path`` is the
    database URL, for information.
    """

    source: str = Field(description="'database' or 'file'")
    path: str = Field(description="DB URL or inventory file path")
    exists: bool = Field(description="True if the source is reachable")
    host_count: Optional[int] = Field(
        default=None,
        description="Number of enabled hosts (None if source is unreadable)",
    )


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


class AnsibleReadinessResponse(BaseModel):
    ansible_version: Optional[str] = Field(
        default=None,
        description="ansible --version first line (None if ansible not on PATH)",
    )
    ansible_mode: str = Field(
        default="real",
        description=(
            "'mock' when ACTIVE_PROFILES includes 'mock' (the mock Ansible runner); "
            "'real' otherwise (AnsibleRunner). Used by e2e tests to gate on mock mode."
        ),
    )
    executor_modes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "'mock' or 'real' per offering mode, from the job executors compute "
            "provisioning composed. Empty before composition."
        ),
    )
    inventory: InventoryInfo
    playbook: FileInfo
    ssh_keys: list[SshKeyInfo] = Field(default_factory=list)


async def probe_connectivity(runner: Any, host: ExecutionHost) -> ConnectivityResult:
    """Ping one registered host through an inventory rendered from its connection.

    The inventory, and any key decrypted for it, is removed when the probe ends.
    """
    with runner.write_inventory(
        [inventory_target(host)], group=PROBE_INVENTORY_GROUP
    ) as inventory:
        return await runner.check_connectivity_with_inventory(host.host_id, inventory.path)


def ansible_readiness(
    *,
    list_hosts: Optional[Callable[[], list]],
    inventory_path: str,
    playbook_path: Path,
    ansible_mode: str,
    executor_modes: Mapping[str, str],
) -> AnsibleReadinessResponse:
    """The Ansible implementation's readiness, collected synchronously.

    ``list_hosts`` returns the enabled registered hosts (``None`` when the host
    registry is not composed yet); ``inventory_path`` names where they are kept.
    This performs filesystem and subprocess I/O; an async caller runs it in a
    thread.
    """
    host_count: Optional[int] = None
    ssh_keys: list[SshKeyInfo] = []
    exists = False
    if list_hosts is not None:
        try:
            hosts = list_hosts()
        except Exception:
            hosts = None
        if hosts is not None:
            exists = True
            host_count = len(hosts)
            ssh_keys = collect_ssh_keys_from_hosts(hosts)
    playbook_exists = playbook_path.exists()
    return AnsibleReadinessResponse(
        ansible_version=ansible_version(),
        ansible_mode=ansible_mode,
        executor_modes=dict(executor_modes),
        inventory=InventoryInfo(
            source="database", path=inventory_path, exists=exists, host_count=host_count
        ),
        playbook=FileInfo(
            path=str(playbook_path),
            exists=playbook_exists,
            sha256=sha256_file(playbook_path) if playbook_exists else None,
        ),
        ssh_keys=ssh_keys,
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
    "AnsibleReadinessResponse",
    "FileInfo",
    "InventoryInfo",
    "PROBE_INVENTORY_GROUP",
    "SshKeyInfo",
    "ansible_readiness",
    "ansible_version",
    "collect_ssh_keys_from_hosts",
    "probe_connectivity",
    "sha256_file",
]
