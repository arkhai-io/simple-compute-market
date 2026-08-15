"""Signed in-memory site authority for ``market_site_client`` unit tests."""

from __future__ import annotations

import itertools
import json
import time
from copy import deepcopy
from typing import Any

import httpx
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Identity,
    ReplayReservation,
    ResponseEnvelope,
    SignatureProof,
    Signer,
    VerificationCode,
    canonical_body_hash,
    sign_response,
    TrustedIdentitySet,
    verify_request,
)

from market_site_client.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    resolve_capacity_route,
)


class FakeSite:
    """Dict-backed capacity ledger with the server's v2 identity boundary."""

    def __init__(
        self,
        *,
        caller: Signer,
        authority: Signer,
        deliverable_modes: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.caller = caller
        self.authority = authority
        self.deliverable_modes = frozenset(deliverable_modes or ())
        self.resources: dict[str, dict[str, Any]] = {}
        self.reservations: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.seen_requests: list[dict[str, Any]] = []
        self.dispatch_count = 0
        self._versions = itertools.count(1)
        self._ids = itertools.count(1)
        self._replays: dict[tuple[str, str, str], ReplayReservation] = {}
        self._outcomes: dict[
            tuple[str, str, str], tuple[int, Any]
        ] = {}

        # One-shot or persistent protocol-failure controls used by focused tests.
        self.mutate_next_request_body = False
        self.mutate_next_response_body = False
        self.response_role = "service"
        self.response_signer: Signer | None = None
        self.response_request_id: str | None = None
        self.response_operation: str | None = None
        self.response_resource: str | None = None
        self.response_protocol: str | None = None
        self.omit_response_authentication = False

    def add_resource(
        self,
        resource_id: str,
        total_units: int,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.resources[resource_id] = {
            "resource_id": resource_id,
            "total_units": int(total_units),
            "attributes": dict(attributes or {}),
            "enabled": True,
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _emit(self, kind: str, resource_id: str | None) -> None:
        self.events.append(
            {
                "version": next(self._versions),
                "kind": kind,
                "resource_id": resource_id,
                "occurred_at": "2026-01-01T00:00:00Z",
            }
        )

    def _available(self, resource_id: str) -> int:
        held = sum(
            reservation["units"]
            for reservation in self.reservations.values()
            if reservation["resource_id"] == resource_id
            and reservation["state"]
            in ("reserved", "provisioning", "leased", "releasing")
        )
        return self.resources[resource_id]["total_units"] - held

    @staticmethod
    def _wire_body(request: httpx.Request) -> Any:
        if request.method == "GET":
            if request.url.path == "/api/v1/capacity/events":
                return {
                    "after": int(request.url.params.get("after", 0)),
                    "limit": int(request.url.params.get("limit", 500)),
                }
            if request.url.path == "/api/v1/capacity/reservations":
                return {
                    key: request.url.params[key]
                    for key in ("state", "escrow_uid")
                    if key in request.url.params
                }
            return EMPTY_BODY
        return json.loads(request.content) if request.content else EMPTY_BODY

    @staticmethod
    def _request_envelope(request: httpx.Request, body: Any) -> AuthenticatedRequest:
        principal = Identity(
            scheme=request.headers[IDENTITY_SCHEME_HEADER],
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        )
        operation, resource = resolve_capacity_route(
            request.method, request.url.path, body
        )
        return AuthenticatedRequest(
            protocol=request.headers[SIGNATURE_VERSION_HEADER],
            role=request.headers[ROLE_HEADER],
            principal=principal,
            method=request.method,
            operation=operation,
            resource=resource,
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=principal.scheme,
                value=request.headers[SIGNATURE_HEADER],
            ),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        wire_body = self._wire_body(request)
        operation, resource = resolve_capacity_route(
            request.method, request.url.path, wire_body
        )
        verification_body = wire_body
        if self.mutate_next_request_body:
            self.mutate_next_request_body = False
            verification_body = (
                {**wire_body, "transit_mutation": True}
                if isinstance(wire_body, dict)
                else {"transit_mutation": True}
            )

        try:
            authenticated = self._request_envelope(request, wire_body)
        except (KeyError, TypeError, ValueError):
            return httpx.Response(400, json={"detail": "malformed authentication"})

        replay_key = (
            authenticated.principal.scheme.value,
            authenticated.principal.identifier,
            authenticated.request_id,
        )
        result = verify_request(
            authenticated,
            body=verification_body,
            now=int(time.time()),
            max_skew=300,
            expected_role="seller",
            expected_principals=TrustedIdentitySet(
                identities=(self.caller.identity,)
            ),
            expected_method=request.method,
            expected_operation=operation,
            expected_resource=resource,
            existing_replay=self._replays.get(replay_key),
        )
        self.seen_requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "operation": operation,
                "resource": resource,
                "body": deepcopy(wire_body),
                "request_id": authenticated.request_id,
                "timestamp": authenticated.timestamp,
                "signature": authenticated.proof.value,
                "verification": result.code,
            }
        )

        if result.code == VerificationCode.EXACT_RETRY:
            status_code, response_body = self._outcomes[replay_key]
            return self._response(
                request,
                status_code=status_code,
                body=deepcopy(response_body),
                operation=operation,
                resource=resource,
                request_id=authenticated.request_id,
            )
        if not result.verified:
            status_code = (
                409 if result.code == VerificationCode.CHANGED_REUSE else 403
            )
            return self._response(
                request,
                status_code=status_code,
                body={"detail": result.code.value},
                operation=operation,
                resource=resource,
                request_id=authenticated.request_id,
            )

        assert result.reservation is not None
        self._replays[replay_key] = result.reservation
        self.dispatch_count += 1
        status_code, response_body = self._dispatch(request, wire_body)
        self._outcomes[replay_key] = (status_code, deepcopy(response_body))
        return self._response(
            request,
            status_code=status_code,
            body=response_body,
            operation=operation,
            resource=resource,
            request_id=authenticated.request_id,
        )

    def _response(
        self,
        request: httpx.Request,
        *,
        status_code: int,
        body: Any,
        operation: str,
        resource: str,
        request_id: str,
    ) -> httpx.Response:
        if self.omit_response_authentication:
            return httpx.Response(status_code, json=body)

        response_signer = self.response_signer or self.authority
        signed = sign_response(
            signer=response_signer,
            envelope=ResponseEnvelope(
                role=self.response_role,
                principal=response_signer.identity,
                method=request.method,
                operation=self.response_operation or operation,
                resource=(
                    self.response_resource
                    if self.response_resource is not None
                    else resource
                ),
                request_id=self.response_request_id or request_id,
                timestamp=int(time.time()),
                status=status_code,
                body_hash=canonical_body_hash(body),
            ),
        )
        headers = {
            SIGNATURE_VERSION_HEADER: self.response_protocol or signed.protocol,
            IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
            ROLE_HEADER: signed.role,
            REQUEST_ID_HEADER: signed.request_id,
            TIMESTAMP_HEADER: str(signed.timestamp),
            SIGNATURE_HEADER: signed.proof.value,
        }
        emitted_body = body
        if self.mutate_next_response_body:
            self.mutate_next_response_body = False
            emitted_body = (
                {**body, "transit_mutation": True}
                if isinstance(body, dict)
                else {"transit_mutation": True}
            )
        return httpx.Response(status_code, json=emitted_body, headers=headers)

    def _dispatch(self, request: httpx.Request, body: Any) -> tuple[int, Any]:
        path = request.url.path

        if request.method == "PUT" and path.startswith(
            "/api/v1/capacity/resources/"
        ):
            resource_id = path.rsplit("/", 1)[1]
            self.resources[resource_id] = {
                "resource_id": resource_id,
                "total_units": body["total_units"],
                "resource_type": body.get("resource_type", "compute.gpu"),
                "pool_id": body.get("pool_id"),
                "resource_subtype": body.get("resource_subtype"),
                "attributes": body.get("attributes") or {},
                "capacity": body.get("capacity"),
                "enabled": body.get("enabled", True),
            }
            self._emit("released", resource_id)
            return 200, self.resources[resource_id]

        if request.method == "GET" and path == "/api/v1/capacity/resources":
            rows = list(self.resources.values())
            return 200, {"resources": rows, "total": len(rows)}

        if path == "/api/v1/capacity/site-resource-pools/version":
            return 200, {"revision": 1, "digest": "pools"}
        if path == "/api/v1/capacity/site-resource-pools":
            return 200, {
                "revision": 1,
                "digest": "pools",
                "resource_pools": [],
            }
        if path == "/api/v1/capacity/site-capacity-buckets/version":
            return 200, {"revision": 1, "digest": "buckets"}
        if path == "/api/v1/capacity/site-capacity-buckets":
            return 200, {
                "revision": 1,
                "digest": "buckets",
                "capacity_buckets": [],
            }

        if path == "/api/v1/capacity/snapshot":
            return 200, {
                "resources": [
                    {
                        "resource_id": resource_id,
                        "resource_type": "compute.gpu",
                        "unit": "count",
                        "value": row["total_units"],
                        "available_units": self._available(resource_id),
                        "available": {
                            "gpu_count": self._available(resource_id)
                        },
                        "state": (
                            "available"
                            if self._available(resource_id) > 0
                            else "leased"
                        ),
                        "attributes": row["attributes"],
                        "enabled": True,
                    }
                    for resource_id, row in self.resources.items()
                    if row["enabled"]
                ]
            }

        if path == "/api/v1/capacity/probe":
            return 200, {"match": self._match(body["claim"])}

        if request.method == "POST" and path == "/api/v1/capacity/reservations":
            match = self._match(body["claim"])
            if match is None:
                return 200, {"reservation": None}
            capacity_reservation_id = f"alloc-{next(self._ids)}"
            self.reservations[capacity_reservation_id] = {
                "capacity_reservation_id": capacity_reservation_id,
                "resource_id": match["resource_id"],
                "units": match["allocated_gpu_count"],
                "state": "reserved",
                "deal_ref": body.get("deal_ref") or {},
            }
            self._emit("reserved", match["resource_id"])
            public_match = {
                key: value
                for key, value in match.items()
                if key not in {"resource_id", "vm_host"}
            }
            return 200, {
                "reservation": {
                    **public_match,
                    "capacity_reservation_id": capacity_reservation_id,
                    "hold_expires_at": None,
                }
            }

        if path.endswith("/commit"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return 404, {"detail": "not found"}
            reservation["state"] = "leased"
            reservation["lease_start_utc"] = body.get("lease_start_utc")
            reservation["lease_end_utc"] = body.get("lease_end_utc")
            self._emit("committed", reservation["resource_id"])
            return 200, {"reservation": reservation}

        if path == "/api/v1/capacity/releases":
            reservation = None
            if body.get("capacity_reservation_id"):
                reservation = self.reservations.get(
                    body["capacity_reservation_id"]
                )
            else:
                escrow = (body.get("deal_ref") or {}).get("escrow_uid")
                reservation = next(
                    (
                        item
                        for item in self.reservations.values()
                        if item["deal_ref"].get("escrow_uid") == escrow
                        and item["state"] != "released"
                    ),
                    None,
                )
            if reservation is None or reservation["state"] == "released":
                return 200, {"reservation": None}
            reservation["state"] = "released"
            reservation["failure_reason"] = body.get("failure_reason")
            reservation["failure_message"] = body.get("failure_message")
            self._emit("released", reservation["resource_id"])
            return 200, {
                "reservation": {
                    **reservation,
                    "allocated_gpu_count": reservation["units"],
                }
            }

        if path.endswith("/truncate-lease"):
            capacity_reservation_id = path.split("/")[-2]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return 200, {"reservation": None}
            reservation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("lease_truncated", reservation["resource_id"])
            return 200, {"reservation": reservation}

        if request.method == "GET" and path == "/api/v1/capacity/reservations":
            escrow = request.url.params.get("escrow_uid")
            state = request.url.params.get("state")
            rows = [
                reservation
                for reservation in self.reservations.values()
                if (
                    escrow is None
                    or reservation["deal_ref"].get("escrow_uid") == escrow
                )
                and (state is None or reservation["state"] == state)
            ]
            return 200, {"reservations": rows, "total": len(rows)}

        if request.method == "GET" and path.startswith(
            "/api/v1/capacity/reservations/"
        ):
            capacity_reservation_id = path.rsplit("/", 1)[1]
            reservation = self.reservations.get(capacity_reservation_id)
            if reservation is None:
                return 404, {"detail": "not found"}
            return 200, {"reservation": reservation}

        if path == "/api/v1/capacity/events":
            after = int(request.url.params.get("after", 0))
            limit = int(request.url.params.get("limit", 500))
            page = [event for event in self.events if event["version"] > after][
                :limit
            ]
            latest = self.events[-1]["version"] if self.events else 0
            return 200, {"events": page, "latest_version": latest}

        return 404, {"detail": f"unhandled {path}"}

    def _match(self, claim: dict[str, Any]) -> dict[str, Any] | None:
        claim = claim or {}
        executor_kind = claim.get("executor_kind")
        if (
            not isinstance(executor_kind, str)
            or executor_kind not in self.deliverable_modes
        ):
            return None
        dimensions = claim.get("dimensions") or {}
        requested = int(dimensions.get("gpu_count") or claim.get("gpu_count") or 1)
        required_resource_type = claim.get("resource_type")
        if (
            required_resource_type is not None
            and required_resource_type != "compute.gpu"
        ):
            return None
        for resource_id, row in self.resources.items():
            if not row["enabled"]:
                continue
            attributes = row["attributes"]
            top_level = {"resource_id": resource_id, "pool_id": resource_id}
            mismatched = any(
                attributes.get(key, top_level.get(key)) != value
                for key, value in claim.items()
                if key not in (
                    "gpu_count",
                    "dimensions",
                    "resource_type",
                    "executor_kind",
                )
            )
            if mismatched or self._available(resource_id) < requested:
                continue
            return {
                "resource_id": resource_id,
                "pool_id": None,
                "member_id": None,
                "vm_host": attributes.get("vm_host"),
                "allocated_gpu_count": requested,
                "available_gpu_count": self._available(resource_id),
                "attributes": attributes,
            }
        return None
