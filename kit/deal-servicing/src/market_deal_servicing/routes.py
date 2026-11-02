"""Mountable signed lifecycle routes with immutable role and Agreement bindings."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response
from market_deal_lifecycle.acknowledgements import verify_end_acknowledgement
from market_deal_lifecycle_contracts.models import (
    EndDeliveryMessage, SignedEndDeliveryReceipt,
    CommitMessage, EvidenceItem, HintMessage, LifecycleCommand, ListDealsRequest,
    SubmitResponse, WireModel,
)
from market_deal_lifecycle_contracts.routes import lifecycle_route
from market_identity import (
    EMPTY_BODY, AuthenticatedRequest, Identity, ResponseEnvelope, SignatureProof,
    Signer, TrustedIdentitySet, canonical_body_hash, canonical_json, sign_response, verify_request,
)

from .end import EndService
from .ingress import DeliveryIngress
from .evidence import EvidenceSession, in_transaction
from .journal import EndSession
from .seller import SellerServicing

Peer: TypeAlias = CommitMessage | HintMessage
PeerHandler = Callable[[Peer], Awaitable[SubmitResponse]]


@dataclass(frozen=True)
class LifecycleRouteBinding:
    """Project the accepted Agreement even before a commitment is registered."""

    buyer: Identity
    seller: Identity
    settlement: bool


@dataclass(frozen=True)
class LifecycleRouteServices:
    seller: SellerServicing
    binding: Callable[[str], LifecycleRouteBinding]
    signer: Signer
    administrators: TrustedIdentitySet
    peer: PeerHandler
    ingress: DeliveryIngress | None = None
    end: EndService | None = None


def create_lifecycle_router(
    services: Callable[[Request], LifecycleRouteServices],
) -> APIRouter:
    """Resolve lifespan-owned services, never a domain or global container.

    The injected commit handler shares the domain's settlement implementation;
    it verifies the authority before effects. Hint handlers read the authority.
    Neither callback receives buyer authority commands. Mutating handlers must
    recover unknown results under the peer message's stable operation key.
    """
    router = APIRouter()

    async def dispatch(request: Request, operation: str, negotiation_id: str = "") -> Response:
        svc = await asyncio.to_thread(services, request)
        route = lifecycle_route(operation)
        resource = negotiation_id
        if operation == "lifecycle_list" and request.query_params:
            resource = "?" + urlencode(sorted(request.query_params.multi_items()))
        body: Any = EMPTY_BODY
        raw = await request.body()
        status = 200
        envelope = None
        try:
            if raw:
                body = json.loads(raw)
            elif request.method == "POST":
                raise ValueError("a lifecycle write requires a JSON body")
            if request.method == "POST" and not isinstance(body, dict):
                raise ValueError("a lifecycle write requires a JSON object")
            if request.method == "GET" and raw:
                raise ValueError("a lifecycle read has no body")
            binding = await asyncio.to_thread(svc.binding, negotiation_id) if negotiation_id else None
            if binding is not None and svc.signer.identity != binding.seller:
                raise RuntimeError("lifecycle signer is not the Agreement seller")
            role = route["roles"][0]
            expected = (TrustedIdentitySet(identities=(binding.buyer,))
                        if role == "buyer" and binding is not None else svc.administrators)
            envelope = _authenticate(request, operation, resource, body, expected, svc.seller.clock())
            # A transport retry may refresh timestamp/proof, never signed content.
            assert envelope is not None
            verified = verify_request(
                envelope, body=body, now=svc.seller.clock(), max_skew=300,
                expected_role=role, expected_method=request.method, expected_operation=operation,
                expected_resource=resource, expected_principals=expected,
            )
            assert verified.reservation is not None
            request_hash = verified.reservation.request_hash
            def retain_request(conn):
                if not EndSession(conn).check_and_record(
                    "_lifecycle_transport",
                    hashlib.sha256(canonical_json([envelope.principal.model_dump(mode="json"), envelope.request_id])).hexdigest(),
                    request_hash,
                ):
                    raise RouteRefusal(409, "request ID changes signed content")
                if negotiation_id and raw:
                    EvidenceSession(conn).put(negotiation_id, EvidenceItem(
                        evidence_id="lifecycle-request:" + hashlib.sha256(canonical_json(envelope)).hexdigest(),
                        kind="lifecycle_peer" if role == "buyer" else "lifecycle_submit",
                        classification="buyer_observation" if role == "buyer" else "seller_assertion",
                        recorded_at=svc.seller.clock(), body=base64.b64encode(raw),
                        headers=dict(request.headers),
                        context={"authenticated_request": envelope.model_dump(mode="json")},
                    ))
            await in_transaction(svc.seller.path, retain_request)
            result: WireModel
            if operation == "lifecycle_list":
                # Bind the complete page selector into the signed resource.
                query = dict(request.query_params)
                if len(query) != len(request.query_params.multi_items()):
                    raise ValueError("duplicate lifecycle page selector")
                page = ListDealsRequest.model_validate({
                    **query, **({"limit": int(query["limit"])} if "limit" in query else {}),
                })
                result = await svc.seller.list(page)
            elif operation == "lifecycle_submit":
                value = dict(body)
                reason = value.pop("reason", None)
                command = LifecycleCommand.model_validate(value)
                if command.negotiation_id != negotiation_id:
                    raise ValueError("command names another negotiation")
                result = SubmitResponse(outcome=await svc.seller.submit(
                    command, actor=envelope.principal, reason=reason,
                ))
            elif operation == "lifecycle_buyer_read":
                result = await asyncio.to_thread(svc.seller.delivery_read, negotiation_id)
            elif operation == "lifecycle_seller_read":
                result = await svc.seller.read(negotiation_id)
            elif body.get("kind") == "end_delivery":
                message_end = EndDeliveryMessage.model_validate(body)
                if message_end.negotiation_id != negotiation_id:
                    raise ValueError("peer message names another negotiation")
                if binding is None or not binding.settlement:
                    raise RouteRefusal(409, "end_delivery requires a settlement-stage Agreement")
                if svc.ingress is None or svc.end is None:
                    raise RouteRefusal(503, "delivery servicing is unavailable")
                if svc.ingress.path.resolve() != svc.seller.path.resolve() or svc.end.path.resolve() != svc.seller.path.resolve():
                    raise RuntimeError("lifecycle delivery services must share persistence")
                acknowledgement = await asyncio.to_thread(
                    svc.ingress.end_delivery, envelope, body=raw, headers=dict(request.headers),
                )
                try:
                    await svc.end.drive_physical(negotiation_id)
                except Exception:
                    # Receipt is durable even if physical I/O fails. The pending
                    # effect keeps its key for the controller to retry.
                    logging.getLogger(__name__).exception("Delivery end awaits physical recovery")
                delivery = await in_transaction(svc.seller.path, lambda conn: EndSession(conn).view(negotiation_id))
                result = acknowledgement.model_copy(update={
                    "delivery": delivery, "selected_end": delivery.recorded_end,
                })
            else:
                message: Peer = (CommitMessage.model_validate(body) if body.get("kind") == "commit"
                                 else HintMessage.model_validate(body))
                if message.negotiation_id != negotiation_id:
                    raise ValueError("peer message names another negotiation")
                def retain_peer(conn):
                    if not EndSession(conn).check_and_record(
                        negotiation_id, "lifecycle-peer:" + message.kind + ":" + message.operation_key,
                        hashlib.sha256(canonical_json(message)).hexdigest(),
                    ):
                        raise RouteRefusal(409, "peer operation key changes content")
                await in_transaction(svc.seller.path, retain_peer)
                result = await svc.peer(message)
            payload = result.model_dump(mode="json")
        except RouteRefusal as exc:
            status, payload = exc.status, {"detail": str(exc)}
        except KeyError:
            status, payload = 404, {"detail": "accepted negotiation not found"}
        except (ValueError, TypeError) as exc:
            status, payload = 422, {"detail": str(exc)}
        signed = sign_response(signer=svc.signer, envelope=ResponseEnvelope(
            role="seller", principal=svc.signer.identity, method=request.method, operation=operation,
            resource=resource, request_id=request.headers.get("X-Market-Request-ID", "unauthenticated"),
            timestamp=svc.seller.clock(), status=status, body_hash=canonical_body_hash(payload),
        ))
        rendered = canonical_json(payload)
        headers = _headers(signed)
        if status == 200 and isinstance(body, dict) and body.get("kind") == "end_delivery":
            assert envelope is not None and binding is not None
            verify_end_acknowledgement(SignedEndDeliveryReceipt(
                request=envelope, request_body=base64.b64encode(raw), response=signed,
                response_body=base64.b64encode(rendered),
            ), negotiation_id=negotiation_id, buyer=binding.buyer, seller=binding.seller)
        if envelope is not None and negotiation_id:
            await in_transaction(svc.seller.path, lambda conn: EvidenceSession(conn).put(negotiation_id, EvidenceItem(
                    evidence_id="lifecycle-response:" + hashlib.sha256(canonical_json(signed)).hexdigest(),
                    kind="lifecycle_response", classification="seller_assertion",
                    recorded_at=signed.timestamp, body=base64.b64encode(rendered), headers=headers,
                    context={"authenticated_response": signed.model_dump(mode="json")},
            )))
        return Response(rendered, status_code=status, headers=headers, media_type="application/json")

    @router.get("/api/v1/admin/lifecycle")
    async def list_deals(request: Request):
        return await dispatch(request, "lifecycle_list")

    @router.post("/api/v1/admin/lifecycle/{negotiation_id}")
    async def submit(request: Request, negotiation_id: str):
        return await dispatch(request, "lifecycle_submit", negotiation_id)

    @router.get("/api/v1/admin/lifecycle/{negotiation_id}")
    async def seller_read(request: Request, negotiation_id: str):
        return await dispatch(request, "lifecycle_seller_read", negotiation_id)

    @router.post("/api/v1/negotiations/{negotiation_id}/lifecycle")
    async def peer(request: Request, negotiation_id: str):
        return await dispatch(request, "lifecycle_peer", negotiation_id)

    @router.get("/api/v1/negotiations/{negotiation_id}/lifecycle")
    async def buyer_read(request: Request, negotiation_id: str):
        return await dispatch(request, "lifecycle_buyer_read", negotiation_id)

    return router


class RouteRefusal(ValueError):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status


def _authenticate(request, operation, resource, body, expected, now) -> AuthenticatedRequest:
    try:
        headers = request.headers
        principal = Identity(scheme=headers["X-Market-Identity-Scheme"],
                             identifier=headers["X-Market-Identity-Identifier"])
        envelope = AuthenticatedRequest(
            protocol=headers["X-Market-Signature-Version"], principal=principal,
            role=headers["X-Market-Role"], method=request.method, operation=operation, resource=resource,
            request_id=headers["X-Market-Request-ID"], timestamp=int(headers["X-Market-Timestamp"]),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(scheme=principal.scheme, value=headers["X-Market-Signature"]),
        )
    except (KeyError, ValueError) as exc:
        raise RouteRefusal(401, "malformed marketplace v2 authentication") from exc
    verified = verify_request(
        envelope, body=body, now=now, max_skew=300, expected_role=lifecycle_route(operation)["roles"][0],
        expected_method=request.method, expected_operation=operation, expected_resource=resource,
        expected_principals=expected,
    )
    if not verified.verified:
        raise RouteRefusal(403, "lifecycle authentication failed: " + verified.code.value)
    return envelope


def _headers(envelope) -> dict[str, str]:
    return {
        "X-Market-Signature-Version": envelope.protocol,
        "X-Market-Identity-Scheme": envelope.principal.scheme.value,
        "X-Market-Identity-Identifier": envelope.principal.identifier,
        "X-Market-Role": envelope.role, "X-Market-Request-ID": envelope.request_id,
        "X-Market-Timestamp": str(envelope.timestamp), "X-Market-Signature": envelope.proof.value,
    }
