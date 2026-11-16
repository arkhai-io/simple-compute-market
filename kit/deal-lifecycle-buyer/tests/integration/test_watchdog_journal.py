"""The watchdog's per-deal record in the buyer's SQLite evidence file, and the read it composes."""

import asyncio

from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle_contracts.models import AuthorityView, DeliveryView, LifecycleRead, Rejected
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle, FileEvidenceStore, WatchdogSettings, WatchdogStop
from market_deal_lifecycle_buyer.watchdog import ProbeObservation


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
        # The status and the funding stop sit beside the lifecycle read, never inside it.
        assert LifecycleRead.model_validate({k: v for k, v in read.items() if k not in {"watchdog", "funding_stop"}})

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
