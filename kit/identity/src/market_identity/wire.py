"""The version 3 marketplace wire names: header fields, profile tags, and refusal codes.

Every client and authority speaking the version 3 profile imports these names from
here, so a field's spelling or a refusal's code has one definition the signer, the
verifier and every reader of a refusal body share.
"""

from __future__ import annotations

from enum import Enum

#: The signature tag of a version 3 request, and of a signed delivery.
REQUEST_PROFILE = "arkhai.market-request.v3"
#: The signature tag of a version 3 response.
RESPONSE_PROFILE = "arkhai.market-response.v3"

#: The label the profile signs under. Labels are not covered by a signature, so a
#: verifier selects a signature by its tag and accepts it under any label.
SIGNATURE_LABEL = "market"

MARKET_ROLE = "Market-Role"
MARKET_OPERATION = "Market-Operation"
MARKET_RESOURCE = "Market-Resource"
#: A structured list of the principals the caller would accept the answer from.
MARKET_AUDIENCE = "Market-Audience"
MARKET_REQUEST_ID = "Market-Request-ID"
#: The request's first signing instant, unchanged on every retry under its request ID.
MARKET_REQUEST_ORIGIN = "Market-Request-Origin"
CONTENT_DIGEST = "Content-Digest"
SIGNATURE_INPUT = "Signature-Input"
SIGNATURE = "Signature"


class RefusalCode(str, Enum):
    """The body codes of the profile's refusals and exact-retry answers."""

    OPERATION_NOT_SERVED = "operation_not_served"
    OPERATION_MISMATCH = "operation_mismatch"
    AUDIENCE_MISMATCH = "audience_mismatch"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    EXACT_RETRY_EXPIRED = "exact_retry_expired"
    EXACT_RETRY_OUTCOME_UNKNOWN = "exact_retry_outcome_unknown"


__all__ = [
    "CONTENT_DIGEST",
    "MARKET_AUDIENCE",
    "MARKET_OPERATION",
    "MARKET_REQUEST_ID",
    "MARKET_REQUEST_ORIGIN",
    "MARKET_RESOURCE",
    "MARKET_ROLE",
    "REQUEST_PROFILE",
    "RESPONSE_PROFILE",
    "RefusalCode",
    "SIGNATURE",
    "SIGNATURE_INPUT",
    "SIGNATURE_LABEL",
]
