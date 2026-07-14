"""Compatibility wrapper for shared lease lifecycle orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core_storefront.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleError,
    LeaseLifecycleService as CoreLeaseLifecycleService,
    LeaseNotFoundError,
    ReleaseDelegate,
)
from services.release_executors import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalReleaseExecutor,
    ExecutorReleaseDispatcher,
    VM_EXECUTOR_KIND,
    VmReleaseExecutor,
)
from services.site_resources_service import SiteResourcesService

logger = logging.getLogger(__name__)


async def _notify_storefront_capacity_released(settings: Any, allocation: dict[str, Any]) -> bool:
    from storefront_client import StorefrontClient, StorefrontClientError

    storefront_url = str(getattr(settings, "storefront_url", "") or "").rstrip("/")
    storefront_admin_key = str(getattr(settings, "storefront_admin_key", "") or "")
    if not storefront_url:
        logger.warning(
            "[LEASE_LIFECYCLE] storefront_url not configured — skipping capacity-released event for allocation %s",
            allocation.get("allocation_id"),
        )
        return False
    try:
        async with StorefrontClient(
            base_url=storefront_url,
            admin_key=storefront_admin_key or None,
        ) as sf:
            await sf.notify_capacity_released(
                str(allocation["allocation_id"]),
                resource_id=allocation.get("resource_id"),
                released_at=allocation.get("released_at"),
            )
        return True
    except StorefrontClientError as exc:
        logger.warning(
            "[LEASE_LIFECYCLE] capacity-released event rejected by storefront for allocation %s: %s",
            allocation.get("allocation_id"), exc,
        )
        return False
    except Exception as exc:
        logger.warning(
            "[LEASE_LIFECYCLE] Could not deliver capacity-released event for allocation %s: %s",
            allocation.get("allocation_id"), exc,
        )
        return False


class LeaseLifecycleService(CoreLeaseLifecycleService):
    """VM provisioning compatibility wrapper around the shared service."""

    def __init__(
        self,
        settings,
        site_resources_service: SiteResourcesService | None = None,
        *,
        capacity_ledger=None,
        job_service=None,
        job_queue_provider: Callable[[], Any] | None = None,
        release_delegate: ReleaseDelegate | None = None,
        release_dispatcher: ExecutorReleaseDispatcher | None = None,
    ) -> None:
        site_resources = site_resources_service or SiteResourcesService(capacity_ledger)
        dispatcher = release_dispatcher or ExecutorReleaseDispatcher({
            BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(),
            VM_EXECUTOR_KIND: VmReleaseExecutor(
                job_service=job_service,
                job_queue_provider=job_queue_provider,
            ),
        })
        super().__init__(
            settings,
            site_resources,
            release_delegate=release_delegate or dispatcher.submit_release,
            job_service=job_service,
            default_executor_kind=VM_EXECUTOR_KIND,
            capacity_released_notifier=(
                lambda allocation: _notify_storefront_capacity_released(
                    settings, allocation,
                )
            ),
        )


__all__ = [
    "InvalidLeaseStateError",
    "LeaseLifecycleError",
    "LeaseLifecycleService",
    "LeaseNotFoundError",
    "ReleaseDelegate",
]
