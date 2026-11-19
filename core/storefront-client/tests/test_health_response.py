"""The status model reads the fields a storefront reports and keeps the rest."""

from __future__ import annotations

from storefront_client.models import HealthResponse


def test_the_parked_settlement_count_is_read_when_reported():
    status = HealthResponse.from_dict(
        {"status": "ok", "settlement_manual_required": 2, "custom": True}
    )

    assert status.settlement_manual_required == 2
    assert status.extra == {"custom": True}


def test_the_parked_settlement_count_is_absent_when_not_reported():
    status = HealthResponse.from_dict({"status": "ok"})

    assert status.settlement_manual_required is None
    assert "settlement_manual_required" not in status.extra


def test_the_lifecycle_loops_are_read_when_reported():
    loops = {"publication": {"name": "publication", "state": "running", "last_outcome": None}}
    status = HealthResponse.from_dict({"status": "ok", "lifecycle": loops})

    assert status.lifecycle == loops
    assert "lifecycle" not in status.extra


def test_the_lifecycle_loops_are_absent_when_not_reported():
    assert HealthResponse.from_dict({"status": "ok"}).lifecycle is None


def test_the_time_section_is_read_in_either_mode():
    injected = HealthResponse.from_dict(
        {"status": "ok", "time": {"source": "injected", "now": 1794822300}}
    )
    wall = HealthResponse.from_dict({"status": "ok", "time": {"source": "wall"}})

    assert injected.time == {"source": "injected", "now": 1794822300}
    assert wall.time == {"source": "wall"}
    assert "time" not in injected.extra
    assert HealthResponse.from_dict({"status": "ok"}).time is None
