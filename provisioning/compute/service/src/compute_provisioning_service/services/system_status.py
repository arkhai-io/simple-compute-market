"""The provisioning service's health, status, and version.

Health is the local liveness a Kubernetes probe can afford: the database and
the job processor, with no outbound call. Status is the operator's view: the
storefront's reachability and authentication, the lease watchdog, the
storefront-to-provisioning contract this service speaks, what executes jobs,
and every readiness component composition contributed. Neither discloses a
database URL or a credential.

Framework-free: the system controller binds it.
"""

from __future__ import annotations

import asyncio
import os
import tomllib
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from compute_provisioning import JobExecutorTable
from compute_provisioning_contracts import (
    COMPUTE_PROVISIONING_CONTRACT_VERSION,
    SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS,
    ExecutionStatus,
    ExecutorStatus,
    HealthResponse,
    SystemStatusComponent,
    SystemStatusResponse,
    VersionResponse,
)
from market_identity import TrustedIdentitySet
from sqlalchemy import text
from storefront_client import StorefrontClient, StorefrontClientError

#: A readiness component's provider: called on each status read, in a worker
#: thread, because a component may run a subprocess or read files.
ComponentProvider = Callable[[], SystemStatusComponent]

_PACKAGE = "arkhai-compute-provisioning-service"


def _read_version() -> str:
    """The installed package's version, else the source tree's, else ``unknown``."""
    try:
        return version(_PACKAGE)
    except PackageNotFoundError:
        pass
    try:
        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


SERVICE_VERSION: str = _read_version()


def _active_profiles() -> list[str]:
    raw = os.environ.get("ACTIVE_PROFILES", "")
    return [profile.strip() for profile in raw.split(",") if profile.strip()]


# What each check's healthy values are. ``unconfigured`` is not a failure: the
# service is simply not pointed at a storefront. A paused or disabled lease
# watchdog is an operator's or a test's intent, not a degradation.
_HEALTHY_CHECK_VALUES: dict[str, frozenset[str]] = {
    "storefront": frozenset({"ok", "unconfigured"}),
    "storefront_auth": frozenset({"ok", "unconfigured"}),
    "lease_watchdog": frozenset({"running", "paused", "disabled"}),
}


class SystemStatusService:
    """Health, status, and version over the service's composed collaborators.

    ``job_queue_provider`` raises or returns ``None`` before the queue exists.
    ``identity_resolver`` resolves the service's signer and the storefront
    principal it trusts, raising ``RuntimeError`` when they are misconfigured.
    ``components`` are the readiness components composition contributed.
    """

    def __init__(
        self,
        *,
        settings: Any,
        session_factory: Callable[[], Any],
        job_queue_provider: Callable[[], Any],
        lease_lifecycle: Any,
        job_executors: JobExecutorTable,
        components: Sequence[ComponentProvider],
        identity_resolver: Callable[[], Any],
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._job_queue_provider = job_queue_provider
        self._lease_lifecycle = lease_lifecycle
        self._job_executors = job_executors
        self._components = tuple(components)
        self._identity_resolver = identity_resolver

    def version(self) -> VersionResponse:
        """The service version and the configuration profiles it loaded."""
        return VersionResponse(version=SERVICE_VERSION, active_profiles=_active_profiles())

    def health(self) -> HealthResponse:
        """Local checks only, so a probe never depends on another service."""
        checks: dict[str, str] = {"api": "ok"}
        try:
            with self._session_factory() as db:
                db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            job_queue = self._job_queue_provider()
            alive = job_queue is not None and job_queue.is_alive()
        except Exception:
            alive = False
        checks["job_processor"] = "ok" if alive else "degraded"
        status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
        return HealthResponse(status=status, checks=checks)

    def execution(self) -> ExecutionStatus:
        """What executes jobs, from the executors composition registered.

        Execution counts as mocked only when executors are composed and every
        one of them is the mock, so a deployment that would run real work
        never reports itself mocked.
        """
        mocked = self._job_executors.mocked_by_offering_mode()
        return ExecutionStatus(
            mocked=bool(mocked) and all(mocked.values()),
            executors=[
                ExecutorStatus(offering_mode=mode, mocked=is_mocked)
                for mode, is_mocked in mocked.items()
            ],
        )

    async def status(self) -> SystemStatusResponse:
        """The operator's view; heavier than health, and never a probe."""
        checks = await self._storefront_checks()
        checks["lease_watchdog"] = self._lease_watchdog_check()
        components = [
            await asyncio.to_thread(component) for component in self._components
        ]
        checks["execution"] = (
            "ok" if all(component.ready for component in components) else "degraded"
        )
        healthy = all(
            value in _HEALTHY_CHECK_VALUES.get(name, frozenset({"ok"}))
            for name, value in checks.items()
        )
        return SystemStatusResponse(
            status="ok" if healthy else "degraded",
            checks=checks,
            # Reported rather than negotiated, so a fleet can be checked for
            # skew before mutations resume; the service still refuses an
            # unsupported major on each contract route itself.
            provisioning_contract_version=COMPUTE_PROVISIONING_CONTRACT_VERSION,
            provisioning_contract_supported_majors=sorted(
                SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS
            ),
            execution=self.execution(),
            components=components,
        )

    def _lease_watchdog_check(self) -> str:
        if not getattr(self._settings, "lease_watchdog_enabled", True):
            return "disabled"
        return "paused" if self._lease_lifecycle.is_paused else "running"

    async def _storefront_checks(self) -> dict[str, str]:
        """The storefront's reachability, then whether this service authenticates to it.

        Authentication uses the service's own signer under the ``service``
        role and verifies the response against the storefront principal this
        service pins.
        """
        storefront_url = str(getattr(self._settings, "storefront_url", "") or "").rstrip("/")
        if not storefront_url:
            return {"storefront": "unconfigured", "storefront_auth": "unconfigured"}

        try:
            async with StorefrontClient(base_url=storefront_url) as storefront:
                await storefront.get_health()
            reachable = "ok"
        except StorefrontClientError as exc:
            reachable = f"http_{exc.status_code}" if exc.status_code else "error"
        except Exception as exc:
            reachable = _transport_failure(exc)
        if reachable != "ok":
            return {"storefront": reachable, "storefront_auth": reachable}

        try:
            identity = self._identity_resolver()
        except RuntimeError:
            return {"storefront": "ok", "storefront_auth": "configuration_error"}
        try:
            async with StorefrontClient(
                base_url=storefront_url,
                signer=identity.signer,
                caller_role="service",
                expected_publishers=TrustedIdentitySet(
                    identities=(identity.storefront_principal,)
                ),
            ) as storefront:
                await storefront.get_system_status()
            authenticated = "ok"
        except StorefrontClientError as exc:
            if exc.status_code in (401, 403):
                authenticated = "unauthorized"
            else:
                authenticated = f"http_{exc.status_code}" if exc.status_code else "error"
        except Exception as exc:
            authenticated = f"error: {type(exc).__name__}"
        return {"storefront": "ok", "storefront_auth": authenticated}


def _transport_failure(exc: Exception) -> str:
    name = type(exc).__name__
    if "Connect" in name or "connection" in str(exc).lower():
        return "unreachable"
    if "Timeout" in name or "timeout" in str(exc).lower():
        return "timeout"
    return f"error: {name}"


__all__ = ["ComponentProvider", "SERVICE_VERSION", "SystemStatusService"]
