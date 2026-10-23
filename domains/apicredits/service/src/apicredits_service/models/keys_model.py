"""The authority's wire models, bound to this service's issuance label."""

from __future__ import annotations

from arkhai_api.labels import IssuanceLabel
from arkhai_api_contracts.models import (
    AdjustRequest,
    ConsumeBatchItem,
    ConsumeBatchRequest,
    ConsumeBatchResponse,
    ConsumeRequest,
    GrantListResponse,
    KeyDisposition,
    KeyListResponse,
    UsageListResponse,
    VerifyRequest,
    issuance_request_model,
    issuance_response_model,
)

# Recorded grants carry the singular identity prefix, which no rule derives
# from the label's name.
ISSUANCE_LABEL = IssuanceLabel("api-credits", "api-credit-fulfillment.v1")
IssuanceRequest = issuance_request_model(ISSUANCE_LABEL)
IssuanceResponse = issuance_response_model(ISSUANCE_LABEL)

__all__ = [
    "ISSUANCE_LABEL",
    "AdjustRequest",
    "ConsumeBatchItem",
    "ConsumeBatchRequest",
    "ConsumeBatchResponse",
    "ConsumeRequest",
    "GrantListResponse",
    "IssuanceRequest",
    "IssuanceResponse",
    "KeyDisposition",
    "KeyListResponse",
    "UsageListResponse",
    "VerifyRequest",
]
