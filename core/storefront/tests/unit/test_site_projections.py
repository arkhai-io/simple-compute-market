import asyncio
from datetime import datetime, timezone

from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)


class FakeClient:
    def __init__(self):
        self.identity = ProjectionIdentity(1, "a")
        self.value = ["one"]
        self.fail_version = False
        self.snapshot_calls = 0

    async def version(self):
        if self.fail_version:
            raise RuntimeError("offline")
        return self.identity

    async def snapshot(self):
        self.snapshot_calls += 1
        await asyncio.sleep(0)
        return self.identity, list(self.value)


def test_load_and_unchanged_poll():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        assert (await cache.load()).state == ProjectionState.loaded
        await cache.poll_once()
        assert client.snapshot_calls == 1
    asyncio.run(run())


def test_changed_identity_atomically_replaces_generation():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.identity = ProjectionIdentity(2, "b")
        client.value = ["two"]
        view = await cache.poll_once()
        assert view.value == ["two"]
        assert view.identity == client.identity
    asyncio.run(run())


def test_poll_failure_retains_last_complete_generation_as_stale():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.fail_version = True
        view = await cache.poll_once()
        assert view.state == ProjectionState.stale
        assert view.value == ["one"]
    asyncio.run(run())


def test_concurrent_forced_refreshes_never_overlap():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        await asyncio.gather(cache.refresh(force=True), cache.refresh(force=True))
        # The lock prevents partial overlap; callers see complete generations.
        assert cache.view().state == ProjectionState.loaded
    asyncio.run(run())


def test_refresh_after_topology_error_detects_drift_and_updates_cache():
    """The reactive path a topology-sensitive HTTP failure (404/409/422)
    triggers: report whether the identity observed before the failure is
    now stale, and if so, the cache already reflects the new generation."""
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        observed = (await cache.load()).identity
        client.identity = ProjectionIdentity(2, "b")
        client.value = ["two"]
        drifted = await cache.refresh_after_topology_error(observed)
        assert drifted is True
        assert cache.view().value == ["two"]
        assert cache.view().identity == client.identity
    asyncio.run(run())


def test_refresh_after_topology_error_reports_no_drift_when_unchanged():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        observed = (await cache.load()).identity
        drifted = await cache.refresh_after_topology_error(observed)
        assert drifted is False
        assert cache.view().value == ["one"]
    asyncio.run(run())


def test_refresh_after_topology_error_falls_back_to_current_identity_when_none_observed():
    """A caller with no prior observed identity (e.g. first-ever call)
    passes None; the cache's own last-known identity is the baseline."""
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        await cache.load()
        drifted = await cache.refresh_after_topology_error(None)
        assert drifted is False
    asyncio.run(run())


def test_fetched_at_is_none_before_any_successful_load():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        assert cache.view().fetched_at is None
    asyncio.run(run())


def test_fetched_at_set_on_successful_load():
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        before = datetime.now(timezone.utc)
        view = await cache.load()
        assert view.fetched_at is not None
        assert before <= view.fetched_at
    asyncio.run(run())


def test_fetched_at_advances_on_unchanged_poll_confirmation():
    """An unchanged poll_once() is still a successful confirmation -- the
    operator-visible 'last confirmed' time should advance even when the
    generation itself didn't change."""
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        first = (await cache.load()).fetched_at
        await asyncio.sleep(0.01)
        second = (await cache.poll_once()).fetched_at
        assert second is not None and second > first
    asyncio.run(run())


def test_fetched_at_unchanged_on_failed_poll():
    """A failed poll must not advance fetched_at -- it did not confirm anything."""
    async def run():
        client = FakeClient()
        cache = ProjectionCache(client)
        loaded_at = (await cache.load()).fetched_at
        client.fail_version = True
        view = await cache.poll_once()
        assert view.state == ProjectionState.stale
        assert view.fetched_at == loaded_at


async def _let_new_tasks_reach_their_wait() -> None:
    """Run each task created since the last await up to its first suspension.

    The one wait point these tests cannot observe through the fake client is a
    caller parked inside the cache -- queued on its lock, or joined to its
    running operation -- because parking there calls nothing. Exposing it would
    put a test hook in production code, so the tests yield once instead: tasks
    run in creation order, and each reaches the cache's lock or its join before
    this returns. Where a caller that failed to join would poll for itself, the
    recorded calls show it, so a missed join fails the test rather than passing.
    """

    await asyncio.sleep(0)


class GatedClient(FakeClient):
    """A client whose calls the test can hold open and fail on demand.

    Every call is recorded in order. A held call parks on its event until the
    test releases it, so overlapping operations are ordered by the test rather
    than by scheduling.
    """

    def __init__(self):
        super().__init__()
        self.calls: list[str] = []
        self.version_entered = asyncio.Event()
        self.version_gate: asyncio.Event | None = None
        self.snapshot_entered = asyncio.Event()
        self.snapshot_gate: asyncio.Event | None = None

    async def version(self):
        self.calls.append("version")
        self.version_entered.set()
        if self.version_gate is not None:
            await self.version_gate.wait()
        return await super().version()

    async def snapshot(self):
        self.calls.append("snapshot")
        self.snapshot_entered.set()
        if self.snapshot_gate is not None:
            await self.snapshot_gate.wait()
        return await super().snapshot()


def test_a_poll_and_a_refresh_started_together_run_once_each_in_order():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        await asyncio.gather(cache.poll_once(), cache.refresh(force=True))
        assert client.calls == ["version", "snapshot"]
        assert cache.view().state == ProjectionState.loaded
    asyncio.run(run())


