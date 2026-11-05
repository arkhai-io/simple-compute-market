import asyncio
import threading
from market_deal_servicing import (
    DeliveryIngress, EndService, SQLiteEvidenceStore,
)
from market_deal_servicing.evidence import transaction


async def test_constructors_do_not_open_sqlite_on_the_event_loop(rig, tmp_path):
    # The parent does not exist: opening SQLite here would fail synchronously.
    path = tmp_path / "not-created" / "storefront.sqlite"
    EndService(path, rig["physical"], clock=lambda: 150)
    DeliveryIngress(path, clock=lambda: 150, verify_site=lambda *_: None)
    SQLiteEvidenceStore(path)
    watch = rig["watch"]()
    assert not path.exists()
    assert watch.path == rig["path"]


async def test_watch_retention_and_database_callbacks_are_off_loop(rig):
    loop_thread = threading.get_ident()
    threads = []
    watch = rig["watch"]()
    watch.observe_retention = lambda _: threads.append(threading.get_ident())
    await watch.poll()
    assert threads and threads[0] != loop_thread


async def test_busy_database_does_not_block_an_unrelated_coroutine(rig):
    # Hold the writer in a worker, then let an unrelated event-loop callback
    # release it. A synchronous connection on the loop cannot reach that release.
    locked = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def hold():
        with transaction(rig["path"]):
            loop.call_soon_threadsafe(locked.set)
            assert release.wait(timeout=3)

    holder = asyncio.create_task(asyncio.to_thread(hold))
    await locked.wait()
    reader = asyncio.create_task(rig["service"]().read("deal"))
    await asyncio.sleep(0)  # Explicit scheduling turn, not elapsed-time synchronization.
    release.set()
    await holder
    assert (await reader).authority.outcome.status == "accepted"
