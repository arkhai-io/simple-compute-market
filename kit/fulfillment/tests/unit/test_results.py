import pytest
from pydantic import ValidationError

from market_fulfillment import (
    FULFILLMENT_RESULT_KIND,
    FULFILLMENT_RESULT_SCHEMA_VERSION,
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    VersionedEnvelope,
    build_fulfillment_result_envelope,
)


def test_build_fulfillment_result_envelope_shape():
    payload = FulfillmentResultPayload(
        fulfillment_id="fulfillment-1",
        capacity_reservation_id="reservation-1",
        state="active",
        provisioned_resources=(
            ProvisionedResourceOutput(
                provisioned_resource_id="provisioned-1",
                domain_resource_ref="vm-1",
                status="active",
            ),
        ),
    )

    result = build_fulfillment_result_envelope(payload)

    assert result.kind == FULFILLMENT_RESULT_KIND
    assert result.schema_version == FULFILLMENT_RESULT_SCHEMA_VERSION
    assert result.payload["fulfillment_id"] == "fulfillment-1"
    assert result.payload["provisioned_resources"][0]["domain_resource_ref"] == "vm-1"
    # Never populated by this construction path yet -- no provider fetch exists.
    assert result.payload["credentials"] == []


def test_fulfillment_result_payload_defaults_are_empty():
    payload = FulfillmentResultPayload(
        fulfillment_id="fulfillment-1",
        capacity_reservation_id="reservation-1",
        state="dispatch_pending",
    )

    assert payload.provisioned_resources == ()
    assert payload.credentials == ()
    assert payload.failure_reason is None


def test_fulfillment_result_payload_is_frozen():
    payload = FulfillmentResultPayload(
        fulfillment_id="fulfillment-1",
        capacity_reservation_id="reservation-1",
        state="active",
    )

    with pytest.raises(ValidationError):
        payload.state = "torn_down"


def test_envelope_round_trips_through_the_generic_versioned_envelope():
    payload = FulfillmentResultPayload(
        fulfillment_id="fulfillment-1",
        capacity_reservation_id="reservation-1",
        state="failed",
        failure_reason="create_failed",
        failure_message="provider reported a create failure",
    )

    result = build_fulfillment_result_envelope(payload)
    restored = VersionedEnvelope[dict].model_validate_json(result.model_dump_json())

    assert restored.payload["failure_reason"] == "create_failed"
