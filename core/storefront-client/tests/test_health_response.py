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
