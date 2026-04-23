"""System diagnostics service.

Provides the business logic for the ``SystemController`` endpoints:
health checks, version resolution, and Ansible readiness inspection.

This service is intentionally free of FastAPI, SQLAlchemy, and any HTTP
concerns — those live in the controller.  It can be instantiated and tested
without starting the application.

Version resolution order
------------------------
1. ``importlib.metadata`` — works when the package is installed
   (``pip install -e .`` in Docker / production).
2. ``tomllib`` (stdlib ≥ 3.11) — reads ``pyproject.toml`` relative to this
   file, works in local dev without a package install.
3. ``"unknown"`` — defensive fallback so the endpoint never raises.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Optional

from models.system_model import (
    AnsibleReadinessResponse,
    FileInfo,
    InventoryInfo,
    SshKeyInfo,
)
from services.ansible_service import AnsibleService


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def _read_version() -> str:
    """Return the service version string.

    Tries ``importlib.metadata`` first (installed package), then parses
    ``pyproject.toml`` relative to this file, then returns ``"unknown"``.
    """
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("provisioning-service")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass

    try:
        # This file lives at src/services/system_service.py.
        # pyproject.toml is two levels up.
        pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
    except Exception:
        pass

    return "unknown"


# Resolved once at import time; stable for the lifetime of the process.
SERVICE_VERSION: str = _read_version()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> Optional[str]:
    """Return the SHA-256 hex digest of *path*, or ``None`` if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def ansible_version() -> Optional[str]:
    """Run ``ansible --version`` and return the first output line, or ``None``.

    Returns ``None`` if the ``ansible`` binary is not on ``PATH``, the
    invocation times out, or any other OS error occurs.  A ``None`` return
    is itself diagnostic information — it means Ansible is not installed or
    not reachable from the service's ``PATH``.
    """
    try:
        result = subprocess.run(
            ["ansible", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.splitlines()[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def collect_ssh_keys(ansible_service: AnsibleService) -> list[SshKeyInfo]:
    """Parse the Ansible inventory and return SSH key diagnostics.

    Collects every unique ``ansible_ssh_private_key_file`` value found in
    host entries, expands ``~``, and returns one ``SshKeyInfo`` per unique
    path with existence, SHA-256, and a list of the host aliases that
    reference it.

    Returns an empty list if the inventory is unreadable.
    """
    try:
        hosts = ansible_service.parse_inventory()
    except Exception:
        return []

    key_to_hosts: dict[str, list[str]] = {}
    for host in hosts:
        raw = host.vars.get("ansible_ssh_private_key_file", "")
        if raw:
            key_to_hosts.setdefault(raw, []).append(host.name)

    results: list[SshKeyInfo] = []
    for raw_path, host_names in key_to_hosts.items():
        expanded = Path(os.path.expanduser(raw_path))
        exists = expanded.exists()
        results.append(
            SshKeyInfo(
                raw_path=raw_path,
                path=str(expanded),
                exists=exists,
                sha256=sha256_file(expanded) if exists else None,
                referenced_by=sorted(host_names),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SystemService:
    """Diagnostics operations for the system controller.

    Depends only on ``AnsibleService`` and ``Settings`` — no DB, no HTTP.
    All public methods are synchronous; callers that need to run them from
    an async context should use ``asyncio.to_thread``.
    """

    def __init__(self, ansible_service: AnsibleService, settings) -> None:
        self._ansible = ansible_service
        self._settings = settings

    def get_version(self) -> str:
        """Return the service version string."""
        return SERVICE_VERSION

    def ansible_version(self) -> Optional[str]:
        """Run ``ansible --version`` and return the first line."""
        return ansible_version()

    def ansible_readiness(self) -> AnsibleReadinessResponse:
        """Collect full Ansible readiness information synchronously.

        This method performs filesystem and subprocess I/O; callers in an
        async context should invoke it via ``asyncio.to_thread``.
        """
        inventory_path = self._settings.resolved_inventory_path
        inventory_exists = inventory_path.exists()
        host_count: Optional[int] = None
        if inventory_exists:
            try:
                host_count = len(self._ansible.parse_inventory())
            except Exception:
                host_count = None

        playbook_path = self._settings.resolved_playbook_path
        playbook_exists = playbook_path.exists()

        return AnsibleReadinessResponse(
            ansible_version=ansible_version(),
            inventory=InventoryInfo(
                path=str(inventory_path),
                exists=inventory_exists,
                sha256=sha256_file(inventory_path) if inventory_exists else None,
                host_count=host_count,
            ),
            playbook=FileInfo(
                path=str(playbook_path),
                exists=playbook_exists,
                sha256=sha256_file(playbook_path) if playbook_exists else None,
            ),
            ssh_keys=collect_ssh_keys(self._ansible),
        )
