"""The status service's own rules, over injected collaborators.

The route, the typed client, and the composed executors and components are the
integration suite's; this covers what the service decides from them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from compute_provisioning import JobExecutorTable
from compute_provisioning.jobs.executor_mock import MockRuleSet
from compute_provisioning_contracts import SystemStatusComponent
from market_core import envelope

from compute_provisioning_service.services.system_status import (
    COMPONENT_FAILURE_KIND,
    StatusComponentProvider,
    SystemStatusService,
)


class _Executor:
    def __init__(self, *, mocked: bool) -> None:
        self.rules = MockRuleSet() if mocked else None


def _table(**modes: bool) -> JobExecutorTable:
    table = JobExecutorTable()
    for mode, mocked in modes.items():
        table.register(mode, "act", _Executor(mocked=mocked))
    table.freeze()
    return table


def _component(*, ready: bool, name: str = "fake") -> SystemStatusComponent:
    return SystemStatusComponent(
        name=name, ready=ready, detail=envelope("fake.readiness", 1, {"ready": ready})
    )


def _provider(*, ready: bool, name: str = "fake") -> StatusComponentProvider:
    return StatusComponentProvider(name=name, collect=lambda: _component(ready=ready, name=name))


class _Session:
    def __init__(self, *, fails: bool = False) -> None:
        self._fails = fails

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        if self._fails:
            raise RuntimeError("could not connect to postgresql://user:secret@db/x")


def _service(
    *,
    table=None,
    components=(),
    session=None,
    queue_alive=True,
    queue_provider=None,
    paused=False,
    watchdog_enabled=True,
):
    return SystemStatusService(
        # No storefront configured, so status makes no outbound call.
        settings=SimpleNamespace(storefront_url="", lease_watchdog_enabled=watchdog_enabled),
        session_factory=lambda: session or _Session(),
        job_queue_provider=queue_provider
        or (lambda: SimpleNamespace(is_alive=lambda: queue_alive)),
        lease_lifecycle=SimpleNamespace(is_paused=paused),
        job_executors=table if table is not None else _table(vm=True),
        components=components,
        identity_resolver=lambda: None,
    )


def test_health_is_ok_with_a_database_and_a_live_job_processor():
    health = _service().health()

    assert (health.status, health.checks) == (
        "ok",
        {"api": "ok", "database": "ok", "job_processor": "ok"},
    )


def test_a_database_failure_is_reported_without_its_message():
    """The message can carry the database URL, credentials included."""
    health = _service(session=_Session(fails=True)).health()

    assert health.status == "degraded"
    assert health.checks["database"] == "error: RuntimeError"


def test_a_job_processor_not_running_degrades_health():
    assert _service(queue_alive=False).health().checks["job_processor"] == "degraded"


def test_a_job_queue_not_yet_created_degrades_health():
    def missing():
        raise RuntimeError("Job queue is not initialised")

    assert _service(queue_provider=missing).health().checks["job_processor"] == "degraded"


@pytest.mark.parametrize(
    ("modes", "mocked"),
    [
        ({"vm": True, "bare_metal": True}, True),
        ({"vm": True, "bare_metal": False}, False),
        ({}, False),
    ],
)
def test_execution_is_mocked_only_when_every_composed_executor_is(modes, mocked):
    execution = _service(table=_table(**modes)).execution()

    assert execution.mocked is mocked
    assert {(e.offering_mode, e.mocked) for e in execution.executors} == set(modes.items())


async def test_a_component_not_ready_degrades_execution_and_status():
    status = await _service(
        components=[_provider(ready=True, name="a"), _provider(ready=False)]
    ).status()

    assert status.checks["execution"] == "degraded"
    assert status.status == "degraded"
    assert [c.name for c in status.components] == ["a", "fake"]


async def test_every_component_ready_leaves_status_ok():
    status = await _service(components=[_provider(ready=True)]).status()

    assert status.checks == {
        "storefront": "unconfigured",
        "storefront_auth": "unconfigured",
        "lease_watchdog": "running",
        "execution": "ok",
    }
    assert status.status == "ok"


@pytest.mark.parametrize(
    ("paused", "enabled", "value"),
    [(False, True, "running"), (True, True, "paused"), (False, False, "disabled")],
)
async def test_the_lease_watchdog_state_never_degrades_status(paused, enabled, value):
    status = await _service(paused=paused, watchdog_enabled=enabled).status()

    assert status.checks["lease_watchdog"] == value
    assert status.status == "ok"


def test_version_reports_the_active_profiles(monkeypatch):
    monkeypatch.setenv("ACTIVE_PROFILES", "docker, mock")

    version = _service().version()

    assert version.active_profiles == ["docker", "mock"]
    assert version.version


async def test_a_provider_that_raises_is_reported_failed_and_status_degrades():
    """One defective diagnostic degrades status rather than failing it, and
    its failure discloses the exception's type, never its message."""

    def raising():
        raise RuntimeError("could not read /secrets/id_ed25519")

    status = await _service(
        components=[
            _provider(ready=True, name="healthy"),
            StatusComponentProvider(name="broken", collect=raising),
        ]
    ).status()

    broken = status.component("broken")
    assert status.component("healthy").ready is True
    assert broken.ready is False
    assert (broken.detail.kind, broken.detail.payload) == (
        COMPONENT_FAILURE_KIND,
        {"error": "RuntimeError"},
    )
    assert "secrets" not in status.model_dump_json()
    assert (status.checks["execution"], status.status) == ("degraded", "degraded")


async def test_a_provider_reporting_another_name_is_reported_failed_under_its_own():
    """A provider cannot report a component it was not registered for."""
    impostor = StatusComponentProvider(
        name="ansible", collect=lambda: _component(ready=True, name="other")
    )

    status = await _service(components=[impostor]).status()

    assert [c.name for c in status.components] == ["ansible"]
    assert status.component("ansible").ready is False
    assert status.component("ansible").detail.payload == {"error": "reported as 'other'"}
