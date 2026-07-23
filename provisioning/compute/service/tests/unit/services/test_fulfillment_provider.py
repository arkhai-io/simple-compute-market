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


def test_fulfillment_result_carries_only_provider_metadata():
    result = FulfillmentResult(provider_metadata={"job_id": "abc"})
    assert result.provider_metadata == {"job_id": "abc"}
    assert not hasattr(result, "credentials")


def test_provider_status_defaults_detail_to_none():
    status = ProviderStatus(state=ProviderOperationState.pending)
    assert status.detail is None

    status_with_detail = ProviderStatus(
        state=ProviderOperationState.failed, detail="boom"
    )
    assert status_with_detail.detail == "boom"
