"""The watchdog's per-deal record in the buyer's SQLite evidence file, and the read it composes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import injected_time
import pytest
from injected_time import InjectedTime
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, DeliveryView, LifecycleRead, Rejected
from market_deal_lifecycle_buyer import (
    BuyerDeal, BuyerLifecycle, EndDeliveryProgress, FileEvidenceStore, WatchdogSettings, WatchdogStop, watch_deal,
)
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS, ProbeObservation


class Peer:
    async def read(self, negotiation_id):
        return LifecycleRead(negotiation_id=negotiation_id, authority=AuthorityView(outcome=Rejected(reason="x")),
                             delivery=DeliveryView(progress="unstarted"))


def lifecycle(root, now):
    store = FileEvidenceStore(root)
    deal = BuyerDeal("deal", "commitment", PaymentBinding("deal", PaymentSelector("fixture.payment")), rate=True)
    return store, BuyerLifecycle(
        deal=lambda _: deal, payments=PaymentAdapterTable([]), disputes=DisputeAdapterTable([]),
        operations=store, peer=Peer(), end_journal=store.end_journal, evidence=store,
        watchdog=store.watchdog, clock=lambda: now,
    )


def test_the_opt_in_probe_and_stop_survive_a_restart_and_the_read_shows_each(tmp_path):
    async def drive():
        store, _ = lifecycle(tmp_path, 1000)
        settings = WatchdogSettings(interval_seconds=30, threshold=2, probe_timeout_seconds=5)
        store.watchdog.opt_in("deal", settings)
        _, reopened = lifecycle(tmp_path, 1000)
        assert (await reopened.buyer_read("deal"))["watchdog"] == {"status": "unmonitored", "last_probe_at": None}

        store.watchdog.record_probe("deal", 990)
        _, fresh = lifecycle(tmp_path, 1000)
        read = await fresh.buyer_read("deal")
        assert read["watchdog"] == {"status": "monitored", "last_probe_at": 990}
        # The status sits beside the lifecycle read, never inside it.
        assert LifecycleRead.model_validate({k: v for k, v in read.items() if k != "watchdog"})

        _, later = lifecycle(tmp_path, 1100)
        assert (await later.buyer_read("deal"))["watchdog"]["status"] == "unmonitored"

        first = WatchdogStop(1100, (ProbeObservation(1050, "probe timed out"),))
        assert store.watchdog.record_stop("deal", first) == first
        assert store.watchdog.record_stop("deal", WatchdogStop(1200, ())) == first
        # Opting in again keeps the journaled stop.
        store.watchdog.opt_in("deal", settings)
        assert (await later.buyer_read("deal"))["watchdog"]["status"] == "stopped"

        await store.delete("deal")
        assert store.watchdog.state("deal") is None

    asyncio.run(drive())


INSTANT = 1_794_822_300
SETTINGS = WatchdogSettings(interval_seconds=30, threshold=2, probe_timeout_seconds=5)


@pytest.fixture
def source():
    before = injected_time.installed()
    held = InjectedTime(start=INSTANT)
    injected_time.install(held)
    yield held
    injected_time.install(before)


def test_the_loop_journals_its_probes_and_stop_at_the_process_source_s_instant(tmp_path, source):
    elapsed = [0.0]

    async def fake_sleep(seconds):
        elapsed[0] += seconds

    async def failing_probe():
        return False

    async def never_ended():
        return False

    store = FileEvidenceStore(tmp_path)
    deal = BuyerDeal("deal", "commitment", PaymentBinding("deal", PaymentSelector("fixture.payment")), rate=True)
    # Only the stop's dispatch is stood in for; the journal is the SQLite file.
    stopping = SimpleNamespace(
        _deal=lambda _: deal, end_journal=None, evidence=None,
        end=AsyncMock(return_value=EndDeliveryProgress(
            negotiation_id="deal", observed_at=INSTANT, mode="normal_stop", payment=Accepted())),
    )
    store.watchdog.opt_in("deal", SETTINGS)

    # No clock is given: the loop stamps from the process source.
    asyncio.run(watch_deal(stopping, "deal", journal=store.watchdog, probe=failing_probe,
                           monotonic=lambda: elapsed[0], sleep=fake_sleep, ended=never_ended))

    state = FileEvidenceStore(tmp_path).watchdog.state("deal")
    assert state.last_probe_at == INSTANT
    assert state.stop.decided_at == INSTANT
    assert [probe.at for probe in state.stop.probes] == [INSTANT, INSTANT]


def test_the_read_judges_a_probe_s_staleness_at_the_process_source_s_instant(tmp_path, source):
    fresh = 30 + 5 + GRACE_SECONDS
    store = FileEvidenceStore(tmp_path)
    deal = BuyerDeal("deal", "commitment", PaymentBinding("deal", PaymentSelector("fixture.payment")), rate=True)
    # No clock is given: the lifecycle reads the process source.
    buyer = BuyerLifecycle(
        deal=lambda _: deal, payments=PaymentAdapterTable([]), disputes=DisputeAdapterTable([]),
        operations=store, peer=Peer(), end_journal=store.end_journal, evidence=store,
        watchdog=store.watchdog,
    )
    store.watchdog.opt_in("deal", SETTINGS)
    store.watchdog.record_probe("deal", INSTANT)

    source.set(INSTANT + fresh)
    assert asyncio.run(buyer.buyer_read("deal"))["watchdog"]["status"] == "monitored"
    source.set(INSTANT + fresh + 1)
    assert asyncio.run(buyer.buyer_read("deal"))["watchdog"]["status"] == "unmonitored"
