"""Buyer peer messages and delivery reads over marketplace identity v2."""

from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from urllib.parse import quote

import httpx
from market_deal_lifecycle_contracts.models import (
    CommitMessage, EndDeliveryAcknowledgement, EndDeliveryMessage, HintMessage, LifecycleRead,
    SignedEndDeliveryReceipt, SubmitResponse,
)
from market_deal_lifecycle_contracts.routes import lifecycle_route
from market_identity import (
    EMPTY_BODY, AuthenticatedResponse, EnvelopeCapture, Identity, RequestEnvelope,
    SignatureProof, Signer, TrustedIdentitySet, canonical_body_hash, canonical_json,
    capture_envelope, sign_request, verify_response,
)


class LifecycleClientError(ValueError):
    """An HTTP or authentication failure, not an authority's lifecycle outcome."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LifecycleClient:
    def __init__(
        self, base_url: str, signer: Signer, expected_publishers: TrustedIdentitySet,
        *, timeout: float = 60, transport: httpx.AsyncBaseTransport | None = None,
        capture: EnvelopeCapture | None = None, max_timestamp_skew: int = 300,
    ) -> None:
        if not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if not isinstance(expected_publishers, TrustedIdentitySet):
            raise TypeError("expected_publishers must be a TrustedIdentitySet")
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must be nonnegative")
        self._signer = signer
        self._publishers = expected_publishers
        self._capture = capture
        self._skew = max_timestamp_skew
        self._requests: dict[str, tuple[str, str, str]] = {}
        self._responses: dict[str, SignedEndDeliveryReceipt] = {}
        self._end_receipts: dict[tuple[str, str], SignedEndDeliveryReceipt] = {}
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def __aenter__(self) -> LifecycleClient:
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def commit(self, message: CommitMessage, *, request_id: str | None = None) -> SubmitResponse:
        return SubmitResponse.model_validate(await self._request(
            "lifecycle_peer", message.negotiation_id, message.model_dump(mode="json"), request_id,
        ))

    async def hint(self, message: HintMessage, *, request_id: str | None = None) -> SubmitResponse:
        return SubmitResponse.model_validate(await self._request(
            "lifecycle_peer", message.negotiation_id, message.model_dump(mode="json"), request_id,
        ))

    async def end_delivery(
        self, negotiation_id: str, *, operation_key: str | None = None, request_id: str | None = None,
    ) -> EndDeliveryAcknowledgement:
        """Surrender delivery at the seller receipt, never at a supplied instant."""
        key = operation_key or hashlib.sha256(canonical_json(["end_delivery", negotiation_id])).hexdigest()
        message = EndDeliveryMessage(negotiation_id=negotiation_id, operation_key=key)
        request_id = uuid.uuid4().hex if request_id is None else request_id
        acknowledgement = EndDeliveryAcknowledgement.model_validate(await self._request(
            "lifecycle_peer", negotiation_id, message.model_dump(mode="json"), request_id,
        ))
        if acknowledgement.negotiation_id != negotiation_id or acknowledgement.operation_key != key:
            raise LifecycleClientError("end acknowledgement names another request")
        receipt = self._responses.pop(request_id)
        prior = self._end_receipts.get((negotiation_id, key))
        if prior is not None:
            previous = EndDeliveryAcknowledgement.model_validate_json(prior.response_body)
            claim_withdrawn = (
                acknowledgement.signed_delivery_end_claim is None
                and acknowledgement.selected_end != previous.selected_end
                and acknowledgement.selected_end.ended_at <= previous.selected_end.ended_at
            )
            if (previous.receipt_at != acknowledgement.receipt_at
                    or (previous.signed_delivery_end_claim != acknowledgement.signed_delivery_end_claim
                        and not claim_withdrawn)):
                raise LifecycleClientError("end retry changes the durable receipt or claim")
        self._end_receipts[negotiation_id, key] = receipt
        return acknowledgement

    def end_receipt(self, negotiation_id: str, operation_key: str) -> SignedEndDeliveryReceipt:
        """Exact envelopes for offline Agreement-bound verification and evidence."""
        return self._end_receipts[negotiation_id, operation_key]

    async def read(self, negotiation_id: str, *, request_id: str | None = None) -> LifecycleRead:
        result = LifecycleRead.model_validate(await self._request(
            "lifecycle_buyer_read", negotiation_id, EMPTY_BODY, request_id,
        ))
        if result.negotiation_id != negotiation_id:
            raise LifecycleClientError("lifecycle read names another negotiation")
        return result

    async def _request(self, operation: str, negotiation_id: str, body: object, request_id: str | None) -> dict:
        if not negotiation_id or any(c in negotiation_id for c in "/?#%") or negotiation_id in {".", ".."}:
            raise ValueError("negotiation_id must be one unescaped path segment")
        route = lifecycle_route(operation)
        path = route["path"].replace(r"(?P<negotiation_id>[^/]+)", quote(negotiation_id, safe=""))
        if re.fullmatch(route["path"], path) is None:
            raise ValueError("negotiation_id does not match the lifecycle route")
        method = route["method"]
        request_id = uuid.uuid4().hex if request_id is None else request_id
        digest = canonical_body_hash(body)
        context = (method, negotiation_id, digest)
        if request_id in self._requests and self._requests[request_id] != context:
            raise ValueError("request_id was reused with changed request content")
        self._requests[request_id] = context
        request = sign_request(signer=self._signer, envelope=RequestEnvelope(
            role="buyer", principal=self._signer.identity, method=method, operation=operation,
            resource=negotiation_id, request_id=request_id, timestamp=int(time.time()), body_hash=digest,
        ))
        headers = {
            "Accept": "application/json", "X-Market-Signature-Version": request.protocol,
            "X-Market-Identity-Scheme": request.principal.scheme.value,
            "X-Market-Identity-Identifier": request.principal.identifier,
            "X-Market-Role": request.role, "X-Market-Request-ID": request.request_id,
            "X-Market-Timestamp": str(request.timestamp), "X-Market-Signature": request.proof.value,
        }
        content = None if body is EMPTY_BODY else canonical_json(body)
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = await self._client.request(method, path, content=content, headers=headers)
        except httpx.TransportError as exc:
            raise LifecycleClientError("lifecycle transport failed; outcome is unknown") from exc
        try:
            payload = response.json()
            principal = Identity.model_validate({
                "scheme": response.headers["X-Market-Identity-Scheme"],
                "identifier": response.headers["X-Market-Identity-Identifier"],
            })
            authenticated = AuthenticatedResponse(
                protocol=response.headers["X-Market-Signature-Version"],
                role=response.headers["X-Market-Role"], principal=principal,
                method=method, operation=operation, resource=negotiation_id,
                request_id=response.headers["X-Market-Request-ID"],
                timestamp=int(response.headers["X-Market-Timestamp"]), status=response.status_code,
                body_hash=canonical_body_hash(payload),
                proof=SignatureProof(scheme=principal.scheme, value=response.headers["X-Market-Signature"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise LifecycleClientError("unreadable lifecycle response authentication", status_code=response.status_code) from exc
        verified = verify_response(
            authenticated, body=payload, now=int(time.time()), max_skew=self._skew,
            expected_role="seller", expected_principals=self._publishers, expected_method=method,
            expected_operation=operation, expected_resource=negotiation_id, expected_request_id=request_id,
            capture=self._capture, raw_body=response.content, headers=response.headers,
        )
        if not verified.verified:
            raise LifecycleClientError(f"lifecycle response authentication failed: {verified.code.value}", status_code=response.status_code)
        capture_envelope(self._capture, envelope=request, raw_body=content or b"", headers=headers,
                         verified_at=int(time.time()), expected_principals=TrustedIdentitySet(identities=(request.principal,)))
        if operation == "lifecycle_peer" and isinstance(body, dict) and body.get("kind") == "end_delivery" and not response.is_error:
            self._responses[request_id] = SignedEndDeliveryReceipt(
                request=request, request_body=base64.b64encode(content or b""),
                response=authenticated, response_body=base64.b64encode(response.content),
            )
        if response.is_error:
            raise LifecycleClientError(f"lifecycle HTTP {response.status_code}: {payload}", status_code=response.status_code)
        if not isinstance(payload, dict):
            raise LifecycleClientError("lifecycle response must be a JSON object", status_code=response.status_code)
        return payload
