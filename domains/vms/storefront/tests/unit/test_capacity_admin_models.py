"""Field-set contract of the storefront's fulfillment-event models."""

from __future__ import annotations

from market_storefront.models.capacity_admin_models import (
    CapacityReleasedEventRequest,
    FulfillmentEventResponse,
)


def test_the_capacity_released_request_carries_its_release_fields():
    assert set(CapacityReleasedEventRequest.model_fields) == {
        "capacity_reservation_id",
        "site_id",
        "provider_lease_id",
        "resource_id",
        "released_at",
    }


def test_a_capacity_released_event_names_its_reservation_and_site():
    event = CapacityReleasedEventRequest.model_validate(
        {"capacity_reservation_id": "reservation-1", "site_id": "site-1"}
    )

    assert event.capacity_reservation_id == "reservation-1"
    assert event.site_id == "site-1"
    assert event.released_at is None


def test_the_event_response_reports_the_listings_it_changed():
    response = FulfillmentEventResponse(
        capacity_reservation_id="reservation-1",
        state="released",
        reopened_listing_ids=["listing-1"],
    )

    assert response.closed_listing_ids == []
    assert response.reopened_listing_ids == ["listing-1"]