def test_a_refresh_requested_during_a_poll_waits_for_it_before_fetching():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.version_gate = asyncio.Event()
        poll = asyncio.create_task(cache.poll_once())
        await asyncio.wait_for(client.version_entered.wait(), timeout=1)
        refresh = asyncio.create_task(cache.refresh(force=True))
        await _let_new_tasks_reach_their_wait()
        assert client.calls == ["version"]
        client.version_gate.set()
        await asyncio.wait_for(asyncio.gather(poll, refresh), timeout=1)
        assert client.calls == ["version", "snapshot"]
    asyncio.run(run())


def test_a_poll_arriving_during_an_operation_returns_its_result_without_polling():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.snapshot_gate = asyncio.Event()
        client.identity = ProjectionIdentity(2, "b")
        client.value = ["two"]
        refresh = asyncio.create_task(cache.refresh(force=True))
        await asyncio.wait_for(client.snapshot_entered.wait(), timeout=1)
        polls = [asyncio.create_task(cache.poll_once()) for _ in range(2)]
        await _let_new_tasks_reach_their_wait()
        client.snapshot_gate.set()
        views = await asyncio.wait_for(asyncio.gather(refresh, *polls), timeout=1)
        assert client.calls == ["snapshot"]
        assert {view.value[0] for view in views} == {"two"}
    asyncio.run(run())


def test_concurrent_polls_check_the_version_once():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.version_gate = asyncio.Event()
        first = asyncio.create_task(cache.poll_once())
        await asyncio.wait_for(client.version_entered.wait(), timeout=1)
        others = [asyncio.create_task(cache.poll_once()) for _ in range(2)]
        await _let_new_tasks_reach_their_wait()
        client.version_gate.set()
        views = await asyncio.wait_for(asyncio.gather(first, *others), timeout=1)
        assert client.calls == ["version"]
        assert {view.state for view in views} == {ProjectionState.loaded}
    asyncio.run(run())


def test_a_failing_version_check_never_replaces_a_later_confirmation():
    """A version check that began before a successful refresh completed fails
    first, and the refresh requested after it then confirms the generation."""
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        loaded_at = (await cache.load()).fetched_at
        client.version_gate = asyncio.Event()
        client.fail_version = True
        poll = asyncio.create_task(cache.poll_once())
        await asyncio.wait_for(client.version_entered.wait(), timeout=1)
        refresh = asyncio.create_task(cache.refresh(force=True))
        await _let_new_tasks_reach_their_wait()
        client.version_gate.set()
        polled, refreshed = await asyncio.wait_for(
            asyncio.gather(poll, refresh), timeout=1
        )
        assert polled.state == ProjectionState.stale
        assert refreshed.state == ProjectionState.loaded
        view = cache.view()
        assert view.state == ProjectionState.loaded
        assert view.last_error is None
        assert view.fetched_at is not None and view.fetched_at > loaded_at
    asyncio.run(run())


def test_a_drift_check_during_a_poll_shares_its_version_check():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        observed = (await cache.load()).identity
        client.calls.clear()
        client.version_gate = asyncio.Event()
        client.identity = ProjectionIdentity(2, "b")
        client.value = ["two"]
        poll = asyncio.create_task(cache.poll_once())
        await asyncio.wait_for(client.version_entered.wait(), timeout=1)
        drift = asyncio.create_task(cache.refresh_after_topology_error(observed))
        await _let_new_tasks_reach_their_wait()
        client.version_gate.set()
        _, drifted = await asyncio.wait_for(asyncio.gather(poll, drift), timeout=1)
        assert drifted is True
        assert client.calls == ["version", "snapshot"]
        assert cache.view().value == ["two"]
    asyncio.run(run())


def test_a_poll_joined_to_a_cancelled_operation_polls_for_itself():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.snapshot_gate = asyncio.Event()
        refresh = asyncio.create_task(cache.refresh(force=True))
        await asyncio.wait_for(client.snapshot_entered.wait(), timeout=1)
        poll = asyncio.create_task(cache.poll_once())
        await _let_new_tasks_reach_their_wait()
        refresh.cancel()
        view = await asyncio.wait_for(poll, timeout=1)
        assert view.state == ProjectionState.loaded
        assert client.calls == ["snapshot", "version"]
    asyncio.run(run())


def test_refresh_without_force_is_a_poll():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        view = await asyncio.wait_for(cache.refresh(), timeout=1)
        assert view.state == ProjectionState.loaded
        assert client.calls == ["version"]
    asyncio.run(run())


def test_an_unforced_refresh_after_a_remote_change_fetches_the_new_generation():
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.identity = ProjectionIdentity(2, "b")
        client.value = ["two"]
        view = await asyncio.wait_for(cache.refresh(), timeout=1)
        assert view.value == ["two"]
        assert client.calls == ["version", "snapshot"]
    asyncio.run(run())


def test_a_cancelled_caller_joined_to_a_cancelled_operation_does_not_poll():
    """When the joined operation and the joining caller are both cancelled, the
    caller's own cancellation wins: it neither polls nor returns a view."""
    async def run():
        client = GatedClient()
        cache = ProjectionCache(client)
        await cache.load()
        client.calls.clear()
        client.snapshot_gate = asyncio.Event()
        refresh = asyncio.create_task(cache.refresh(force=True))
        await asyncio.wait_for(client.snapshot_entered.wait(), timeout=1)
        poll = asyncio.create_task(cache.poll_once())
        await _let_new_tasks_reach_their_wait()
        refresh.cancel()
        poll.cancel()
        results = await asyncio.wait_for(
            asyncio.gather(refresh, poll, return_exceptions=True), timeout=1
        )
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert client.calls == ["snapshot"]
        assert cache.view().state == ProjectionState.loaded
    asyncio.run(run())
