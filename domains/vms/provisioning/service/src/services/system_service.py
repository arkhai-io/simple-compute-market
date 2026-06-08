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


    async def get_status(self) -> dict:
        """Return a full diagnostic status dict for the system status endpoint.

        Heavier than ``ansible_readiness`` — includes outbound HTTP calls against
        the storefront via ``StorefrontClient``. Not suitable for Kubernetes
        liveness/readiness probes; use ``GET /health`` for those.

        Returns::

            {
                "status": "ok" | "degraded",
                "checks": {
                    "storefront":      "ok" | "unreachable" | "timeout" | "unconfigured" | "http_N",
                    "storefront_auth": "ok" | "unauthorized" | "unconfigured" | "http_N" | <error>,
                    "lease_watchdog":  "running" | "paused" | "disabled",
                }
            }

        Status rollup rules (what counts as healthy per check):
          - storefront:      "ok" or "unconfigured"
          - storefront_auth: "ok" or "unconfigured"
          - lease_watchdog:  "running", "paused", or "disabled"
        """
        from storefront_client import StorefrontClient, StorefrontClientError
        import container as _container_module

        checks: dict[str, str] = {}

        storefront_url = str(
            getattr(self._settings, "storefront_url", "") or ""
        ).rstrip("/")
        storefront_admin_key = str(
            getattr(self._settings, "storefront_admin_key", "") or ""
        )

        if not storefront_url:
            checks["storefront"] = "unconfigured"
            checks["storefront_auth"] = "unconfigured"
        else:
            # Reachability — GET /health via StorefrontClient (no admin key needed)
            try:
                async with StorefrontClient(base_url=storefront_url) as sf:
                    health = await sf.get_health()
                # Any structured response (ok or degraded) means the storefront is reachable
                checks["storefront"] = "ok"
            except StorefrontClientError as exc:
                checks["storefront"] = f"http_{exc.status_code}" if exc.status_code else "error"
            except Exception as exc:
                name = type(exc).__name__
                if "Connect" in name or "connection" in str(exc).lower():
                    checks["storefront"] = "unreachable"
                elif "Timeout" in name or "timeout" in str(exc).lower():
                    checks["storefront"] = "timeout"
                else:
                    checks["storefront"] = f"error: {name}"

            # Auth — GET /api/v1/system/status with admin key
            if not storefront_admin_key:
                checks["storefront_auth"] = "unconfigured"
            elif checks["storefront"] != "ok":
                # Storefront not reachable — auth check is meaningless
                checks["storefront_auth"] = checks["storefront"]
            else:
                try:
                    async with StorefrontClient(
                        base_url=storefront_url,
                        admin_key=storefront_admin_key,
                    ) as sf:
                        await sf.get_system_status()
                    checks["storefront_auth"] = "ok"
                except StorefrontClientError as exc:
                    if exc.status_code in (401, 403):
                        checks["storefront_auth"] = "unauthorized"
                    else:
                        checks["storefront_auth"] = f"http_{exc.status_code}" if exc.status_code else "error"
                except Exception as exc:
                    checks["storefront_auth"] = f"error: {type(exc).__name__}"

        # Lease watchdog state
        svc = getattr(_container_module, "resolved_lease_lifecycle_service", None)
        if svc is None:
            checks["lease_watchdog"] = "disabled"
        elif not getattr(self._settings, "lease_watchdog_enabled", True):
            checks["lease_watchdog"] = "disabled"
        elif not svc._resume_event.is_set():
            checks["lease_watchdog"] = "paused"
        else:
            checks["lease_watchdog"] = "running"

        def _is_healthy(key: str, value: str) -> bool:
            """True when a check value is not a service degradation.

            - storefront / storefront_auth: "ok" and "unconfigured" are healthy.
              "unconfigured" means not yet pointed at a storefront — not a failure.
            - lease_watchdog: "running", "paused", and "disabled" are all healthy.
              "paused" is an intentional operator/test action; "disabled" means
              the watchdog was not started (e.g. in test environments).
            """
            if key in ("storefront", "storefront_auth"):
                return value in ("ok", "unconfigured")
            if key == "lease_watchdog":
                return value in ("running", "paused", "disabled")
            return value == "ok"

        all_ok = all(_is_healthy(k, v) for k, v in checks.items())
        return {"status": "ok" if all_ok else "degraded", "checks": checks}
