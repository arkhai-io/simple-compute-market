"""Unit tests for the per-site resource-pool/capacity-bucket projection cache."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from market_storefront.services import site_projection_cache as spc


class _FakeRemote:
    """Stands in for a `SiteCapacityClient`; each family method independently
    configurable to succeed or raise, so tests can simulate one site being
    reachable while another is not."""

    def __init__(self, *, fails: bool = False) -> None:
        self._fails = fails
        self.version_calls = 0
        self.snapshot_calls = 0

    async def _projection_version(self, key: str) -> dict[str, Any]:
        self.version_calls += 1
        if self._fails:
            raise ConnectionError(f"{key} unreachable")
        return {"revision": 1, "digest": "d1"}

    async def _projection(self, key: str) -> dict[str, Any]:
        self.snapshot_calls += 1
        if self._fails:
            raise ConnectionError(f"{key} unreachable")
        return {"revision": 1, "digest": "d1", key: [{"resource_pool_id": "pool-1"}]}

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        return await self._projection_version("resource_pools")

    async def resource_pool_projection(self) -> dict[str, Any]:
        return await self._projection("resource_pools")

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        return await self._projection_version("capacity_buckets")

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        return await self._projection("capacity_buckets")

    def set_topology_error_handler(self, handler: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_caches():
    """`_caches` is a module global; isolate each test from the others."""
    spc._caches.clear()
    yield
    spc._caches.clear()


def _patched_remotes(remotes: dict[str, _FakeRemote]):
    return patch.multiple(
        spc,
        build_capacity_client=lambda _get_db: object(),
        remote_site_clients=lambda _aggregate: remotes,
    )


class TestLoadSiteProjectionsPartialFailure:
    async def test_one_site_failing_does_not_block_another_from_loading(self):
        """A site that fails its first load must not prevent a healthy site's
        cache from being populated -- both belong in `_caches` after
        `load_site_projections()`, with independently correct states."""
        healthy = _FakeRemote(fails=False)
        failing = _FakeRemote(fails=True)

        with _patched_remotes({"site-healthy": healthy, "site-failing": failing}):
            await spc.load_site_projections(object())

        caches = spc.projection_caches()
        assert set(caches) == {"site-healthy", "site-failing"}

        healthy_view = caches["site-healthy"].resource_pools.view()
        assert healthy_view.state.value == "loaded"

        failing_view = caches["site-failing"].resource_pools.view()
        assert failing_view.state.value == "invalid"
        assert failing_view.last_error is not None

    async def test_poller_retries_a_site_that_has_never_loaded(self):
        """Once a never-successfully-loaded site is in `_caches` (state
        `invalid`), the next poll cycle must attempt it again rather than
        giving up because it has no prior successful identity."""
        failing = _FakeRemote(fails=True)

        with _patched_remotes({"site-failing": failing}):
            await spc.load_site_projections(object())
            assert failing.snapshot_calls == 2  # resource_pools + capacity_buckets

            caches = spc.projection_caches()
            await caches["site-failing"].resource_pools.poll_once()

        # poll_once() checks version() first; a still-failing remote means
        # another attempt was made, proving the poller does not stop
        # retrying a site that has never once succeeded.
        assert failing.version_calls == 1


class TestProjectionStatusSummary:
    async def test_reports_state_identity_and_error_without_the_payload(self):
        healthy = _FakeRemote(fails=False)
        failing = _FakeRemote(fails=True)

        with _patched_remotes({"site-healthy": healthy, "site-failing": failing}):
            await spc.load_site_projections(object())

        summary = spc.projection_status_summary()

        assert summary["site-healthy"]["resource_pool"]["state"] == "loaded"
        assert summary["site-healthy"]["resource_pool"]["revision"] == 1
        assert summary["site-healthy"]["resource_pool"]["digest"] == "d1"
        assert summary["site-healthy"]["resource_pool"]["last_error"] is None
        # The payload itself (the list of resource-pool rows) must never
        # appear in the status summary -- only its identity and state.
        assert "value" not in summary["site-healthy"]["resource_pool"]
        assert "resource_pools" not in summary["site-healthy"]["resource_pool"]

        assert summary["site-failing"]["resource_pool"]["state"] == "invalid"
        assert summary["site-failing"]["resource_pool"]["revision"] is None
        assert summary["site-failing"]["resource_pool"]["last_error"] is not None

    async def test_empty_when_no_site_has_loaded_yet(self):
        assert spc.projection_status_summary() == {}


class _PayloadRemote:
    """A `_FakeRemote`-shaped stand-in that returns a caller-supplied
    resource-pool payload, for tests that need specific `pool_metadata`
    content rather than `_FakeRemote`'s fixed `[{"resource_pool_id": "pool-1"}]`.
    """

    def __init__(self, resource_pools: list[dict[str, Any]]) -> None:
        self._resource_pools = resource_pools

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        return {"revision": 1, "digest": "d1"}

    async def resource_pool_projection(self) -> dict[str, Any]:
        return {"revision": 1, "digest": "d1", "resource_pools": self._resource_pools}

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        return {"revision": 1, "digest": "d1"}

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        return {"revision": 1, "digest": "d1", "capacity_buckets": []}

    def set_topology_error_handler(self, handler: Any) -> None:
        pass


class TestListingModeExplanations:
    async def test_empty_when_nothing_loaded(self):
        assert spc.listing_mode_explanations() == {}

    async def test_no_explanation_for_a_recognized_or_absent_listing_mode(self):
        remote = _PayloadRemote([
            {"resource_pool_id": "gpu-pool-a", "resources": []},
            {
                "resource_pool_id": "gpu-pool-b", "resources": [],
                "pool_metadata": {"policy_tags": {"listing_mode": "specific_resource"}},
            },
        ])
        with _patched_remotes({"site-a": remote}):
            await spc.load_site_projections(object())
        assert spc.listing_mode_explanations() == {}

    async def test_explanation_for_an_unrecognized_listing_mode(self):
        remote = _PayloadRemote([
            {
                "resource_pool_id": "gpu-pool",
                "resources": [],
                "pool_metadata": {"policy_tags": {"listing_mode": "bogus"}},
            },
        ])
        with _patched_remotes({"site-a": remote}):
            await spc.load_site_projections(object())
        explanations = spc.listing_mode_explanations()
        assert set(explanations) == {"site-a"}
        assert "gpu-pool" in explanations["site-a"]
        assert "bogus" in explanations["site-a"]["gpu-pool"]

    async def test_one_sites_explanations_do_not_affect_another(self):
        clean = _PayloadRemote([{"resource_pool_id": "clean-pool", "resources": []}])
        bad = _PayloadRemote([
            {
                "resource_pool_id": "bad-pool", "resources": [],
                "pool_metadata": {"policy_tags": {"listing_mode": "bogus"}},
            },
        ])
        with _patched_remotes({"site-clean": clean, "site-bad": bad}):
            await spc.load_site_projections(object())
        explanations = spc.listing_mode_explanations()
        assert set(explanations) == {"site-bad"}
