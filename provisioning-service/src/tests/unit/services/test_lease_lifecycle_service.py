"""Unit tests for LeaseLifecycleService.

Scope:
  - check_leases: processes pending→active activation
  - check_leases: processes due leases, calls _patch_storefront_resource
  - check_leases: returns correct counts (activated, checked, released, forced, skipped)
  - check_leases: grace period logic — skips within grace, forces past grace
  - _patch_storefront_resource: reads storefront_url/admin_key from settings
  - _patch_storefront_resource: returns True on 200, True on 404 (idempotent),
    False on other errors and network failures
  - _patch_storefront_resource: correct URL construction and headers

External boundaries mocked: httpx.AsyncClient (storefront HTTP calls).
LeaseService uses a real in-memory SQLite DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from db.database import create_session_factory
from db.models import Base, LeaseStatus, VmLease
from models.lease_model import LeaseCreate
from services.lease_lifecycle_service import LeaseLifecycleService
from services.lease_service import LeaseService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def lease_svc(session_factory):
    return LeaseService(session_factory=session_factory)


def _make_settings(**overrides):
    s = MagicMock()
    s.lease_watchdog_grace_period_seconds = 300
    s.storefront_url = "http://storefront:8001"
    s.storefront_admin_key = "admin-key"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_check_svc(lease_svc, **settings_overrides):
    return LeaseLifecycleService(
        lease_service=lease_svc,
        settings=_make_settings(**settings_overrides),
        job_service=None,  # unit tests: no job service, direct patch path
    )


def _expired_lease_data(
    resource_id: str = "compute-ww1-001",
    escrow_uid: str = "escrow-test",
    vm_host: str = "ww1",
    vm_target: str = "tenant-a1b2",
    seconds_ago: int = 10,
) -> LeaseCreate:
    return LeaseCreate(
        resource_id=resource_id,
        escrow_uid=escrow_uid,
        vm_host=vm_host,
        vm_target=vm_target,
        lease_end_utc=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
    )


# ---------------------------------------------------------------------------
# check_leases — activation of pending leases
# ---------------------------------------------------------------------------

class TestCheckLeasesActivation:
    @pytest.mark.asyncio
    async def test_activates_pending_lease_with_past_start(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        future_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        data = LeaseCreate(
            resource_id="r1",
            escrow_uid="e-activate",
            vm_host="ww1",
            vm_target="t1",
            lease_start_utc=future_start,
            lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        lease = lease_svc.create(data)
        assert lease.status == LeaseStatus.active.value  # past start → active at create

        # pending with future start that has now passed
        future_start2 = datetime.now(timezone.utc) + timedelta(hours=1)
        data2 = LeaseCreate(
            resource_id="r2",
            escrow_uid="e-activate2",
            vm_host="ww1",
            vm_target="t2",
            lease_start_utc=future_start2,
            lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=3),
        )
        lease2 = lease_svc.create(data2)
        assert lease2.status == LeaseStatus.pending.value

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=True)):
            result = await svc.check_leases()

        # pending lease start is still in the future — should NOT be activated
        assert result["activated"] == 0

    @pytest.mark.asyncio
    async def test_activated_count_in_summary(self, lease_svc):
        """A pending lease with lease_start_utc now in the past is activated."""
        svc = _make_check_svc(lease_svc)
        # Create with a far-future lease_end but set status to pending manually
        lease = lease_svc.create(LeaseCreate(
            resource_id="r-act",
            escrow_uid="e-act-manual",
            vm_host="ww1",
            vm_target="t1",
            lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=2),
        ))
        # Manually force to pending (simulate a deferred start that has now passed)
        from models.lease_model import LeaseUpdate
        lease_svc.update(lease.id, LeaseUpdate(status=LeaseStatus.pending.value))

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=True)):
            result = await svc.check_leases()

        assert result["activated"] == 1
        updated = lease_svc.get_lease(lease.id)
        assert updated.status == LeaseStatus.active.value


# ---------------------------------------------------------------------------
# check_leases — happy path
# ---------------------------------------------------------------------------

class TestCheckLeasesHappyPath:
    @pytest.mark.asyncio
    async def test_releases_expired_active_lease(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        lease = lease_svc.create(_expired_lease_data())

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=True)):
            result = await svc.check_leases()

        # With no job_service, _begin_release patches directly and marks released
        assert result["released"] == 1
        assert result["checked"] == 0  # checked = check jobs submitted; 0 when no job_svc
        updated = lease_svc.get_lease(lease.id)
        assert updated.status == LeaseStatus.released.value

    @pytest.mark.asyncio
    async def test_no_due_leases_returns_zero_counts(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        result = await svc.check_leases()
        assert result == {
            "activated": 0, "checked": 0, "released": 0, "forced": 0, "skipped": 0
        }

    @pytest.mark.asyncio
    async def test_skips_already_released_leases(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        lease = lease_svc.create(_expired_lease_data(escrow_uid="e-already-done"))
        lease_svc.mark_released(lease.id)

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=True)):
            result = await svc.check_leases()

        assert result["released"] == 0  # already released, not in list_due


# ---------------------------------------------------------------------------
# check_leases — grace period and force
# ---------------------------------------------------------------------------

class TestCheckLeasesGracePeriod:
    @pytest.mark.asyncio
    async def test_skips_when_patch_fails_within_grace(self, lease_svc):
        """Storefront unreachable within grace period → skipped, not forced."""
        svc = _make_check_svc(lease_svc, lease_watchdog_grace_period_seconds=300)
        lease = lease_svc.create(_expired_lease_data(seconds_ago=10))

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=False)):
            result = await svc.check_leases()

        assert result["skipped"] == 1
        assert result["forced"] == 0
        # No job_service → _begin_release calls patch directly, skipped means
        # lease stays active (the direct-patch path in _begin_release just logs warning)
        updated = lease_svc.get_lease(lease.id)
        assert updated.status == LeaseStatus.active.value

    @pytest.mark.asyncio
    async def test_forces_releasing_lease_past_grace(self, lease_svc):
        """releasing lease past grace period → forced when patch also fails."""
        svc = _make_check_svc(lease_svc, lease_watchdog_grace_period_seconds=5)
        # Create an expired lease and manually put it in releasing state
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        data = LeaseCreate(
            resource_id="r-force",
            escrow_uid="e-force",
            vm_host="ww1",
            vm_target="t1",
            lease_end_utc=past,
        )
        lease = lease_svc.create(data)
        # Manually transition to releasing (as if check job was submitted)
        lease_svc.begin_releasing(lease.id, check_job_id="fake-job-id")

        with patch.object(svc, "_patch_storefront_resource", new=AsyncMock(return_value=False)):
            result = await svc.check_leases()

        assert result["forced"] == 1
        updated = lease_svc.get_lease(lease.id)
        assert updated.status == LeaseStatus.forced.value


# ---------------------------------------------------------------------------
# _patch_storefront_resource
# ---------------------------------------------------------------------------

class TestPatchStorefrontResource:
    def _make_fake_lease(self, resource_id="r1"):
        lease = VmLease()
        lease.id = "test-lease-id"
        lease.resource_id = resource_id
        lease.escrow_uid = "esc-1"
        lease.vm_host = "ww1"
        lease.vm_target = "t1"
        return lease

    @pytest.mark.asyncio
    async def test_returns_true_on_200(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        lease = self._make_fake_lease()

        mock_resp = MagicMock(status_code=200)
        with patch("services.lease_lifecycle_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.patch = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            result = await svc._patch_storefront_resource(lease)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_404(self, lease_svc):
        """404 means resource already gone — idempotent, treat as success."""
        svc = _make_check_svc(lease_svc)
        lease = self._make_fake_lease()

        mock_resp = MagicMock(status_code=404)
        with patch("services.lease_lifecycle_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.patch = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            result = await svc._patch_storefront_resource(lease)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_5xx(self, lease_svc):
        svc = _make_check_svc(lease_svc)
        lease = self._make_fake_lease()

        mock_resp = MagicMock(status_code=500)
        with patch("services.lease_lifecycle_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.patch = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            result = await svc._patch_storefront_resource(lease)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_connect_error(self, lease_svc):
        import httpx
        svc = _make_check_svc(lease_svc)
        lease = self._make_fake_lease()

        with patch("services.lease_lifecycle_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.patch = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_cls.return_value = mock_client
            result = await svc._patch_storefront_resource(lease)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_storefront_url_not_configured(self, lease_svc):
        svc = _make_check_svc(lease_svc, storefront_url="")
        lease = self._make_fake_lease()
        result = await svc._patch_storefront_resource(lease)
        assert result is False

    @pytest.mark.asyncio
    async def test_uses_global_url_and_admin_key_from_settings(self, lease_svc):
        """storefront_url and admin_key come from settings, not lease fields."""
        svc = _make_check_svc(
            lease_svc,
            storefront_url="http://mysf:8001",
            storefront_admin_key="my-key",
        )
        lease = self._make_fake_lease(resource_id="compute-ww1-001")

        mock_resp = MagicMock(status_code=200)
        with patch("services.lease_lifecycle_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.patch = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            await svc._patch_storefront_resource(lease)

        call_kwargs = mock_client.patch.call_args
        url = call_kwargs.args[0]
        assert "mysf:8001" in url
        assert "compute-ww1-001" in url
        assert call_kwargs.kwargs["json"]["state"] == "available"
        assert call_kwargs.kwargs["json"]["attributes"]["lease_end_utc"] is None
        assert call_kwargs.kwargs["headers"]["X-Admin-Key"] == "my-key"
