"""Typed, authenticated async clients for a site authority's capacity API.

Every request uses the market-identity v2 envelope.  The injected signer is the
configured seller/storefront identity; responses are accepted only from the
bounded trusted set of site-authority principals acting with the ``service`` role.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

import httpx
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    Signer,
    canonical_body_hash,
    sign_request,
    TrustedIdentitySet,
    verify_response,
)

from market_site_client.models import ResourceRegistration


SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


class SiteCapacityClientError(Exception):
    """HTTP, transport, or protocol error from a site capacity API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SiteCapacityAdminClientError(SiteCapacityClientError):
    """Error from the operator resource-registration surface."""


class SiteCapacityAuthenticationError(SiteCapacityAdminClientError):
    """A response did not carry a valid acknowledgement from the authority."""


@dataclass(frozen=True, slots=True)
class CapacityRouteContract:
    """One authenticated capacity route and its semantic v2 context."""

    method: str
    pattern: re.Pattern[str]
    operation: str
    path_resource: str | None = None
    body_resource: str | None = None
    optional_body_resource: bool = False

    def match(self, method: str, path: str, body: Any) -> str | None:
        if method.upper() != self.method:
            return None
        matched = self.pattern.fullmatch(path)
        if matched is None:
            return None
        if self.path_resource is not None:
            return matched.group(self.path_resource)
        if self.body_resource is not None:
            if not isinstance(body, dict):
                raise ValueError(
                    f"{self.operation} requires a JSON object request body"
                )
            resource = body.get(self.body_resource)
            if resource is None and self.optional_body_resource:
                return ""
            if not isinstance(resource, str) or not resource:
                raise ValueError(
                    f"{self.operation} requires body.{self.body_resource}"
                )
            return resource
        return ""


CAPACITY_ROUTE_CONTRACTS = (
    CapacityRouteContract(
        "PUT",
        re.compile(r"/api/v1/capacity/resources/(?P<resource_id>[^/]+)"),
        "capacity_resource_put",
        path_resource="resource_id",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/resources"),
        "capacity_resources_list",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/site-resource-pools/version"),
        "capacity_resource_pools_version",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/site-resource-pools"),
        "capacity_resource_pools_get",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/site-capacity-buckets/version"),
        "capacity_buckets_version",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/site-capacity-buckets"),
        "capacity_buckets_get",
    ),
    CapacityRouteContract(
        "GET", re.compile(r"/api/v1/capacity/snapshot"), "capacity_snapshot"
    ),
    CapacityRouteContract(
        "POST", re.compile(r"/api/v1/capacity/probe"), "capacity_probe"
    ),
    CapacityRouteContract(
        "POST", re.compile(r"/api/v1/capacity/reservations"), "capacity_reserve"
    ),
    CapacityRouteContract(
        "POST",
        re.compile(
            r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/commit"
        ),
        "capacity_commit",
        path_resource="reservation_id",
    ),
    CapacityRouteContract(
        "POST",
        re.compile(r"/api/v1/capacity/releases"),
        "capacity_release",
        body_resource="capacity_reservation_id",
        optional_body_resource=True,
    ),
    CapacityRouteContract(
        "POST",
        re.compile(
            r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)/truncate-lease"
        ),
        "capacity_truncate_lease",
        path_resource="reservation_id",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/reservations"),
        "capacity_reservations_list",
    ),
    CapacityRouteContract(
        "GET",
        re.compile(r"/api/v1/capacity/reservations/(?P<reservation_id>[^/]+)"),
        "capacity_reservation_get",
        path_resource="reservation_id",
    ),
    CapacityRouteContract(
        "GET", re.compile(r"/api/v1/capacity/events"), "capacity_events"
    ),
)


def resolve_capacity_route(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
) -> tuple[str, str]:
    """Return the server-owned semantic operation and resource for a route."""

    for contract in CAPACITY_ROUTE_CONTRACTS:
        resource = contract.match(method, path, body)
        if resource is not None:
            return contract.operation, resource
    raise ValueError(f"no authenticated capacity contract for {method} {path}")


