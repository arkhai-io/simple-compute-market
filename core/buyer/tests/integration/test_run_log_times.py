"""A run log stamps its events, and reports its runs, at the process time source's instant."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import Ed25519Signer

from core_buyer.run_log import RunLog, list_runs, read_run

INSTANT = 1_794_821_400


def _stamp(instant: int) -> str:
    return datetime.fromtimestamp(instant, timezone.utc).isoformat()


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    before = injected_time.installed()
    held = InjectedTime(start=INSTANT)
    injected_time.install(held)
    yield held
    injected_time.install(before)


def test_a_run_s_events_and_summary_hold_the_injected_instant(
    monkeypatch: pytest.MonkeyPatch, tmp_path, source: InjectedTime,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Deterministic development identity; never use on a public network.
    buyer = Ed25519Signer(b"\x21" * 32)

    log = RunLog.start(profile_id=uuid.uuid4(), principal=buyer.identity)
    log.event("negotiation_started", listing_id="listing-1")
    source.set(INSTANT + 60)
    log.end("complete")

    events = read_run(log.run_id, signer=buyer)
    assert [event["ts"] for event in events] == [
        _stamp(INSTANT), _stamp(INSTANT), _stamp(INSTANT + 60),
    ]
    (summary,) = list_runs()
    assert summary.started_at == _stamp(INSTANT)
    assert summary.last_event_ts == _stamp(INSTANT + 60)
    assert summary.last_status == "complete"
