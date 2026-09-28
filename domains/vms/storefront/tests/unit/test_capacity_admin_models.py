"""Field-set contract of the storefront's fulfillment-event models."""

from __future__ import annotations

from market_storefront.models.capacity_admin_models import (
    ReleaseStartedEventRequest,
)

_RETIRED = "vm_remove_job_id"


def test_release_started_event_defines_no_vm_release_handle():
    assert _RETIRED not in ReleaseStartedEventRequest.model_fields


def test_release_started_event_ignores_the_retired_name_like_any_unknown_field():
    """The retired name is not refused: an event carrying it is accepted and
    the value is dropped, as for any field the model does not define."""
    event = ReleaseStartedEventRequest.model_validate(
        {
            "capacity_reservation_id": "reservation-1",
            "site_id": "site-1",
            _RETIRED: "fulfillment-1",
        }
    )

    assert event.capacity_reservation_id == "reservation-1"
    assert _RETIRED not in event.model_dump()
