"""The job routes' validation, refusals, and response shapes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from compute_provisioning.jobs.route_service import JobRouteService, JobTestRouteService
from compute_provisioning.route_errors import ProvisioningRouteError


def _jobs(*statuses: str) -> SimpleNamespace:
    return SimpleNamespace(
        jobs=[SimpleNamespace(status=status) for status in statuses], total=len(statuses)
    )


class TestJobRouteService:
    @pytest.mark.parametrize(
        "query",
        [{"offset": -1}, {"limit": 0}, {"limit": 101}, {"sort": "newest"}],
    )
    def test_an_impossible_page_or_sort_is_refused(self, query):
        engine = MagicMock()

        with pytest.raises(ProvisioningRouteError) as refused:
            JobRouteService(engine).list_jobs(**query)

        assert refused.value.status_code == 422
        engine.list_jobs.assert_not_called()

    def test_a_listing_passes_its_filters_to_the_engine(self):
        engine = MagicMock()

        JobRouteService(engine).list_jobs(
            offset=5, limit=10, status="failed", capacity_reservation_id="r-1"
        )

        engine.list_jobs.assert_called_once_with(
            offset=5,
            limit=10,
            status_filter="failed",
            sort="created_at_desc",
            capacity_reservation_id="r-1",
        )

    @pytest.mark.parametrize("read", ["get_job", "get_credentials", "get_logs"])
    def test_an_unknown_job_is_not_found(self, read):
        engine = MagicMock()
        getattr(engine, read).side_effect = LookupError("Job j-1 not found")

        with pytest.raises(ProvisioningRouteError) as refused:
            getattr(JobRouteService(engine), read)("j-1")

        assert (refused.value.status_code, refused.value.detail) == (404, "Job j-1 not found")

    @pytest.mark.asyncio
    async def test_cancelling_an_unknown_job_is_not_found(self):
        engine = MagicMock()
        engine.cancel_job = AsyncMock(side_effect=LookupError("Job j-1 not found"))

        with pytest.raises(ProvisioningRouteError) as refused:
            await JobRouteService(engine).cancel_job("j-1")

        assert refused.value.status_code == 404


class TestJobTestRouteService:
    def test_a_summary_counts_jobs_by_status(self):
        engine = MagicMock()
        engine.list_jobs.return_value = _jobs("queued", "running", "succeeded", "failed", "failed")

        summary = JobTestRouteService(engine).summary()

        assert summary == {
            "counts": {"queued": 1, "running": 1, "succeeded": 1, "failed": 2},
            "total": 5,
            "total_terminal": 3,
            "total_active": 2,
        }

    @pytest.mark.asyncio
    async def test_a_drain_returns_at_once_when_every_job_is_terminal(self):
        engine = MagicMock()
        engine.list_jobs.return_value = _jobs("succeeded", "cancelled")

        assert await JobTestRouteService(engine).drain(timeout=0) == {
            "drained": True,
            "counts": {"succeeded": 1, "cancelled": 1},
        }

    @pytest.mark.asyncio
    async def test_a_drain_with_active_jobs_at_its_deadline_is_refused(self):
        engine = MagicMock()
        engine.list_jobs.return_value = _jobs("running")

        with pytest.raises(ProvisioningRouteError) as refused:
            await JobTestRouteService(engine).drain(timeout=0)

        assert refused.value.status_code == 408

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("raised", "status"), [(LookupError("gone"), 404), (TimeoutError("late"), 408)])
    async def test_a_wait_maps_absence_and_lateness(self, raised, status):
        engine = MagicMock()
        engine.wait_for_terminal = AsyncMock(side_effect=raised)

        with pytest.raises(ProvisioningRouteError) as refused:
            await JobTestRouteService(engine).wait("j-1", timeout=1)

        assert refused.value.status_code == status

    @pytest.mark.asyncio
    async def test_a_wait_returns_the_final_status(self):
        engine = MagicMock()
        engine.wait_for_terminal = AsyncMock(
            return_value=SimpleNamespace(status="failed", result=None, error="boom")
        )

        assert await JobTestRouteService(engine).wait("j-1", timeout=1) == {
            "job_id": "j-1",
            "status": "failed",
            "result": None,
            "error": "boom",
        }
