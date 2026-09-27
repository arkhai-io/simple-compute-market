"""Field-set contract of the storefront's fulfillment-event models."""

from __future__ import annotations

from market_storefront.models.capacity_admin_models import (
    ReleaseStartedEventRequest,
)


def test_release_started_event_carries_no_release_handle():
    """The event records that release began; the handle a caller follows is
    the site authority's, published on its lease contract."""
    assert not {
        name for name in ReleaseStartedEventRequest.model_fields
        if name.endswith("_job_id")
    }
