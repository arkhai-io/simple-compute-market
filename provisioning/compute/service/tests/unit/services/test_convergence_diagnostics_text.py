"""The recovery-diagnostics line carries its counts in its own text, so a log
handler that drops structured ``extra`` still shows them."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from compute_provisioning_service.services.fulfillment_convergence import (
    FulfillmentConvergenceWatchdog,
    _diagnostics_text,
)

_DIAGNOSTICS = {
    "per_state": {
        "dispatching": {
            "total": 3,
            "actively_claimed": 1,
            "expired_claims": 2,
            "oldest_row_age_seconds": 7.5,
            "max_attempt_count": 4,
        },
    },
    "failed_count": 5,
    "teardown_failed_count": 6,
}
_LEASE_TARGETS = {
    "repaired": 8,
    "different_target_recorded": 9,
    "unrecordable": {"metadata": 1, "reservation_refused": 2, "no_reservation": 0},
}


def test_the_text_names_each_count() -> None:
    text = _diagnostics_text(_DIAGNOSTICS, _LEASE_TARGETS)

    assert "failed=5" in text
    assert "teardown_failed=6" in text
    assert (
        "dispatching=total:3,claimed:1,expired:2,max_attempts:4,oldest_s:7.5" in text
    )
    assert "lease_targets=repaired:8,different:9,unrecordable:3" in text


def test_the_logged_message_carries_the_counts_and_keeps_its_extra(caplog) -> None:
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=MagicMock(),
        repository=MagicMock(),
        provider_registry=MagicMock(),
        settings=MagicMock(),
    )

    with caplog.at_level(logging.INFO):
        watchdog._log_diagnostics(_DIAGNOSTICS, lease_targets=_LEASE_TARGETS)

    [record] = [r for r in caplog.records if getattr(r, "event", None)]
    assert record.getMessage() == (
        "[FULFILLMENT_CONVERGENCE] recovery diagnostics: "
        + _diagnostics_text(_DIAGNOSTICS, _LEASE_TARGETS)
    )
    assert record.event == "fulfillment_recovery_diagnostics"
    assert record.recovery_diagnostics == _DIAGNOSTICS
    assert record.lease_targets == _LEASE_TARGETS
