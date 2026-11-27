"""A double of the owning storefront's two callback routes, at the storefront
client's transport.

It answers the signed lease-end report and capacity-released callbacks as the
storefront does: a 200 signed by the storefront's publisher identity, as the
service's client verifies it. A test scripts each route's next answers — an
HTTP error status, an explicit ``unsupported``, or an acknowledgement lost
after the storefront took the request — and reads back every request it took.
The signing identity is a public deterministic development fixture, never for a
public network.

It differs from the storefront in two ways, neither of which the service reads:
it records the service's request signature headers without verifying them, and
an acknowledgement's body is ``{"status": "accepted"}`` rather than the
storefront's full delivery or fulfillment view — the service reads only an
answer's ``status``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

import httpx
import injected_time
from market_identity import ResponseEnvelope, Signer, canonical_body_hash, sign_response
from storefront_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)

LEASE_ENDED = "lease_ended"
CAPACITY_RELEASED = "capacity_released"

#: An answer: an HTTP status to fail with, ``"unsupported"``, or ``"lost"`` —
#: the storefront took the request and its acknowledgement never arrived.
ACKNOWLEDGE = 200
UNSUPPORTED = "unsupported"
LOST = "lost"

_CAPACITY_RELEASED_PATH = "/api/v1/admin/fulfillment/events/capacity-released"


@dataclass(frozen=True)
class TakenRequest:
    route: str
    resource: str
    request_id: str
    content: bytes
    role: str
    signer: str

    @property
    def body(self) -> dict:
        return json.loads(self.content)


@dataclass
class StorefrontPeerDouble:
    signer: Signer
    requests: list[TakenRequest] = field(default_factory=list)
    _scripts: dict[str, deque] = field(default_factory=dict)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def answer(self, route: str, *answers: int | str) -> None:
        """Answer the route's next requests with ``answers``, in order, then
        acknowledge."""
        self._scripts.setdefault(route, deque()).extend(answers)

    def taken(self, route: str) -> list[TakenRequest]:
        return [request for request in self.requests if request.route == route]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == _CAPACITY_RELEASED_PATH:
            route, operation = CAPACITY_RELEASED, "fulfillment_capacity_released"
            resource = json.loads(request.content)["capacity_reservation_id"]
        elif path.endswith("/lease-ended"):
            route, operation = LEASE_ENDED, "lease_ended"
            resource = path.rstrip("/").split("/")[-2]
        else:
            return httpx.Response(404, json={"detail": "not found"})
        taken = TakenRequest(
            route, resource, request.headers[REQUEST_ID_HEADER], request.content,
            request.headers[ROLE_HEADER], request.headers[IDENTITY_IDENTIFIER_HEADER],
        )
        script = self._scripts.get(route)
        answer = script.popleft() if script else ACKNOWLEDGE
        if answer == LOST:
            self.requests.append(taken)
            raise httpx.ReadError("acknowledgement lost", request=request)
        self.requests.append(taken)
        if isinstance(answer, int) and answer != ACKNOWLEDGE:
            return httpx.Response(answer, json={"detail": "refused by the storefront double"})
        body = {"status": "unsupported"} if answer == UNSUPPORTED else {"status": "accepted"}
        return self._signed(request, operation, resource, body)

    def _signed(self, request: httpx.Request, operation: str, resource: str, body: dict) -> httpx.Response:
        signed = sign_response(
            signer=self.signer,
            envelope=ResponseEnvelope(
                role="seller",
                principal=self.signer.identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=injected_time.now(),
                status=200,
                body_hash=canonical_body_hash(body),
            ),
        )
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                SIGNATURE_VERSION_HEADER: signed.protocol,
                IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
                ROLE_HEADER: signed.role,
                REQUEST_ID_HEADER: signed.request_id,
                TIMESTAMP_HEADER: str(signed.timestamp),
                SIGNATURE_HEADER: signed.proof.value,
            },
        )