class _AuthenticatedSiteClient:
    _error_type: type[SiteCapacityClientError] = SiteCapacityClientError

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None,
        max_timestamp_skew: int,
    ) -> None:
        if not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if not isinstance(expected_authorities, TrustedIdentitySet):
            raise TypeError(
                "expected_authorities must be a market_identity.TrustedIdentitySet"
            )
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must not be negative")
        self._base_url = base_url.rstrip("/")
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._timeout = timeout
        self._transport = transport
        self._max_timestamp_skew = max_timestamp_skew
        self._request_contexts: dict[
            str, tuple[str, str, str, str]
        ] = {}
        self._topology_error_handler: Callable[[], Awaitable[None]] | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    def set_topology_error_handler(
        self, handler: Callable[[], Awaitable[None]] | None
    ) -> None:
        """Install a bounded drift check after verified topology-sensitive errors."""

        self._topology_error_handler = handler

    def _request_headers(
        self,
        *,
        method: str,
        operation: str,
        resource: str,
        body: Any,
        request_id: str,
    ) -> dict[str, str]:
        context = (
            method.upper(),
            operation,
            resource,
            canonical_body_hash(body),
        )
        existing = self._request_contexts.get(request_id)
        if existing is not None and existing != context:
            raise ValueError("request_id was reused with changed request content")

        authenticated = sign_request(
            signer=self._signer,
            envelope=RequestEnvelope(
                role="seller",
                principal=self._signer.identity,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                timestamp=int(time.time()),
                body_hash=context[3],
            ),
        )
        headers = {
            SIGNATURE_VERSION_HEADER: authenticated.protocol,
            IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
            ROLE_HEADER: authenticated.role,
            REQUEST_ID_HEADER: authenticated.request_id,
            TIMESTAMP_HEADER: str(authenticated.timestamp),
            SIGNATURE_HEADER: authenticated.proof.value,
        }
        self._request_contexts[request_id] = context
        return dict(headers)

    def _verify_response(
        self,
        response: httpx.Response,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
        body: Any,
    ) -> None:
        try:
            principal = Identity(
                scheme=response.headers[IDENTITY_SCHEME_HEADER],
                identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
            )
            authenticated = AuthenticatedResponse(
                protocol=response.headers[SIGNATURE_VERSION_HEADER],
                role=response.headers[ROLE_HEADER],
                principal=principal,
                method=method,
                operation=operation,
                resource=resource,
                request_id=response.headers[REQUEST_ID_HEADER],
                timestamp=int(response.headers[TIMESTAMP_HEADER]),
                status=response.status_code,
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(
                    scheme=principal.scheme,
                    value=response.headers[SIGNATURE_HEADER],
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SiteCapacityAuthenticationError(
                "missing or malformed site-authority response authentication",
                status_code=response.status_code,
            ) from exc

        result = verify_response(
            authenticated,
            body=body,
            now=int(time.time()),
            max_skew=self._max_timestamp_skew,
            expected_role="service",
            expected_principals=self._expected_authorities,
            expected_method=method,
            expected_operation=operation,
            expected_resource=resource,
            expected_request_id=request_id,
        )
        if not result.verified:
            raise SiteCapacityAuthenticationError(
                f"site-authority response authentication failed: {result.code.value}",
                status_code=response.status_code,
            )

    @staticmethod
    def _response_body(response: httpx.Response) -> Any:
        if not response.content:
            return EMPTY_BODY
        try:
            return response.json()
        except ValueError:
            return response.text

    def _raise_response_error(self, response: httpx.Response, body: Any) -> None:
        if response.is_success:
            return
        detail = body.get("detail", response.text) if isinstance(body, dict) else body
        raise self._error_type(str(detail), status_code=response.status_code)

    async def _request(
        self,
        method: str,
        path: str,
        body: Any = EMPTY_BODY,
        *,
        query: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        payload = (
            body.model_dump(mode="json", exclude_none=True)
            if hasattr(body, "model_dump")
            else body
        )
        signing_body = query if query is not None else payload
        operation, resource = resolve_capacity_route(method, path, payload)
        resolved_request_id = request_id or uuid.uuid4().hex
        headers = self._request_headers(
            method=method,
            operation=operation,
            resource=resource,
            body=signing_body,
            request_id=resolved_request_id,
        )
        kwargs: dict[str, Any] = {}
        if payload is not EMPTY_BODY:
            kwargs["json"] = payload
        if query is not None:
            kwargs["params"] = query

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as http:
            try:
                response = await http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise self._error_type(
                    f"{method.upper()} {path} failed to reach {self._base_url!r}: {exc}"
                ) from exc

        response_body = self._response_body(response)
        self._verify_response(
            response,
            method=method,
            operation=operation,
            resource=resource,
            request_id=resolved_request_id,
            body=response_body,
        )
        if (
            method.upper() == "POST"
            and response.status_code in {404, 409, 422}
            and self._topology_error_handler is not None
        ):
            await self._topology_error_handler()
        self._raise_response_error(response, response_body)
        return response_body


class SiteCapacityAdminClient(_AuthenticatedSiteClient):
    """Authenticated seller client for site resource registration and reads."""

    _error_type = SiteCapacityAdminClientError

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_timestamp_skew: int = 300,
    ) -> None:
        super().__init__(
            base_url,
            signer,
            expected_authorities,
            timeout=timeout,
            transport=transport,
            max_timestamp_skew=max_timestamp_skew,
        )

    async def register_resource(
        self,
        resource_id: str,
        *,
        total_units: int,
        resource_type: str = "compute.gpu",
        pool_id: str | None = None,
        resource_subtype: str | None = None,
        attributes: dict[str, Any] | None = None,
        capacity: dict[str, Any] | None = None,
        enabled: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        body = ResourceRegistration(
            total_units=total_units,
            resource_type=resource_type,
            pool_id=pool_id,
            resource_subtype=resource_subtype,
            attributes=attributes or {},
            capacity=capacity,
            enabled=enabled,
        )
        result = await self._request(
            "PUT",
            f"/api/v1/capacity/resources/{resource_id}",
            body,
            request_id=request_id,
        )
        return dict(result)

    async def list_resources(
        self, *, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "GET", "/api/v1/capacity/resources", request_id=request_id
        )
        return list(result.get("resources") or [])


class SiteCapacityClient(_AuthenticatedSiteClient):
    """Authenticated seller client for buyer-facing site capacity operations."""

    def __init__(
        self,
        base_url: str,
        signer: Signer,
        expected_authorities: TrustedIdentitySet,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_timestamp_skew: int = 300,
    ) -> None:
        super().__init__(
            base_url,
            signer,
            expected_authorities,
            timeout=timeout,
            transport=transport,
            max_timestamp_skew=max_timestamp_skew,
        )

    async def snapshot(
        self, *, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "/api/v1/capacity/snapshot", request_id=request_id
        )
        return list(data.get("resources") or [])

    async def resource_pool_projection_version(
        self, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/capacity/site-resource-pools/version",
            request_id=request_id,
        )

    async def resource_pool_projection(
        self, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/capacity/site-resource-pools",
            request_id=request_id,
        )

    async def capacity_bucket_projection_version(
        self, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/capacity/site-capacity-buckets/version",
            request_id=request_id,
        )

    async def capacity_bucket_projection(
        self, *, request_id: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/capacity/site-capacity-buckets",
            request_id=request_id,
        )

    async def probe(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {"claim": dict(claim or {})}
        if lease_start_utc is not None:
            body["lease_start_utc"] = str(lease_start_utc)
        if lease_duration_seconds is not None:
            body["lease_duration_seconds"] = int(lease_duration_seconds)
        result = await self._request(
            "POST", "/api/v1/capacity/probe", body, request_id=request_id
        )
        return result.get("match")

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "claim": dict(claim or {}),
            "deal_ref": dict(deal_ref or {}),
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = float(ttl_seconds)
        if lease_start_utc is not None:
            body["lease_start_utc"] = str(lease_start_utc)
        if lease_duration_seconds is not None:
            body["lease_duration_seconds"] = int(lease_duration_seconds)
        result = await self._request(
            "POST", "/api/v1/capacity/reservations", body, request_id=request_id
        )
        return result.get("reservation")

    async def commit(
        self,
        *,
        resource_id: str | None = None,
        capacity_reservation_id: str | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if not capacity_reservation_id:
            raise ValueError(
                "remote capacity commit requires the capacity_reservation_id the "
                "reserve returned (the site ledger has no aggregate path)"
            )
        body = {
            key: value
            for key, value in {
                "resource_id": resource_id,
                "lease_start_utc": (
                    str(lease_start_utc) if lease_start_utc is not None else None
                ),
                "lease_end_utc": (
                    str(lease_end_utc) if lease_end_utc is not None else None
                ),
                "idempotency_ref": idempotency_ref,
            }.items()
            if value is not None
        }
        await self._request(
            "POST",
            "/api/v1/capacity/reservations/"
            f"{capacity_reservation_id}/commit",
            body,
            request_id=request_id,
        )

    async def release(
        self,
        *,
        capacity_reservation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        body: dict[str, Any] = {"deal_ref": dict(deal_ref or {})}
        if capacity_reservation_id is not None:
            body["capacity_reservation_id"] = capacity_reservation_id
        if failure_reason is not None:
            body["failure_reason"] = failure_reason
        if failure_message is not None:
            body["failure_message"] = failure_message
        result = await self._request(
            "POST", "/api/v1/capacity/releases", body, request_id=request_id
        )
        return result.get("reservation")

    async def truncate_lease(
        self,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        result = await self._request(
            "POST",
            "/api/v1/capacity/reservations/"
            f"{capacity_reservation_id}/truncate-lease",
            {"lease_end_utc": str(lease_end_utc)},
            request_id=request_id,
        )
        return result.get("reservation")

    async def list_reservations(
        self,
        *,
        state: str | None = None,
        escrow_uid: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if state is not None:
            query["state"] = state
        if escrow_uid is not None:
            query["escrow_uid"] = escrow_uid
        data = await self._request(
            "GET",
            "/api/v1/capacity/reservations",
            query=query,
            request_id=request_id,
        )
        return list(data.get("reservations") or [])

    async def get_reservation(
        self,
        capacity_reservation_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        data = await self._request(
            "GET",
            "/api/v1/capacity/reservations/"
            f"{capacity_reservation_id}",
            request_id=request_id,
        )
        return data.get("reservation")

    async def events_after(
        self,
        after_version: int,
        *,
        limit: int = 500,
        request_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        query = {"after": int(after_version), "limit": int(limit)}
        data = await self._request(
            "GET",
            "/api/v1/capacity/events",
            query=query,
            request_id=request_id,
        )
        return list(data.get("events") or []), int(data.get("latest_version") or 0)
