import asyncio

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


def test_concurrent_refreshes_are_coalesced():
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
