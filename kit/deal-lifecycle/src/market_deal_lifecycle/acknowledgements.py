"""End-delivery receipt binding and offline verification under Agreement principals."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from market_deal_lifecycle_contracts.models import (
    AuthorityView, DeliveryView, EndDeliveryAcknowledgement, EndDeliveryMessage,
    Instant, LifecycleRead, Rejected, SignedEndDeliveryReceipt,
)
from market_deal_lifecycle_contracts.routes import lifecycle_route
from market_identity import Identity, TrustedIdentitySet, canonical_json, verify_request, verify_response
from pydantic import TypeAdapter


class ReceiptStore(Protocol):
    async def get_or_record(
        self, negotiation_id: str, operation_key: str, request_digest: str, received_at: int,
    ) -> int:
        """Atomically retain the first receipt, return it on retry, refuse changed content."""
        ...


async def receipt_time(request: EndDeliveryMessage, received_at: int, store: ReceiptStore) -> int:
    TypeAdapter(Instant).validate_python(received_at)
    digest = hashlib.sha256(canonical_json(request)).hexdigest()
    return await store.get_or_record(request.negotiation_id, request.operation_key, digest, received_at)


def verify_end_acknowledgement(
    receipt: SignedEndDeliveryReceipt, *, negotiation_id: str, buyer: Identity, seller: Identity,
) -> EndDeliveryAcknowledgement:
    """Verify kept evidence, not transport freshness, against the exact Agreement.

    Freshness/replay admission belongs to the live routes. Archived proofs
    remain verifiable long after receipt; each envelope's own timestamp is
    used here without treating it as a trustworthy independent clock.
    """
    request_body = json.loads(receipt.request_body)
    response_body = json.loads(receipt.response_body)
    request = EndDeliveryMessage.model_validate(request_body)
    acknowledgement = EndDeliveryAcknowledgement.model_validate(response_body)
    if (request.negotiation_id != negotiation_id or acknowledgement.negotiation_id != negotiation_id or
            acknowledgement.operation_key != request.operation_key):
        raise ValueError("end acknowledgement changed request identity")
    operation = lifecycle_route("lifecycle_peer")["operation"]
    request_result = verify_request(
        receipt.request, body=request_body, now=receipt.request.timestamp, max_skew=0,
        expected_role="buyer", expected_method="POST", expected_operation=operation,
        expected_resource=negotiation_id, expected_principals=TrustedIdentitySet(identities=(buyer,)),
    )
    if not request_result.verified:
        raise ValueError(f"end request signature binding failed: {request_result.code.value}")
    response_result = verify_response(
        receipt.response, body=response_body, now=receipt.response.timestamp, max_skew=0,
        expected_role="seller", expected_method="POST", expected_operation=operation,
        expected_resource=negotiation_id, expected_request_id=receipt.request.request_id,
        expected_principals=TrustedIdentitySet(identities=(seller,)),
    )
    if not response_result.verified:
        raise ValueError(f"end response signature binding failed: {response_result.code.value}")
    if not 200 <= receipt.response.status < 300:
        raise ValueError("a rejected response is not an end acknowledgement")
    return acknowledgement


def read_without_adapter(
    negotiation_id: str, mechanism: str, delivery: DeliveryView, *, commitment_ref: str | None = None,
) -> LifecycleRead:
    return LifecycleRead(
        negotiation_id=negotiation_id, commitment_ref=commitment_ref, delivery=delivery,
        authority=AuthorityView(outcome=Rejected(reason=f"{mechanism} has no lifecycle adapter")),
    )
