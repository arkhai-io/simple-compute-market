"""Unit tests for FulfillmentProvider contract dataclasses/enum."""

from __future__ import annotations

from market_fulfillment import (
    FulfillmentResult,
    ProviderOperationState,
    ProviderStatus,
)


def test_provider_operation_state_values():
    assert {s.value for s in ProviderOperationState} == {
        "pending",
        "succeeded",
        "failed",
        "unknown",
    }


def test_fulfillment_result_carries_metadata_and_domain_output_references():
    result = FulfillmentResult(
        provider_metadata={"job_id": "abc"},
        provisioned_resource_refs=("domain-resource-1",),
    )
    assert result.provider_metadata == {"job_id": "abc"}
    assert result.provisioned_resource_refs == ("domain-resource-1",)
    assert not hasattr(result, "credentials")


def test_provider_status_defaults_detail_to_none():
    status = ProviderStatus(state=ProviderOperationState.pending)
    assert status.detail is None

    status_with_detail = ProviderStatus(
        state=ProviderOperationState.failed, detail="boom"
    )
    assert status_with_detail.detail == "boom"
