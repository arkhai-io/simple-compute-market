"""System diagnostics service.

Provides the business logic for the ``SystemController`` endpoints:
health checks, version resolution, and Ansible readiness inspection.

This service is intentionally free of FastAPI and any HTTP concerns — those
live in the controller.  It can be instantiated and tested without starting
the application.

The ``ansible_readiness`` method reads host inventory from the ``HostService``
(DB table), not from the Ansible INI file on disk.  SSH key diagnostics:
  - ``path`` hosts: stat the key file and compute its SHA-256.
  - ``embedded`` hosts: report ``exists=True``; no SHA-256 (key is encrypted
    at rest).

Version resolution order
------------------------
1. ``importlib.metadata`` — works when the package is installed
   (``pip install -e .`` in Docker / production).
2. ``tomllib`` (stdlib >= 3.11) — reads ``pyproject.toml`` relative to this
   file, works in local dev without a package install.
3. ``"unknown"`` — defensive fallback so the endpoint never raises.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from models.system_model import (
    AnsibleReadinessResponse,
    FileInfo,
    InventoryInfo,
    SshKeyInfo,
)
from services.ansible_service import AnsibleService

if TYPE_CHECKING:
    from services.host_service import HostService


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def _read_version() -> str:
    """Return the service version string."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("provisioning-service")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass

    try:
        pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return str(data["project"]["version"])
    except Exception:
        pass

    return "unknown"


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
    """Run ``ansible --version`` and return the first output line, or ``None``."""
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


def collect_ssh_keys_from_hosts(hosts: list) -> list[SshKeyInfo]:
    """Build SSH key diagnostics from DB host rows.

    Groups hosts by their effective key reference:
      - ``path`` hosts: grouped by path string; the file is stat'd.
      - ``embedded`` hosts: each appears as a distinct ``<encrypted>`` entry.

    Returns one ``SshKeyInfo`` per unique key reference.
    """
    path_to_hosts: dict[str, list[str]] = {}
    embedded_hosts: list[str] = []

    for host in hosts:
        if host.ssh_key_type == "path":
            path_to_hosts.setdefault(host.ssh_key_value, []).append(host.name)
        else:
            embedded_hosts.append(host.name)

    results: list[SshKeyInfo] = []

    for raw_path, host_names in path_to_hosts.items():
        expanded = Path(os.path.expanduser(raw_path))
        exists = expanded.exists()
        results.append(
            SshKeyInfo(
                key_type="path",
                raw_path=raw_path,
                path=str(expanded),
                exists=exists,
                sha256=sha256_file(expanded) if exists else None,
                referenced_by=sorted(host_names),
            )
        )

    for host_name in embedded_hosts:
        results.append(
            SshKeyInfo(
                key_type="embedded",
                raw_path="<encrypted>",
                path="<encrypted>",
                exists=True,
                sha256=None,
                referenced_by=[host_name],
            )
        )

    return results


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SystemService:
    """Diagnostics operations for the system controller.

    Depends on ``AnsibleService`` and ``Settings``; optionally accepts a
    ``HostService`` for DB-backed inventory diagnostics.  All public methods
    are synchronous; callers that need to run them from an async context
    should use ``asyncio.to_thread``.
    """

    def __init__(
        self,
        ansible_service: AnsibleService,
        settings,
        host_service: "Optional[HostService]" = None,
    ) -> None:
        self._ansible = ansible_service
        self._settings = settings
        self._host_service = host_service

    def get_version(self) -> str:
        """Return the service version string."""
        return SERVICE_VERSION

    def ansible_version(self) -> Optional[str]:
        """Run ``ansible --version`` and return the first line."""
        return ansible_version()

    def ansible_readiness(self) -> AnsibleReadinessResponse:
        """Collect full Ansible readiness information synchronously.

        Inventory data is sourced from the ``hosts`` DB table via
        ``HostService``.  SSH key diagnostics iterate DB rows instead of
        parsing the INI file.

        This method performs filesystem and subprocess I/O; callers in an
        async context should invoke it via ``asyncio.to_thread``.
        """
        # --- Inventory info (from DB) ---
        if self._host_service is not None:
            try:
                enabled_hosts = self._host_service.list_hosts(enabled_only=True)
                host_count = len(enabled_hosts)
                inventory_info = InventoryInfo(
                    source="database",
                    path=str(self._settings.database_url),
                    exists=True,
                    host_count=host_count,
                )
                ssh_keys = collect_ssh_keys_from_hosts(enabled_hosts)
            except Exception as exc:
                inventory_info = InventoryInfo(
                    source="database",
                    path=str(self._settings.database_url),
                    exists=False,
                    host_count=None,
                )
                ssh_keys = []
        else:
            # Fallback: no HostService wired (e.g. during early startup or tests)
            inventory_info = InventoryInfo(
                source="database",
                path=str(self._settings.database_url),
                exists=False,
                host_count=None,
            )
            ssh_keys = []

        # --- Playbook info (filesystem) ---
        playbook_path = self._settings.resolved_playbook_path
        playbook_exists = playbook_path.exists()

        return AnsibleReadinessResponse(
            ansible_version=ansible_version(),
            ansible_mode=("mock" if "mock" in os.environ.get("ACTIVE_PROFILES", "") else "real"),
            inventory=inventory_info,
            playbook=FileInfo(
                path=str(playbook_path),
                exists=playbook_exists,
                sha256=sha256_file(playbook_path) if playbook_exists else None,
            ),
            ssh_keys=ssh_keys,
        )
