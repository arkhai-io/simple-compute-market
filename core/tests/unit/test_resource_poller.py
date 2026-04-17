"""Unit tests for the resource poller's self-heal behavior.

The poller runs periodically and transitions `state='leased'` resources
back to `available` once their lease ends. If the provisioning layer is
unavailable, a lease that ended a long time ago must still be force-freed
after the configured grace period — otherwise a transient provisioning
outage strands leases forever.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.agent.app.resource_poller import _poll_once
from core.agent.app.utils.sqlite_client import SQLiteClient


async def _seed_leased_resource(db_path: str, *, lease_end_utc: str) -> None:
    """Insert one leased compute resource with the given lease_end_utc."""
    client = SQLiteClient(db_path=db_path)
    await client.upsert_resource(
        resource_id="test-compute-001",
        resource_type="compute.gpu",
        resource_subtype="rtx5080",
        unit="count",
        value=1,
        state="leased",
        attributes={
            "gpu_model": "RTX 5080",
            "sla": 90.0,
            "region": "California, US",
            "vm_host": "test-host",
            "lease_end_utc": lease_end_utc,
        },
    )


async def _load_resource(db_path: str, resource_id: str) -> dict:
    client = SQLiteClient(db_path=db_path)
    rows = await client.list_resources(resource_type="compute.gpu")
    return next(r for r in rows if r["resource_id"] == resource_id)


class _ProvisioningUnreachable(RuntimeError):
    """Simulated network error from the provisioning layer."""


async def _failing_provisioning(*args, **kwargs):
    raise _ProvisioningUnreachable("simulated outage")


async def _reporting_unavailable(*args, **kwargs):
    return {"status": "ok", "vm_host": kwargs.get("vm_host"), "available": False, "running_vms": 1}


@pytest.mark.asyncio
async def test_force_frees_resource_after_grace_window(tmp_path):
    """Lease ended 2h ago + 30m grace → force-free even if provisioning fails."""
    db_path = str(tmp_path / "agent.db")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    await _seed_leased_resource(db_path, lease_end_utc=past)

    client = SQLiteClient(db_path=db_path)
    with patch("core.agent.app.resource_poller.CONFIG") as cfg:
        cfg.provisioning_mode = "http"
        cfg.provisioning_service_url = "http://fake"
        cfg.onchain_agent_id = "test-agent"
        cfg.resource_lease_grace_seconds = 1800  # 30 min

        await _poll_once(client, _failing_provisioning)

    resource = await _load_resource(db_path, "test-compute-001")
    assert resource["state"] == "available", f"Expected force-free, got state={resource['state']}"
    # lease_end_utc is either removed or set to null — both are treated as
    # "no active lease" by the poller's next cycle.
    lease_end = (resource.get("attributes") or {}).get("lease_end_utc")
    assert lease_end is None, (
        f"lease_end_utc should be cleared after force-free: got {lease_end!r}"
    )


@pytest.mark.asyncio
async def test_does_not_force_free_before_grace_window(tmp_path):
    """Lease ended 1 minute ago with a 30m grace → keep leased if provisioning fails."""
    db_path = str(tmp_path / "agent.db")
    just_past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    await _seed_leased_resource(db_path, lease_end_utc=just_past)

    client = SQLiteClient(db_path=db_path)
    with patch("core.agent.app.resource_poller.CONFIG") as cfg:
        cfg.provisioning_mode = "http"
        cfg.provisioning_service_url = "http://fake"
        cfg.onchain_agent_id = "test-agent"
        cfg.resource_lease_grace_seconds = 1800

        await _poll_once(client, _failing_provisioning)

    resource = await _load_resource(db_path, "test-compute-001")
    assert resource["state"] == "leased", (
        f"Should still be leased within grace: state={resource['state']}"
    )
    assert (resource.get("attributes") or {}).get("lease_end_utc") == just_past


@pytest.mark.asyncio
async def test_force_frees_when_provisioning_reports_unavailable_past_grace(tmp_path):
    """After grace window, even a successful 'VM still busy' reply frees the resource."""
    db_path = str(tmp_path / "agent.db")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    await _seed_leased_resource(db_path, lease_end_utc=past)

    client = SQLiteClient(db_path=db_path)
    with patch("core.agent.app.resource_poller.CONFIG") as cfg:
        cfg.provisioning_mode = "http"
        cfg.provisioning_service_url = "http://fake"
        cfg.onchain_agent_id = "test-agent"
        cfg.resource_lease_grace_seconds = 1800

        await _poll_once(client, _reporting_unavailable)

    resource = await _load_resource(db_path, "test-compute-001")
    assert resource["state"] == "available", (
        f"Force-free should override 'unavailable' past grace: state={resource['state']}"
    )
