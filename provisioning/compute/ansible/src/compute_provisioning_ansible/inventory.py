"""Ansible INI inventories as an input format for the host registry.

Every host entry in an inventory given to the provisioning service is a host
to register, under whatever section it is listed: the section names are the
file's Ansible syntax and mean nothing to the host registry. What a host is
sold as follows from its Resource Pool, not from its section. Parsing turns
each entry into an ``InventoryHost`` with an ``ssh`` connection the host
authority applies; the authority, not this module, decides what applying means.

The file given to the service lists only hosts to sell. Infrastructure an
operator manages with Ansible (relay proxies, the provisioning servers
themselves) belongs in a separate file of the same inventory directory, which
the service is not given.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from compute_provisioning.hosts.service import InventoryHost
from market_resource_pools import DEFAULT_POOL_ID

from .connection import ssh_connection

logger = logging.getLogger(__name__)

# The key an entry uses when it names no ansible_ssh_private_key_file.
DEFAULT_KEY_PATH = "/home/appuser/.ssh/id_ed25519"


def parse_inventory_ini(
    ini_text: str,
    *,
    key_material: Literal["path", "embedded"] = "path",
    read_key: Callable[[str], str] = lambda path: Path(path).read_text(encoding="utf-8"),
) -> list[InventoryHost]:
    """The hosts an INI inventory declares, each with an ``ssh`` connection.

    With ``key_material="path"`` an entry's key file is referenced by path; with
    ``"embedded"`` it is read and submitted as the connection's private key,
    which the ``ssh`` codec protects before anything is stored.
    """

    hosts: list[InventoryHost] = []
    for entry in _parse_entries(ini_text):
        key_file = entry["ansible_ssh_private_key_file"]
        connection = ssh_connection(
            ssh_host=entry["ssh_host"],
            ssh_user=entry["ssh_user"],
            ssh_port=entry["ssh_port"],
            public_host=entry["public_host"],
            key_path=key_file if key_material == "path" else None,
            private_key=read_key(key_file) if key_material == "embedded" else None,
        )
        hosts.append(
            InventoryHost(
                host_id=entry["host_id"],
                connection=connection,
                gpu_count=entry["gpu_count"],
                gpu_model=entry.get("gpu_model"),
                pool_id=entry["pool_id"],
            )
        )
    return hosts


def _parse_entries(ini_text: str) -> list[dict]:
    """Parse an Ansible INI inventory block into a list of host dicts.

    Every host entry is imported, under any section or none. A
    ``[group:vars]`` section holds variables and a ``[group:children]``
    section names groups; neither lists hosts, and both are skipped.

    Returns a list of ``{"host_id", "ssh_host", "ssh_user", "ssh_port",
    "gpu_count", "gpu_model", "pool_id", "ansible_ssh_private_key_file"}``
    dicts. Entries missing ``ansible_host`` or ``ansible_user`` are skipped
    with a warning.

    Variable mapping:
        ``ansible_port=``                 → ``ssh_port`` (int, default 22)
        ``gpus=``                         → ``gpu_count`` (int, default 0)
        ``gpu_model=``                    → ``gpu_model`` (str, default None)
        ``public_host=``                  → ``public_host`` (tenant-facing addr)
        ``ansible_ssh_private_key_file=`` → preserved verbatim
        ``pool_id=``                      → Resource Pool id (default "default")
        All other variables              → ignored
    """
    results = []
    in_host_section = True

    for line in ini_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("["):
            in_host_section = ":" not in stripped
            continue

        if not in_host_section:
            continue

        parts = stripped.split()
        name = parts[0]

        host_vars: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                host_vars[k] = v

        ssh_host = host_vars.get("ansible_host")
        ssh_user = host_vars.get("ansible_user")

        if not ssh_host or not ssh_user:
            logger.warning(
                "parse_inventory_ini: skipping '%s' — missing ansible_host or ansible_user",
                name,
            )
            continue

        # A malformed gpus= degrades to 0: a wrong capacity hint produces a
        # wrong listing, which is visible. A malformed ansible_port= instead
        # skips the entry, because substituting 22 would turn an operator's
        # typo into a host that cannot be reached at all — a failure that
        # looks like a network problem rather than a bad inventory line.
        try:
            gpu_count = int(host_vars.get("gpus", 0))
        except ValueError:
            gpu_count = 0

        ssh_port = 22
        if "ansible_port" in host_vars:
            try:
                ssh_port = int(host_vars["ansible_port"])
            except ValueError:
                ssh_port = -1
            if not 1 <= ssh_port <= 65535:
                logger.warning(
                    "parse_inventory_ini: skipping '%s' — ansible_port '%s' is not a "
                    "port number between 1 and 65535",
                    name,
                    host_vars["ansible_port"],
                )
                continue

        results.append({
            "host_id": name,
            "ssh_host": ssh_host,
            "public_host": host_vars.get("public_host"),
            "ssh_user": ssh_user,
            "ssh_port": ssh_port,
            "gpu_count": gpu_count,
            "gpu_model": host_vars.get("gpu_model"),
            "pool_id": host_vars.get("pool_id") or DEFAULT_POOL_ID,
            "ansible_ssh_private_key_file": host_vars.get(
                "ansible_ssh_private_key_file", DEFAULT_KEY_PATH
            ),
        })

    return results


__all__ = ["DEFAULT_KEY_PATH", "parse_inventory_ini"]
