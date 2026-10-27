"""Health and the administrator's status read, over injected configuration and mechanism checks."""

from __future__ import annotations

import sqlite3

from arkhai_api_selling.system import SystemService, SystemSettings, lifecycle_status

NOTHING = SystemSettings(registry_urls=(), registry_auth={}, authority_url="")


def _service(tmp_path, checks) -> SystemService:
    path = tmp_path / "health.db"
    sqlite3.connect(path).close()
    return SystemService(
        sqlite_client=type("Store", (), {"db_path": str(path)})(),
        settings=lambda: NOTHING,
        mechanism_checks=lambda: checks,
        signer=lambda: None,
    )


async def test_a_mechanism_check_is_healthy_unless_it_reports_an_error(tmp_path):
    healthy = await _service(tmp_path, {"example.v1": "dev,main"}).get_health()
    failing = await _service(tmp_path, {"example.v1": "error: no rpc"}).get_health()

    assert healthy == {
        "status": "ok",
        "checks": {"api": "ok", "database": "ok", "example.v1": "dev,main"},
    }
    assert failing["status"] == "degraded"


async def test_the_status_read_carries_the_pause_and_every_loop(tmp_path):
    body = await _service(tmp_path, {}).status(paused=True, loops=None)

    assert body["paused"] is True
    assert body["lifecycle"] is None
    assert body["principal"] is None
    assert (body["checks"]["registry"], body["checks"]["credits_service"]) == (
        "unconfigured",
        "unconfigured",
    )
    assert lifecycle_status(None) is None
