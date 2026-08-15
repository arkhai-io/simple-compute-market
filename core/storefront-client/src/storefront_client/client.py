"""HTTP clients for the Arkhai storefront REST API.

Two clients with identical method signatures:

``StorefrontClient``      — async, backed by ``httpx.AsyncClient``
``SyncStorefrontClient``  — sync,  backed by ``httpx.Client``

Both clients:
- Own their HTTP session internally — callers never create or pass a session.
- Accept a ``transport=`` kwarg at construction for in-process test injection.
- Raise ``StorefrontClientError`` on unexpected non-2xx responses.
- Return typed model objects from all methods.

Usage (async)::

    from market_identity import Ed25519Signer, Identity
    from storefront_client import StorefrontClient

    client = StorefrontClient(
        "http://seller-storefront:8001",
        signer=Ed25519Signer(seed),
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(
            identities=(
                Identity(
                    scheme="ed25519",
                    identifier="configured-publisher-key",
                ),
            )
        ),
    )
    async with client:
        resp = await client.negotiate_new(
            listing_id="listing-id",
            initial_amount=100,
            provision_terms={...},
        )
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.parse
from typing import Any

import httpx
from market_identity import (
    EMPTY_BODY,
    Identity,
    RotationIntent,
    RotationRequest,
    Signer,
    TrustedIdentitySet,
    canonical_json,
    sign_rotation,
)

from storefront_client.auth import (
    SignedRequest,
    StorefrontAuthenticationError,
    build_authenticated_request,
    verify_authenticated_response,
)
from storefront_client.models import (
    EvaluateNegotiateResponse,
    IdentitySubjectStatusResponse,
    StorefrontListingClaimResponse,
    StorefrontListingCloseResponse,
    StorefrontListingCreateResponse,
    StorefrontListingRefundResponse,
    HealthResponse,
    ListingListResponse,
    ListingSummary,
    ListingPauseResponse,
    NegotiationListResponse,
    NegotiationDetail,
    NegotiationActionResponse,
    AdminPauseResponse,
    ReleaseReservationsResponse,
    ReserveCapacityResponse,
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
    ImportResourcesResponse,
    StageEvent,
    StageEventListResponse,
)

logger = logging.getLogger(__name__)


class StorefrontClientError(Exception):
    """HTTP or protocol error from the storefront API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _validate_provision_terms_envelope(
    provision_terms: dict[str, Any],
) -> dict[str, Any]:
    """Validate the shared, schema-opaque negotiation envelope."""
    if not isinstance(provision_terms, dict):
        raise TypeError("provision_terms must be a mapping")
    expected = {"kind", "version", "payload"}
    actual = set(provision_terms)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            "provision_terms must contain exactly kind, version, and payload "
            f"(missing={missing}, extra={extra})"
        )
    kind = provision_terms["kind"]
    version = provision_terms["version"]
    payload = provision_terms["payload"]
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("provision_terms.kind must be a non-empty string")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("provision_terms.version must be a positive integer")
    if not isinstance(payload, dict):
        raise ValueError("provision_terms.payload must be a mapping")
    return {
        "kind": kind,
        "version": version,
        "payload": dict(payload),
    }


# ---------------------------------------------------------------------------
# Marketplace identity v2 helpers — shared by both clients
# ---------------------------------------------------------------------------


def _build_listings_params(
    *, limit: int, offset: int, **filters: Any
) -> dict[str, Any]:
    """Pack listing-list filter kwargs into URL params, dropping ``None`` and
    serializing booleans as the lowercase strings FastAPI expects.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    for key, val in filters.items():
        if val is None:
            continue
        params[key] = "true" if val is True else "false" if val is False else val
    return params


def _query_resource(prefix: str, params: dict[str, Any]) -> str:
    pairs = sorted((key, str(value)) for key, value in params.items())
    query = urllib.parse.urlencode(
        pairs,
        quote_via=urllib.parse.quote,
        safe="",
    )
    return f"{prefix}?{query}"


_ROTATION_AUTHORITIES = frozenset(
    {"storefront.administrator", "storefront.service-peer"}
)


def _validate_rotation_authority(authority: str) -> str:
    if authority not in _ROTATION_AUTHORITIES:
        raise ValueError(
            "authority must be 'storefront.administrator' or 'storefront.service-peer'"
        )
    return authority


def _rotation_resource(authority: str, subject: str) -> str:
    return "/".join(
        urllib.parse.quote(component, safe="") for component in (authority, subject)
    )


# ---------------------------------------------------------------------------
# Shared base — route paths, auth, response parsing
# ---------------------------------------------------------------------------


class _StorefrontClientBase:
    def __init__(
        self,
        base_url: str,
        signer: Signer | None,
        caller_role: str | None,
        expected_publishers: TrustedIdentitySet | None,
        timeout: float,
    ) -> None:
        if signer is not None and not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if signer is not None and caller_role is None:
            raise ValueError("caller_role is required when signer is configured")
        if signer is None and caller_role is not None:
            raise ValueError("caller_role requires signer")
        if signer is not None and expected_publishers is None:
            raise ValueError(
                "expected_publishers is required when signer is configured"
            )
        if signer is None and expected_publishers is not None:
            raise ValueError("expected_publishers requires signer")
        if expected_publishers is not None and not isinstance(
            expected_publishers, TrustedIdentitySet
        ):
            raise TypeError(
                "expected_publishers must be a market_identity.TrustedIdentitySet"
            )
        if (
            signer is not None
            and caller_role == "seller"
            and expected_publishers is not None
            and not expected_publishers.allows(signer.identity)
        ):
            raise ValueError("seller signer identity must be in expected_publishers")
        self._base = base_url.rstrip("/")
        self._signer = signer
        self._caller_role = caller_role
        self._expected_publishers = expected_publishers
        self._timeout = timeout
        self._signed_requests: dict[str, SignedRequest] = {}

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _signed_request(
        self,
        *,
        role: str,
        method: str,
        operation: str,
        resource: str,
        body: Any = EMPTY_BODY,
        request_id: str | None = None,
    ) -> SignedRequest:
        if self._signer is None:
            raise ValueError("this operation requires a configured signer")
        if self._caller_role != role:
            raise ValueError(
                f"this operation requires caller_role={role!r}, "
                f"not {self._caller_role!r}"
            )
        if request_id is not None and request_id in self._signed_requests:
            existing = self._signed_requests[request_id]
            content = None if body is EMPTY_BODY else canonical_json(body)
            context = (role, method.upper(), operation, resource, content)
            existing_context = (
                existing.role,
                existing.method,
                existing.operation,
                existing.resource,
                existing.content,
            )
            if context != existing_context:
                raise ValueError("request_id was reused with changed request content")
            if (
                existing.headers["X-Market-Identity-Scheme"]
                != self._signer.identity.scheme.value
                or existing.headers["X-Market-Identity-Identifier"]
                != self._signer.identity.identifier
            ):
                raise ValueError("configured signer identity changed")
        signed = build_authenticated_request(
            signer=self._signer,
            role=role,
            method=method,
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
        )
        if request_id is not None:
            self._signed_requests[request_id] = signed
        return signed

    def _principal_body(self) -> dict[str, str]:
        if self._signer is None:
            raise ValueError("this operation requires a configured signer")
        return self._signer.identity.model_dump(mode="json")

    def _require_admin_rotation_operator(
        self,
        *,
        authority: str,
        principal: Identity,
        phase: str,
    ) -> None:
        if authority == "storefront.administrator" and (
            self._signer is None or self._signer.identity != principal
        ):
            raise ValueError(
                f"administrator rotation {phase} requires the client signer "
                "to match the rotation principal"
            )

    def _verify_response(
        self,
        response: httpx.Response,
        request: SignedRequest,
        body: Any,
    ) -> None:
        if self._expected_publishers is None:
            raise StorefrontClientError(
                "authenticated responses require pinned expected_publishers"
            )
        try:
            verify_authenticated_response(
                headers=response.headers,
                expected_publishers=self._expected_publishers,
                request=request,
                status=response.status_code,
                body=body,
            )
        except StorefrontAuthenticationError as exc:
            raise StorefrontClientError(str(exc)) from exc

    @staticmethod
    def _raise_for_status(method: str, url: str, status: int, text: str) -> None:
        if status >= 400:
            raise StorefrontClientError(
                f"{method} {url} returned {status}: {text[:200]}",
                status_code=status,
            )


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class StorefrontClient(_StorefrontClientBase):
    """Async HTTP client for the Arkhai storefront REST API.

    Parameters
    ----------
    base_url:
        Base URL of the storefront (e.g. ``http://localhost:8001``).
    signer:
        Scheme-neutral marketplace signer used for authenticated operations.
    caller_role:
        Explicit role bound into every authenticated request. It must match the
        route's required role.
    expected_publishers:
        Required with ``signer``. Authenticated responses must carry a valid v2
        signature from this exact one-or-two-principal trusted set.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        signer: Signer | None = None,
        *,
        caller_role: str | None = None,
        expected_publishers: TrustedIdentitySet | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            signer,
            caller_role,
            expected_publishers,
            timeout,
        )
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "StorefrontClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _authenticated_post(
        self,
        path: str,
        body: Any,
        *,
        role: str,
        operation: str,
        resource: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="POST",
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
        )
        url = self._url(path)
        resp = await self._client.post(
            path,
            content=signed.content,
            headers=signed.headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"POST {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"POST {url} returned non-object JSON")
        return payload

    async def _authenticated_get(
        self,
        path: str,
        *,
        role: str,
        operation: str,
        resource: str,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        allowed_statuses: frozenset[int] = frozenset(),
        timeout: float | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )
        url = self._url(path)
        resp = await self._client.get(
            path,
            params=params,
            headers=signed.headers,
            timeout=self._timeout if timeout is None else timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"GET {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        if resp.status_code not in allowed_statuses:
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"GET {url} returned non-object JSON")
        return payload

    async def _authenticated_patch(
        self,
        path: str,
        body: dict[str, Any],
        *,
        role: str,
        operation: str,
        resource: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="PATCH",
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
        )
        url = self._url(path)
        resp = await self._client.patch(
            path,
            content=signed.content,
            headers=signed.headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"PATCH {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"PATCH {url} returned non-object JSON")
        return payload

    async def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = await self._client.get(path, params=params or {}, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    async def get_health(self) -> HealthResponse:
        """GET /health"""
        return HealthResponse.from_dict(await self._get("/health"))

    async def get_system_status(
        self,
        *,
        request_id: str | None = None,
    ) -> HealthResponse:
        """GET signed system status; a verified 503 remains inspectable."""
        return HealthResponse.from_dict(
            await self._authenticated_get(
                "/api/v1/system/status",
                role="service",
                operation="admin_system_status",
                resource="system/status",
                request_id=request_id,
                allowed_statuses=frozenset({503}),
            )
        )

    async def get_events(
        self,
        *,
        since_id: int = 0,
        limit: int = 100,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
        request_id: str | None = None,
    ) -> StageEventListResponse:
        """GET /api/v1/system/events through admin v2 authentication."""
        params: dict[str, Any] = {
            "since_id": since_id,
            "limit": limit,
            "stream": "false",
        }
        if stage is not None:
            params["stage"] = stage
        if listing_id is not None:
            params["listing_id"] = listing_id
        if negotiation_id is not None:
            params["negotiation_id"] = negotiation_id
        return StageEventListResponse.from_dict(
            await self._authenticated_get(
                "/api/v1/system/events",
                params=params,
                role="admin",
                operation="admin_system_events",
                resource=_query_resource("system-events", params),
                request_id=request_id,
            )
        )

    async def wait_for_stage_event(
        self,
        stage: str,
        event: str,
        *,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
        since_id: int = 0,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> StageEvent:
        """Poll GET /api/v1/system/events until a matching event appears.

        Pass ``since_id`` to ignore events older than that id — useful
        when waiting for the *next* matching event after triggering an
        action. Snapshot ``max(e.id for e in get_events().events)``
        before the trigger, then pass it here.

        Raises TimeoutError if the event is not seen within *timeout* seconds.
        """
        import time as _time

        deadline = _time.monotonic() + timeout
        cursor = since_id
        while _time.monotonic() < deadline:
            result = await self.get_events(
                since_id=cursor,
                limit=100,
                stage=stage,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
            )
            for ev in result.events:
                cursor = max(cursor, ev.id)
                if ev.stage == stage and ev.event == event:
                    return ev
            import asyncio as _asyncio

            await _asyncio.sleep(poll_interval)
        raise TimeoutError(
            f"Stage event stage={stage!r} event={event!r} "
            f"listing_id={listing_id!r} not seen within {timeout}s "
            f"(since_id={since_id})"
        )

    # ------------------------------------------------------------------
    # Listings API (GET endpoints unauthenticated; admin writes use v2 auth)
    # ------------------------------------------------------------------

    async def list_listings(
        self,
        *,
        status: str | None = None,
        paused: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /api/v1/listings — local resource enumeration.

        Discovery filters (gpu_model, region, token, etc.) moved to
        registries with milestone (a1b); query a registry's
        ``/filter-spec`` and ``/listings`` for those.
        """
        params = _build_listings_params(
            status=status,
            paused=paused,
            limit=limit,
            offset=offset,
        )
        return ListingListResponse.from_dict(
            await self._get("/api/v1/listings", params=params)
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}")
        )

    async def pause_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause."""
        return ListingPauseResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                role="admin",
                operation="admin_pause_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    async def resume_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume."""
        return ListingPauseResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                role="admin",
                operation="admin_resume_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Negotiations API
    # ------------------------------------------------------------------

    async def list_negotiations(
        self,
        listing_id: str,
        *,
        terminal_state: str | None = None,
        buyer_principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
        request_id: str | None = None,
    ) -> "NegotiationListResponse":
        """GET /api/v1/listings/{listing_id}/negotiations through admin v2 auth."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_principal is not None:
            if not isinstance(buyer_principal, Identity):
                raise TypeError("buyer_principal must be a market_identity.Identity")
            params["buyer_scheme"] = buyer_principal.scheme.value
            params["buyer_identifier"] = buyer_principal.identifier
        prefix = f"{listing_id}/negotiations"
        return NegotiationListResponse.from_dict(
            await self._authenticated_get(
                f"/api/v1/listings/{listing_id}/negotiations",
                params=params,
                role="admin",
                operation="admin_list_negotiations",
                resource=_query_resource(prefix, params),
                request_id=request_id,
            )
        )

    async def get_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        request_id: str | None = None,
    ) -> "NegotiationDetail":
        """GET one negotiation through admin v2 authentication."""
        resource = f"{listing_id}/negotiations/{neg_id}"
        return NegotiationDetail.from_dict(
            await self._authenticated_get(
                f"/api/v1/listings/{resource}",
                role="admin",
                operation="admin_get_negotiation",
                resource=resource,
                request_id=request_id,
            )
        )

    async def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance  (admin key)"""
        body: dict[str, Any] = {"action": action}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                role="admin",
                operation="admin_advance_negotiation",
                resource=f"{listing_id}/{neg_id}",
                request_id=request_id,
            )
        )

    async def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        amount: int,
        request_id: str | None = None,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept  (admin key)"""
        return NegotiationActionResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"amount": int(amount)},
                role="admin",
                operation="admin_force_accept_negotiation",
                resource=f"{listing_id}/{neg_id}",
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    async def admin_pause(
        self,
        *,
        request_id: str | None = None,
    ) -> AdminPauseResponse:
        """POST /api/v1/admin/pause."""
        return AdminPauseResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/pause",
                {},
                role="admin",
                operation="admin_pause",
                resource="",
                request_id=request_id,
            )
        )

    async def admin_resume(
        self,
        *,
        request_id: str | None = None,
    ) -> AdminPauseResponse:
        """POST /api/v1/admin/resume."""
        return AdminPauseResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/resume",
                {},
                role="admin",
                operation="admin_resume",
                resource="",
                request_id=request_id,
            )
        )

    async def admin_initiate_identity_rotation(
        self,
        *,
        authority: str,
        subject: str,
        current_signer: Signer,
        replacement_signer: Signer,
        nonce: str,
        overlap_seconds: int,
        expires_at: int,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Apply one canonical rotation carrying both possession proofs."""
        authority = _validate_rotation_authority(authority)
        self._require_admin_rotation_operator(
            authority=authority,
            principal=current_signer.identity,
            phase="initiation",
        )
        rotation = sign_rotation(
            current_signer=current_signer,
            replacement_signer=replacement_signer,
            intent=RotationIntent(
                current=current_signer.identity,
                replacement=replacement_signer.identity,
                subject=subject,
                authority=authority,
                nonce=nonce,
                overlap_seconds=overlap_seconds,
                expires_at=expires_at,
            ),
        )
        return IdentitySubjectStatusResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/identity/rotations",
                rotation.model_dump(mode="json"),
                role="admin",
                operation="admin_rotate_identity",
                resource=_rotation_resource(authority, subject),
                request_id=request_id,
            )
        )

    async def admin_complete_identity_rotation(
        self,
        *,
        rotation: RotationRequest,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Retire the old principal from an applied two-proof rotation."""
        if not isinstance(rotation, RotationRequest):
            raise TypeError("rotation must be a market_identity.RotationRequest")
        intent = rotation.intent
        authority = _validate_rotation_authority(intent.authority)
        self._require_admin_rotation_operator(
            authority=authority,
            principal=intent.replacement,
            phase="completion",
        )
        body = {
            "authority": authority,
            "subject": intent.subject,
            "rotation_nonce": intent.nonce,
            "principal": intent.current.model_dump(mode="json"),
        }
        return IdentitySubjectStatusResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/identity/retirements",
                body,
                role="admin",
                operation="admin_retire_identity",
                resource=_rotation_resource(authority, intent.subject),
                request_id=request_id,
            )
        )

    async def admin_get_identity_status(
        self,
        *,
        authority: str,
        subject: str,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Inspect current and retired bindings for one identity subject."""
        authority = _validate_rotation_authority(authority)
        params = {"authority": authority, "subject": subject}
        return IdentitySubjectStatusResponse.from_dict(
            await self._authenticated_get(
                "/api/v1/admin/identity/status",
                params=params,
                role="admin",
                operation="admin_identity_status",
                resource=_query_resource("identity-status", params),
                request_id=request_id,
            )
        )

    async def admin_interrupt_deal(
        self,
        escrow_uid: str,
        *,
        reason: str = "operator_interruption",
        interrupted_at_utc: str | None = None,
        dry_run: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Interrupt an active interruptible deal through the admin control plane."""
        body: dict[str, Any] = {"reason": reason, "dry_run": dry_run}
        if interrupted_at_utc is not None:
            body["interrupted_at_utc"] = interrupted_at_utc
        return await self._authenticated_post(
            f"/api/v1/admin/deals/{escrow_uid}/interrupt",
            body,
            role="admin",
            operation="admin_interrupt_deal",
            resource=escrow_uid,
            request_id=request_id,
        )

    async def admin_import_resources(
        self,
        csv_content: bytes,
        filename: str = "resources.csv",
        *,
        request_id: str | None = None,
    ) -> ImportResourcesResponse:
        """Upload a CSV using a signed boundary-independent descriptor."""
        if not isinstance(csv_content, bytes):
            raise TypeError("csv_content must be bytes")
        descriptor = {
            "filename": filename,
            "media_type": "text/csv",
            "sha256": hashlib.sha256(csv_content).hexdigest(),
            "size": len(csv_content),
        }
        signed = self._signed_request(
            role="admin",
            method="POST",
            operation="admin_import_resources",
            resource="portfolio/resources",
            body=descriptor,
            request_id=request_id,
        )
        headers = dict(signed.headers)
        headers.pop("Content-Type", None)
        path = "/api/v1/admin/portfolio/resources/import"
        url = self._url(path)
        resp = await self._client.post(
            path,
            files={"file": (filename, csv_content, "text/csv")},
            headers=headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"POST {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"POST {url} returned non-object JSON")
        return ImportResourcesResponse.from_dict(payload)

    async def admin_reserve_capacity(
        self,
        *,
        required_attributes: dict[str, Any],
        listing_id: str | None = None,
        escrow_uid: str | None = None,
        request_id: str | None = None,
    ) -> ReserveCapacityResponse:
        """POST /api/v1/admin/portfolio/reservations."""
        body = {
            "required_attributes": required_attributes,
            "listing_id": listing_id,
            "escrow_uid": escrow_uid,
        }
        return ReserveCapacityResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/portfolio/reservations",
                body,
                role="admin",
                operation="admin_reserve_capacity",
                resource=listing_id or escrow_uid or "",
                request_id=request_id,
            )
        )

    async def admin_release_reservations(
        self,
        *,
        request_id: str | None = None,
    ) -> "ReleaseReservationsResponse":
        """POST /api/v1/admin/portfolio/release-reservations."""
        return ReleaseReservationsResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/admin/portfolio/release-reservations",
                {},
                role="admin",
                operation="admin_release_reservations",
                resource="",
                request_id=request_id,
            )
        )

    async def get_resource(
        self,
        resource_id: str,
        *,
        request_id: str | None = None,
    ) -> dict:
        """GET /api/v1/admin/portfolio/resources/{resource_id}."""
        return await self._authenticated_get(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            role="admin",
            operation="admin_get_resource",
            resource=resource_id,
            request_id=request_id,
        )

    async def notify_capacity_released(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        resource_id: "str | None" = None,
        provider_lease_id: "str | None" = None,
        released_at: "str | None" = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated capacity release callback.

        Reuse ``request_id`` with an identical body after an uncertain
        acknowledgement; changed reuse is rejected locally.

        Deal-scoped event from the capacity side: the reservation's lease
        ended and its capacity returned to the pool. The site authority's
        watchdog delivers this point-to-point to the deal's owning
        storefront — it replaces the legacy resource PATCH for
        ledger-held reservations.
        """
        body: dict = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        if resource_id is not None:
            body["resource_id"] = resource_id
        if provider_lease_id is not None:
            body["provider_lease_id"] = provider_lease_id
        if released_at is not None:
            body["released_at"] = released_at
        return await self._authenticated_post(
            "/api/v1/admin/fulfillment/events/capacity-released",
            body,
            role="service",
            operation="fulfillment_capacity_released",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    async def notify_usage_started(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        escrow_uid: "str | None" = None,
        provider_id: "str | None" = None,
        provider_lease_id: "str | None" = None,
        resource_id: "str | None" = None,
        vm_host: "str | None" = None,
        vm_target: "str | None" = None,
        gpu_count: "int | None" = None,
        lease_end_utc: "str | None" = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated usage-started callback.

        Deal-scoped progress event: the reservation moved from held to
        actually leased/in-use. Progress events carry no capacity effect
        of their own (the reservation stays held throughout), but do
        reconcile derived listings against current availability.
        """
        body: dict = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        if escrow_uid is not None:
            body["escrow_uid"] = escrow_uid
        if provider_id is not None:
            body["provider_id"] = provider_id
        if provider_lease_id is not None:
            body["provider_lease_id"] = provider_lease_id
        if resource_id is not None:
            body["resource_id"] = resource_id
        if vm_host is not None:
            body["vm_host"] = vm_host
        if vm_target is not None:
            body["vm_target"] = vm_target
        if gpu_count is not None:
            body["gpu_count"] = gpu_count
        if lease_end_utc is not None:
            body["lease_end_utc"] = lease_end_utc
        return await self._authenticated_post(
            "/api/v1/admin/fulfillment/events/usage-started",
            body,
            role="service",
            operation="fulfillment_usage_started",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    async def notify_fulfillment_failed(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        escrow_uid: "str | None" = None,
        provider_id: "str | None" = None,
        provider_job_id: "str | None" = None,
        resource_id: "str | None" = None,
        reason: "str | None" = None,
        message: "str | None" = None,
        logs_ref: "str | None" = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated fulfillment-failed callback.

        Deal-scoped event: provisioning failed for this reservation.
        Releases the held capacity through the site authority and
        applies the storefront's own fulfillment failure policy.
        """
        body: dict = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        if escrow_uid is not None:
            body["escrow_uid"] = escrow_uid
        if provider_id is not None:
            body["provider_id"] = provider_id
        if provider_job_id is not None:
            body["provider_job_id"] = provider_job_id
        if resource_id is not None:
            body["resource_id"] = resource_id
        if reason is not None:
            body["reason"] = reason
        if message is not None:
            body["message"] = message
        if logs_ref is not None:
            body["logs_ref"] = logs_ref
        return await self._authenticated_post(
            "/api/v1/admin/fulfillment/events/failed",
            body,
            role="service",
            operation="fulfillment_failed",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    async def patch_resource(
        self,
        resource_id: str,
        *,
        state: "str | None" = None,
        attributes: "dict | None" = None,
        request_id: str | None = None,
    ) -> dict:
        """PATCH /api/v1/admin/portfolio/resources/{resource_id}.

        Partial update of a resource row. Only supplied (non-None) fields are
        written. Returns the full resource row after the patch.
        """
        body: dict = {}
        if state is not None:
            body["state"] = state
        if attributes is not None:
            body["attributes"] = attributes
        return await self._authenticated_patch(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            body,
            role="admin",
            operation="admin_patch_resource",
            resource=resource_id,
            request_id=request_id,
        )

    async def evaluate_negotiate(
        self,
        listing_id: str,
        *,
        proposal: dict[str, Any],
        buyer_principal: Identity,
        requested_duration_seconds: int | None = None,
        request_id: str | None = None,
    ) -> EvaluateNegotiateResponse:
        """POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate.

        Runs the configured negotiation strategy against a synthetic buyer
        proposal without creating a negotiation thread or writing to the
        database. ``proposal`` is the full EscrowProposal-shaped dict;
        scalar payment escrows carry the absolute opening amount in
        ``fields["amount"]``. Returns
        ``EvaluateNegotiateResponse.would_negotiate=False`` when the
        strategy would exit immediately.
        """
        if not isinstance(buyer_principal, Identity):
            raise TypeError("buyer_principal must be a market_identity.Identity")
        body: dict[str, Any] = {
            "proposal": proposal,
            "buyer_principal": buyer_principal.model_dump(mode="json"),
        }
        if requested_duration_seconds is not None:
            body["requested_duration_seconds"] = int(requested_duration_seconds)
        return EvaluateNegotiateResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/admin/listings/{listing_id}/evaluate-negotiate",
                body,
                role="admin",
                operation="admin_evaluate_negotiation",
                resource=listing_id,
                request_id=request_id,
            )
        )

    async def create_listing(
        self,
        *,
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]] | None = None,
        settlements: list[dict[str, Any]] | None = None,
        settlement_options: list[dict[str, Any]] | None = None,
        settlement_config: dict[str, Any] | None = None,
        demands: list[dict[str, Any]] | None = None,
        max_duration_seconds: int | None = None,
        paused: bool = False,
        request_id: str | None = None,
    ) -> StorefrontListingCreateResponse:
        """Create a listing through the seller-authenticated v2 contract."""
        body = {
            "offer": offer,
            "accepted_escrows": accepted_escrows or [],
            "settlements": settlements or [],
            "settlement_options": settlement_options or [],
            "settlement_config": settlement_config,
            "demands": demands or [],
            "max_duration_seconds": max_duration_seconds,
            "paused": paused,
        }
        return StorefrontListingCreateResponse.from_dict(
            await self._authenticated_post(
                "/api/v1/listings/create",
                body,
                role="seller",
                operation="create_listing",
                resource="",
                request_id=request_id,
            )
        )

    async def close_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> StorefrontListingCloseResponse:
        """POST /api/v1/listings/{listing_id}/close."""
        return StorefrontListingCloseResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/close",
                EMPTY_BODY,
                role="seller",
                operation="close_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    async def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_principal: Identity,
        buyer_evm_address: str,
        amount: str | int | None = None,
        token: str | None = None,
        request_id: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /api/v1/listings/{listing_id}/refund."""
        if not isinstance(buyer_principal, Identity):
            raise TypeError("buyer_principal must be a market_identity.Identity")
        body: dict[str, Any] = {
            "buyer_principal": buyer_principal.model_dump(mode="json"),
            "buyer_evm_address": buyer_evm_address,
            "amount": amount,
            "token": token,
        }
        return StorefrontListingRefundResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/refund",
                body,
                role="seller",
                operation="refund_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    async def claim_listing(
        self,
        *,
        listing_id: str,
        escrow_uid: str,
        fulfillment_uid: str,
        request_id: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /api/v1/listings/{listing_id}/claim."""
        body: dict[str, Any] = {
            "escrow_uid": escrow_uid,
            "claimant_principal": self._principal_body(),
            "fulfillment_uid": fulfillment_uid,
        }
        return StorefrontListingClaimResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/listings/{listing_id}/claim",
                body,
                role="seller",
                operation="claim_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Buyer protocol — negotiate / settle
    # Marketplace identity v2 binds the exact canonical body and request context.
    # ------------------------------------------------------------------

    async def negotiate_new(
        self,
        *,
        listing_id: str,
        initial_amount: int | None,
        provision_terms: dict[str, Any],
        buyer_agent_url: str = "",
        token: str = "",
        chain_name: str = "",
        escrow_address: str = "",
        escrow_expiration_unix: int | None = None,
        proposal_fields: dict[str, Any] | None = None,
        literal_fields: dict[str, Any] | None = None,
        rates: list[dict[str, Any]] | None = None,
        demands: list[dict[str, Any]] | None = None,
        settlement_selection: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/new through the buyer v2 contract.

        ``provision_terms`` is the required versioned domain envelope. The
        shared client validates only its generic shape and never constructs or
        interprets a domain payload. ``initial_amount`` is the absolute opening
        amount for scalar escrows; amountless exact escrows can pass
        ``initial_amount=None`` with explicit ``literal_fields`` / ``rates``.
        """
        exp_unix = escrow_expiration_unix or (int(time.time()) + 3600)
        fields = dict(proposal_fields or {})
        if initial_amount is not None:
            fields.setdefault("amount", str(initial_amount))
        literals = dict(literal_fields or {})
        if token or literal_fields is None:
            literals.setdefault("token", token or ("0x" + "0" * 40))
        proposal = {
            "chain_name": chain_name or "anvil",
            "escrow_address": escrow_address or ("0x" + "0" * 40),
            "fields": fields,
            "literal_fields": literals,
            "expiration_unix": exp_unix,
        }
        if rates is not None:
            proposal["rates"] = rates
        if demands is not None:
            proposal["demands"] = demands
        body = {
            "listing_id": listing_id,
            "buyer_principal": self._principal_body(),
            "provision_terms": _validate_provision_terms_envelope(
                provision_terms,
            ),
            "proposal": proposal,
            "settlement_selection": settlement_selection,
            "buyer_agent_url": buyer_agent_url,
        }
        return await self._authenticated_post(
            "/api/v1/negotiate/new",
            body,
            role="buyer",
            operation="negotiate_new",
            resource=listing_id,
            request_id=request_id,
        )

    async def negotiate_continue(
        self,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        settlement_selection: dict[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/{neg_id}.

        ``proposal`` is the full EscrowProposal-shaped dict for ``counter``;
        omitted for ``accept`` / ``exit``. ``fields["amount"]`` carries the
        buyer's absolute new offer in base units.
        """
        body: dict[str, Any] = {
            "action": action,
            "buyer_principal": self._principal_body(),
            "proposal": proposal,
            "settlement_selection": settlement_selection,
            "reason": reason,
        }
        return await self._authenticated_post(
            f"/api/v1/negotiate/{neg_id}",
            body,
            role="buyer",
            operation="negotiate_continue",
            resource=neg_id,
            request_id=request_id,
        )

    async def settle(
        self,
        escrow_uid: str,
        *,
        negotiation_id: str,
        buyer_evm_address: str,
        ssh_public_key: str = "",
        chain_name: str = "anvil",
        request_id: str | None = None,
    ) -> SettleResponse:
        """POST /api/v1/settle/{escrow_uid} through the buyer v2 contract.

        ``buyer_evm_address`` is the selected EVM settlement-effect address; it
        is deliberately distinct from the signer-owned marketplace principal.
        """
        body: dict[str, Any] = {
            "negotiation_id": negotiation_id,
            "buyer_principal": self._principal_body(),
            "buyer_evm_address": buyer_evm_address,
            "ssh_public_key": ssh_public_key,
            "chain_name": chain_name,
        }
        return SettleResponse.from_dict(
            await self._authenticated_post(
                f"/api/v1/settle/{escrow_uid}",
                body,
                role="buyer",
                operation="settle_escrow",
                resource=escrow_uid,
                request_id=request_id,
            )
        )

    async def get_settle_status(
        self,
        escrow_uid: str,
        *,
        request_id: str | None = None,
    ) -> SettleStatusResponse:
        """GET /api/v1/settle/{escrow_uid}/status through buyer v2 auth."""
        return SettleStatusResponse.from_dict(
            await self._authenticated_get(
                f"/api/v1/settle/{escrow_uid}/status",
                role="buyer",
                operation="settle_status",
                resource=escrow_uid,
                request_id=request_id,
            )
        )

    async def wait_for_settlement(
        self,
        escrow_uid: str,
        *,
        timeout: float = 60.0,
        request_id: str | None = None,
    ) -> SettleWaitResponse:
        """GET /api/v1/admin/settle/{escrow_uid}/wait — long-poll (admin).

        Single server-side long-poll: the storefront blocks internally until the
        settlement job reaches ``ready`` or ``failed``, or until *timeout* seconds
        elapse. Returns immediately if the job is already terminal.

        Callers must check ``result.ready`` and ``result.status``:
        - ``ready=True, status="ready"`` — provisioning complete, credentials available
        - ``ready=True, status="failed"`` — provisioning failed
        - ``ready=False`` — timed out before reaching a terminal state

        Raises ``StorefrontClientError`` on non-2xx responses.
        """
        timeout_value = str(timeout)
        return SettleWaitResponse.from_dict(
            await self._authenticated_get(
                f"/api/v1/admin/settle/{escrow_uid}/wait",
                params={"timeout": timeout_value},
                role="admin",
                operation="admin_settle_wait",
                resource=f"{escrow_uid}?timeout={timeout_value}",
                request_id=request_id,
                timeout=timeout + 10.0,
            )
        )

    async def verify_settle(
        self,
        escrow_uid: str,
        *,
        seller_wallet: str,
        agreed_price: float,
        agreed_duration_seconds: int,
        listing_id: str,
        chain_name: str = "anvil",
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/verify.

        Reads the escrow from chain on ``chain_name`` and confirms it
        matches the supplied terms. Returns dict with valid=True/False
        and reason on failure. No DB writes. Used by e2e stage 7b.
        """
        body = {
            "seller_wallet": seller_wallet,
            "agreed_price": agreed_price,
            "agreed_duration_seconds": agreed_duration_seconds,
            "listing_id": listing_id,
            "chain_name": chain_name,
        }
        return await self._authenticated_post(
            f"/api/v1/admin/settle/{escrow_uid}/verify",
            body,
            role="admin",
            operation="admin_verify_settlement",
            resource=escrow_uid,
            request_id=request_id,
        )

    async def evaluate_settle(
        self,
        escrow_uid: str,
        *,
        listing_id: str,
        ssh_public_key: str = "",
        duration_seconds: int = 3600,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/evaluate.

        Resolves a host from inventory and builds the job spec without chain reads,
        DB writes, or provisioning calls. Returns dict with would_submit, vm_host,
        vm_target, required_attributes. Used by e2e stage 8a.
        """
        body = {
            "listing_id": listing_id,
            "ssh_public_key": ssh_public_key,
            "duration_seconds": duration_seconds,
        }
        return await self._authenticated_post(
            f"/api/v1/admin/settle/{escrow_uid}/evaluate",
            body,
            role="admin",
            operation="admin_evaluate_settlement",
            resource=escrow_uid,
            request_id=request_id,
        )


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class SyncStorefrontClient(_StorefrontClientBase):
    """Synchronous HTTP client for the Arkhai storefront REST API.

    Identical method signatures to ``StorefrontClient`` but blocking.
    Suitable for synchronous CLI commands, smoke tests, and scripts.

    Parameters
    ----------
    base_url:
        Base URL of the storefront.
    signer:
        Scheme-neutral marketplace signer used for authenticated operations.
    caller_role:
        Explicit role bound into every authenticated request.
    expected_publishers:
        Required with ``signer``; pins v2 responses to one or two publishers.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.BaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        signer: Signer | None = None,
        *,
        caller_role: str | None = None,
        expected_publishers: TrustedIdentitySet | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            signer,
            caller_role,
            expected_publishers,
            timeout,
        )
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SyncStorefrontClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _authenticated_post(
        self,
        path: str,
        body: Any,
        *,
        role: str,
        operation: str,
        resource: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="POST",
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
        )
        url = self._url(path)
        resp = self._client.post(
            path,
            content=signed.content,
            headers=signed.headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"POST {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"POST {url} returned non-object JSON")
        return payload

    def _authenticated_get(
        self,
        path: str,
        *,
        role: str,
        operation: str,
        resource: str,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        allowed_statuses: frozenset[int] = frozenset(),
        timeout: float | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="GET",
            operation=operation,
            resource=resource,
            request_id=request_id,
        )
        url = self._url(path)
        resp = self._client.get(
            path,
            params=params,
            headers=signed.headers,
            timeout=self._timeout if timeout is None else timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"GET {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        if resp.status_code not in allowed_statuses:
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"GET {url} returned non-object JSON")
        return payload

    def _authenticated_patch(
        self,
        path: str,
        body: dict[str, Any],
        *,
        role: str,
        operation: str,
        resource: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        signed = self._signed_request(
            role=role,
            method="PATCH",
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
        )
        url = self._url(path)
        resp = self._client.patch(
            path,
            content=signed.content,
            headers=signed.headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"PATCH {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"PATCH {url} returned non-object JSON")
        return payload

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.get(path, params=params or {}, timeout=self._timeout)
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # System / health
    # ------------------------------------------------------------------

    def get_health(self) -> HealthResponse:
        """GET /health"""
        return HealthResponse.from_dict(self._get("/health"))

    def get_system_status(
        self,
        *,
        request_id: str | None = None,
    ) -> HealthResponse:
        """GET signed system status; a verified 503 remains inspectable."""
        return HealthResponse.from_dict(
            self._authenticated_get(
                "/api/v1/system/status",
                role="service",
                operation="admin_system_status",
                resource="system/status",
                request_id=request_id,
                allowed_statuses=frozenset({503}),
            )
        )

    def get_events(
        self,
        *,
        since_id: int = 0,
        limit: int = 100,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
        request_id: str | None = None,
    ) -> StageEventListResponse:
        """GET /api/v1/system/events through admin v2 authentication."""
        params: dict[str, Any] = {
            "since_id": since_id,
            "limit": limit,
            "stream": "false",
        }
        if stage is not None:
            params["stage"] = stage
        if listing_id is not None:
            params["listing_id"] = listing_id
        if negotiation_id is not None:
            params["negotiation_id"] = negotiation_id
        return StageEventListResponse.from_dict(
            self._authenticated_get(
                "/api/v1/system/events",
                params=params,
                role="admin",
                operation="admin_system_events",
                resource=_query_resource("system-events", params),
                request_id=request_id,
            )
        )

    def wait_for_stage_event(
        self,
        stage: str,
        event: str,
        *,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
        since_id: int = 0,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> StageEvent:
        """Poll GET /api/v1/system/events until a matching event appears.

        Pass ``since_id`` to ignore events older than that id — useful
        when waiting for the *next* matching event after triggering an
        action. Snapshot ``max(e.id for e in get_events().events)``
        before the trigger, then pass it here.

        Raises TimeoutError if the event is not seen within *timeout* seconds.
        """
        import time as _time

        deadline = _time.monotonic() + timeout
        cursor = since_id
        while _time.monotonic() < deadline:
            result = self.get_events(
                since_id=cursor,
                limit=100,
                stage=stage,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
            )
            for ev in result.events:
                cursor = max(cursor, ev.id)
                if ev.stage == stage and ev.event == event:
                    return ev
            _time.sleep(poll_interval)
        raise TimeoutError(
            f"Stage event stage={stage!r} event={event!r} "
            f"listing_id={listing_id!r} not seen within {timeout}s "
            f"(since_id={since_id})"
        )

    # ------------------------------------------------------------------
    # Listings API
    # ------------------------------------------------------------------

    def list_listings(
        self,
        *,
        status: str | None = None,
        paused: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        """GET /api/v1/listings — see :meth:`StorefrontClient.list_listings`."""
        params = _build_listings_params(
            status=status,
            paused=paused,
            limit=limit,
            offset=offset,
        )
        return ListingListResponse.from_dict(
            self._get("/api/v1/listings", params=params)
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(self._get(f"/api/v1/listings/{listing_id}"))

    def pause_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause."""
        return ListingPauseResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                role="admin",
                operation="admin_pause_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    def resume_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume."""
        return ListingPauseResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                role="admin",
                operation="admin_resume_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Negotiations API
    # ------------------------------------------------------------------

    def list_negotiations(
        self,
        listing_id: str,
        *,
        terminal_state: str | None = None,
        buyer_principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
        request_id: str | None = None,
    ) -> NegotiationListResponse:
        """GET /api/v1/listings/{listing_id}/negotiations through admin v2 auth."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_principal is not None:
            if not isinstance(buyer_principal, Identity):
                raise TypeError("buyer_principal must be a market_identity.Identity")
            params["buyer_scheme"] = buyer_principal.scheme.value
            params["buyer_identifier"] = buyer_principal.identifier
        prefix = f"{listing_id}/negotiations"
        return NegotiationListResponse.from_dict(
            self._authenticated_get(
                f"/api/v1/listings/{listing_id}/negotiations",
                params=params,
                role="admin",
                operation="admin_list_negotiations",
                resource=_query_resource(prefix, params),
                request_id=request_id,
            )
        )

    def get_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        request_id: str | None = None,
    ) -> NegotiationDetail:
        """GET one negotiation through admin v2 authentication."""
        resource = f"{listing_id}/negotiations/{neg_id}"
        return NegotiationDetail.from_dict(
            self._authenticated_get(
                f"/api/v1/listings/{resource}",
                role="admin",
                operation="admin_get_negotiation",
                resource=resource,
                request_id=request_id,
            )
        )

    def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> NegotiationActionResponse:
        """POST .../advance  (admin key required)"""
        body: dict[str, Any] = {"action": action}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                role="admin",
                operation="admin_advance_negotiation",
                resource=f"{listing_id}/{neg_id}",
                request_id=request_id,
            )
        )

    def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        amount: int,
        request_id: str | None = None,
    ) -> NegotiationActionResponse:
        """POST .../force-accept  (admin key required)"""
        return NegotiationActionResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"amount": int(amount)},
                role="admin",
                operation="admin_force_accept_negotiation",
                resource=f"{listing_id}/{neg_id}",
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    def admin_pause(
        self,
        *,
        request_id: str | None = None,
    ) -> AdminPauseResponse:
        """POST /api/v1/admin/pause."""
        return AdminPauseResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/pause",
                {},
                role="admin",
                operation="admin_pause",
                resource="",
                request_id=request_id,
            )
        )

    def admin_resume(
        self,
        *,
        request_id: str | None = None,
    ) -> AdminPauseResponse:
        """POST /api/v1/admin/resume."""
        return AdminPauseResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/resume",
                {},
                role="admin",
                operation="admin_resume",
                resource="",
                request_id=request_id,
            )
        )

    def admin_initiate_identity_rotation(
        self,
        *,
        authority: str,
        subject: str,
        current_signer: Signer,
        replacement_signer: Signer,
        nonce: str,
        overlap_seconds: int,
        expires_at: int,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Apply one canonical rotation carrying both possession proofs."""
        authority = _validate_rotation_authority(authority)
        self._require_admin_rotation_operator(
            authority=authority,
            principal=current_signer.identity,
            phase="initiation",
        )
        rotation = sign_rotation(
            current_signer=current_signer,
            replacement_signer=replacement_signer,
            intent=RotationIntent(
                current=current_signer.identity,
                replacement=replacement_signer.identity,
                subject=subject,
                authority=authority,
                nonce=nonce,
                overlap_seconds=overlap_seconds,
                expires_at=expires_at,
            ),
        )
        return IdentitySubjectStatusResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/identity/rotations",
                rotation.model_dump(mode="json"),
                role="admin",
                operation="admin_rotate_identity",
                resource=_rotation_resource(authority, subject),
                request_id=request_id,
            )
        )

    def admin_complete_identity_rotation(
        self,
        *,
        rotation: RotationRequest,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Retire the old principal from an applied two-proof rotation."""
        if not isinstance(rotation, RotationRequest):
            raise TypeError("rotation must be a market_identity.RotationRequest")
        intent = rotation.intent
        authority = _validate_rotation_authority(intent.authority)
        self._require_admin_rotation_operator(
            authority=authority,
            principal=intent.replacement,
            phase="completion",
        )
        body = {
            "authority": authority,
            "subject": intent.subject,
            "rotation_nonce": intent.nonce,
            "principal": intent.current.model_dump(mode="json"),
        }
        return IdentitySubjectStatusResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/identity/retirements",
                body,
                role="admin",
                operation="admin_retire_identity",
                resource=_rotation_resource(authority, intent.subject),
                request_id=request_id,
            )
        )

    def admin_get_identity_status(
        self,
        *,
        authority: str,
        subject: str,
        request_id: str | None = None,
    ) -> IdentitySubjectStatusResponse:
        """Inspect current and retired bindings for one identity subject."""
        authority = _validate_rotation_authority(authority)
        params = {"authority": authority, "subject": subject}
        return IdentitySubjectStatusResponse.from_dict(
            self._authenticated_get(
                "/api/v1/admin/identity/status",
                params=params,
                role="admin",
                operation="admin_identity_status",
                resource=_query_resource("identity-status", params),
                request_id=request_id,
            )
        )

    def admin_interrupt_deal(
        self,
        escrow_uid: str,
        *,
        reason: str = "operator_interruption",
        interrupted_at_utc: str | None = None,
        dry_run: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Interrupt an active interruptible deal through the admin control plane."""
        body: dict[str, Any] = {"reason": reason, "dry_run": dry_run}
        if interrupted_at_utc is not None:
            body["interrupted_at_utc"] = interrupted_at_utc
        return self._authenticated_post(
            f"/api/v1/admin/deals/{escrow_uid}/interrupt",
            body,
            role="admin",
            operation="admin_interrupt_deal",
            resource=escrow_uid,
            request_id=request_id,
        )

    def admin_import_resources(
        self,
        csv_content: bytes,
        filename: str = "resources.csv",
        *,
        request_id: str | None = None,
    ) -> ImportResourcesResponse:
        """Upload a CSV using a signed boundary-independent descriptor."""
        if not isinstance(csv_content, bytes):
            raise TypeError("csv_content must be bytes")
        descriptor = {
            "filename": filename,
            "media_type": "text/csv",
            "sha256": hashlib.sha256(csv_content).hexdigest(),
            "size": len(csv_content),
        }
        signed = self._signed_request(
            role="admin",
            method="POST",
            operation="admin_import_resources",
            resource="portfolio/resources",
            body=descriptor,
            request_id=request_id,
        )
        headers = dict(signed.headers)
        headers.pop("Content-Type", None)
        path = "/api/v1/admin/portfolio/resources/import"
        url = self._url(path)
        resp = self._client.post(
            path,
            files={"file": (filename, csv_content, "text/csv")},
            headers=headers,
            timeout=self._timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise StorefrontClientError(
                f"POST {url} returned non-JSON response authentication body"
            ) from exc
        self._verify_response(resp, signed, payload)
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        if not isinstance(payload, dict):
            raise StorefrontClientError(f"POST {url} returned non-object JSON")
        return ImportResourcesResponse.from_dict(payload)

    def admin_reserve_capacity(
        self,
        *,
        required_attributes: dict[str, Any],
        listing_id: str | None = None,
        escrow_uid: str | None = None,
        request_id: str | None = None,
    ) -> ReserveCapacityResponse:
        """POST /api/v1/admin/portfolio/reservations."""
        body = {
            "required_attributes": required_attributes,
            "listing_id": listing_id,
            "escrow_uid": escrow_uid,
        }
        return ReserveCapacityResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/portfolio/reservations",
                body,
                role="admin",
                operation="admin_reserve_capacity",
                resource=listing_id or escrow_uid or "",
                request_id=request_id,
            )
        )

    def admin_release_reservations(
        self,
        *,
        request_id: str | None = None,
    ) -> "ReleaseReservationsResponse":
        """POST /api/v1/admin/portfolio/release-reservations."""
        return ReleaseReservationsResponse.from_dict(
            self._authenticated_post(
                "/api/v1/admin/portfolio/release-reservations",
                {},
                role="admin",
                operation="admin_release_reservations",
                resource="",
                request_id=request_id,
            )
        )

    def get_resource(
        self,
        resource_id: str,
        *,
        request_id: str | None = None,
    ) -> dict:
        """GET /api/v1/admin/portfolio/resources/{resource_id}."""
        return self._authenticated_get(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            role="admin",
            operation="admin_get_resource",
            resource=resource_id,
            request_id=request_id,
        )

    def notify_capacity_released(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        resource_id: str | None = None,
        provider_lease_id: str | None = None,
        released_at: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated capacity release callback.

        Reuse ``request_id`` with an identical body after an uncertain
        acknowledgement; changed reuse is rejected locally.
        """
        body: dict[str, Any] = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        if resource_id is not None:
            body["resource_id"] = resource_id
        if provider_lease_id is not None:
            body["provider_lease_id"] = provider_lease_id
        if released_at is not None:
            body["released_at"] = released_at
        return self._authenticated_post(
            "/api/v1/admin/fulfillment/events/capacity-released",
            body,
            role="service",
            operation="fulfillment_capacity_released",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    def notify_usage_started(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        escrow_uid: str | None = None,
        provider_id: str | None = None,
        provider_lease_id: str | None = None,
        resource_id: str | None = None,
        vm_host: str | None = None,
        vm_target: str | None = None,
        gpu_count: int | None = None,
        lease_end_utc: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated usage-started callback."""
        body: dict[str, Any] = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        optional = {
            "escrow_uid": escrow_uid,
            "provider_id": provider_id,
            "provider_lease_id": provider_lease_id,
            "resource_id": resource_id,
            "vm_host": vm_host,
            "vm_target": vm_target,
            "gpu_count": gpu_count,
            "lease_end_utc": lease_end_utc,
        }
        body.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        return self._authenticated_post(
            "/api/v1/admin/fulfillment/events/usage-started",
            body,
            role="service",
            operation="fulfillment_usage_started",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    def notify_fulfillment_failed(
        self,
        capacity_reservation_id: str,
        *,
        site_id: str,
        escrow_uid: str | None = None,
        provider_id: str | None = None,
        provider_job_id: str | None = None,
        resource_id: str | None = None,
        reason: str | None = None,
        message: str | None = None,
        logs_ref: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Post a service-authenticated fulfillment-failed callback."""
        body: dict[str, Any] = {
            "capacity_reservation_id": capacity_reservation_id,
            "site_id": site_id,
        }
        optional = {
            "escrow_uid": escrow_uid,
            "provider_id": provider_id,
            "provider_job_id": provider_job_id,
            "resource_id": resource_id,
            "reason": reason,
            "message": message,
            "logs_ref": logs_ref,
        }
        body.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        return self._authenticated_post(
            "/api/v1/admin/fulfillment/events/failed",
            body,
            role="service",
            operation="fulfillment_failed",
            resource=capacity_reservation_id,
            request_id=request_id,
        )

    def patch_resource(
        self,
        resource_id: str,
        *,
        state: "str | None" = None,
        attributes: "dict | None" = None,
        request_id: str | None = None,
    ) -> dict:
        """PATCH /api/v1/admin/portfolio/resources/{resource_id}.

        Partial update of a resource row. Only supplied (non-None) fields are
        written; unspecified fields are left unchanged. Returns the full
        resource row after the patch.

        Primary use cases:
          - Release a lease: ``patch_resource(id, state='available', attributes={'lease_end_utc': None})``
          - Force a state transition for testing or operator recovery.

        Returns the raw response dict from the endpoint.
        """
        body: dict = {}
        if state is not None:
            body["state"] = state
        if attributes is not None:
            body["attributes"] = attributes
        return self._authenticated_patch(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            body,
            role="admin",
            operation="admin_patch_resource",
            resource=resource_id,
            request_id=request_id,
        )

    def evaluate_negotiate(
        self,
        listing_id: str,
        *,
        proposal: dict[str, Any],
        buyer_principal: Identity,
        requested_duration_seconds: int | None = None,
        request_id: str | None = None,
    ) -> EvaluateNegotiateResponse:
        """POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate.

        Runs the configured negotiation strategy against a synthetic buyer
        proposal without creating a negotiation thread or writing to the
        database. ``proposal`` is the full EscrowProposal-shaped dict;
        scalar payment escrows carry the absolute opening amount in
        ``fields["amount"]``. Returns
        ``EvaluateNegotiateResponse.would_negotiate=False`` when the
        strategy would exit immediately.
        """
        if not isinstance(buyer_principal, Identity):
            raise TypeError("buyer_principal must be a market_identity.Identity")
        body: dict[str, Any] = {
            "proposal": proposal,
            "buyer_principal": buyer_principal.model_dump(mode="json"),
        }
        if requested_duration_seconds is not None:
            body["requested_duration_seconds"] = int(requested_duration_seconds)
        return EvaluateNegotiateResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/admin/listings/{listing_id}/evaluate-negotiate",
                body,
                role="admin",
                operation="admin_evaluate_negotiation",
                resource=listing_id,
                request_id=request_id,
            )
        )

    def create_listing(
        self,
        *,
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]] | None = None,
        settlements: list[dict[str, Any]] | None = None,
        settlement_options: list[dict[str, Any]] | None = None,
        settlement_config: dict[str, Any] | None = None,
        demands: list[dict[str, Any]] | None = None,
        max_duration_seconds: int | None = None,
        paused: bool = False,
        request_id: str | None = None,
    ) -> StorefrontListingCreateResponse:
        """Create a listing through the seller-authenticated v2 contract."""
        body = {
            "offer": offer,
            "accepted_escrows": accepted_escrows or [],
            "settlements": settlements or [],
            "settlement_options": settlement_options or [],
            "settlement_config": settlement_config,
            "demands": demands or [],
            "max_duration_seconds": max_duration_seconds,
            "paused": paused,
        }
        return StorefrontListingCreateResponse.from_dict(
            self._authenticated_post(
                "/api/v1/listings/create",
                body,
                role="seller",
                operation="create_listing",
                resource="",
                request_id=request_id,
            )
        )

    def close_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
    ) -> StorefrontListingCloseResponse:
        """POST /api/v1/listings/{listing_id}/close."""
        return StorefrontListingCloseResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/close",
                EMPTY_BODY,
                role="seller",
                operation="close_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_principal: Identity,
        buyer_evm_address: str,
        amount: str | int | None = None,
        token: str | None = None,
        request_id: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /api/v1/listings/{listing_id}/refund."""
        if not isinstance(buyer_principal, Identity):
            raise TypeError("buyer_principal must be a market_identity.Identity")
        body: dict[str, Any] = {
            "buyer_principal": buyer_principal.model_dump(mode="json"),
            "buyer_evm_address": buyer_evm_address,
            "amount": amount,
            "token": token,
        }
        return StorefrontListingRefundResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/refund",
                body,
                role="seller",
                operation="refund_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    def claim_listing(
        self,
        *,
        listing_id: str,
        escrow_uid: str,
        fulfillment_uid: str,
        request_id: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /api/v1/listings/{listing_id}/claim."""
        body: dict[str, Any] = {
            "escrow_uid": escrow_uid,
            "claimant_principal": self._principal_body(),
            "fulfillment_uid": fulfillment_uid,
        }
        return StorefrontListingClaimResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/listings/{listing_id}/claim",
                body,
                role="seller",
                operation="claim_listing",
                resource=listing_id,
                request_id=request_id,
            )
        )

    # ------------------------------------------------------------------
    # Buyer protocol — negotiate / settle
    # Marketplace identity v2 binds the exact canonical body and request context.
    # ------------------------------------------------------------------

    def negotiate_new(
        self,
        *,
        listing_id: str,
        initial_amount: int | None,
        provision_terms: dict[str, Any],
        buyer_agent_url: str = "",
        token: str = "",
        chain_name: str = "",
        escrow_address: str = "",
        escrow_expiration_unix: int | None = None,
        proposal_fields: dict[str, Any] | None = None,
        literal_fields: dict[str, Any] | None = None,
        rates: list[dict[str, Any]] | None = None,
        demands: list[dict[str, Any]] | None = None,
        settlement_selection: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/new through the buyer v2 contract.

        ``provision_terms`` is the required versioned domain envelope. The
        shared client validates its generic shape without interpreting payload.
        """
        exp_unix = escrow_expiration_unix or (int(time.time()) + 3600)
        fields = dict(proposal_fields or {})
        if initial_amount is not None:
            fields.setdefault("amount", str(initial_amount))
        literals = dict(literal_fields or {})
        if token or literal_fields is None:
            literals.setdefault("token", token or ("0x" + "0" * 40))
        proposal = {
            "chain_name": chain_name or "anvil",
            "escrow_address": escrow_address or ("0x" + "0" * 40),
            "fields": fields,
            "literal_fields": literals,
            "expiration_unix": exp_unix,
        }
        if rates is not None:
            proposal["rates"] = rates
        if demands is not None:
            proposal["demands"] = demands
        body = {
            "listing_id": listing_id,
            "buyer_principal": self._principal_body(),
            "provision_terms": _validate_provision_terms_envelope(
                provision_terms,
            ),
            "proposal": proposal,
            "settlement_selection": settlement_selection,
            "buyer_agent_url": buyer_agent_url,
        }
        return self._authenticated_post(
            "/api/v1/negotiate/new",
            body,
            role="buyer",
            operation="negotiate_new",
            resource=listing_id,
            request_id=request_id,
        )

    def negotiate_continue(
        self,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        settlement_selection: dict[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/{neg_id}.

        ``proposal`` is the full EscrowProposal-shaped dict for ``counter``;
        omitted for ``accept`` / ``exit``. ``fields["amount"]`` carries the
        buyer's absolute new offer in base units.
        """
        body: dict[str, Any] = {
            "action": action,
            "buyer_principal": self._principal_body(),
            "proposal": proposal,
            "settlement_selection": settlement_selection,
            "reason": reason,
        }
        return self._authenticated_post(
            f"/api/v1/negotiate/{neg_id}",
            body,
            role="buyer",
            operation="negotiate_continue",
            resource=neg_id,
            request_id=request_id,
        )

    def settle(
        self,
        escrow_uid: str,
        *,
        negotiation_id: str,
        buyer_evm_address: str,
        ssh_public_key: str = "",
        chain_name: str = "anvil",
        request_id: str | None = None,
    ) -> SettleResponse:
        """POST /api/v1/settle/{escrow_uid} through the buyer v2 contract.

        ``buyer_evm_address`` is the selected EVM settlement-effect address; it
        is deliberately distinct from the signer-owned marketplace principal.
        """
        body: dict[str, Any] = {
            "negotiation_id": negotiation_id,
            "buyer_principal": self._principal_body(),
            "buyer_evm_address": buyer_evm_address,
            "ssh_public_key": ssh_public_key,
            "chain_name": chain_name,
        }
        return SettleResponse.from_dict(
            self._authenticated_post(
                f"/api/v1/settle/{escrow_uid}",
                body,
                role="buyer",
                operation="settle_escrow",
                resource=escrow_uid,
                request_id=request_id,
            )
        )

    def get_settle_status(
        self,
        escrow_uid: str,
        *,
        request_id: str | None = None,
    ) -> SettleStatusResponse:
        """GET /api/v1/settle/{escrow_uid}/status through buyer v2 auth."""
        return SettleStatusResponse.from_dict(
            self._authenticated_get(
                f"/api/v1/settle/{escrow_uid}/status",
                role="buyer",
                operation="settle_status",
                resource=escrow_uid,
                request_id=request_id,
            )
        )

    def wait_for_settlement(
        self,
        escrow_uid: str,
        *,
        timeout: float = 60.0,
        request_id: str | None = None,
    ) -> SettleWaitResponse:
        """GET /api/v1/admin/settle/{escrow_uid}/wait — long-poll (admin).

        Single server-side long-poll: the storefront blocks internally until the
        settlement job reaches ``ready`` or ``failed``, or until *timeout* seconds
        elapse. Returns immediately if the job is already terminal.

        Callers must check ``result.ready`` and ``result.status``:
        - ``ready=True, status="ready"`` — provisioning complete, credentials available
        - ``ready=True, status="failed"`` — provisioning failed
        - ``ready=False`` — timed out before reaching a terminal state

        Raises ``StorefrontClientError`` on non-2xx responses.
        """
        timeout_value = str(timeout)
        return SettleWaitResponse.from_dict(
            self._authenticated_get(
                f"/api/v1/admin/settle/{escrow_uid}/wait",
                params={"timeout": timeout_value},
                role="admin",
                operation="admin_settle_wait",
                resource=f"{escrow_uid}?timeout={timeout_value}",
                request_id=request_id,
                timeout=timeout + 10.0,
            )
        )

    def verify_settle(
        self,
        escrow_uid: str,
        *,
        seller_wallet: str,
        agreed_price: float,
        agreed_duration_seconds: int,
        listing_id: str,
        chain_name: str = "anvil",
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/verify.

        Reads the escrow from chain on ``chain_name`` and confirms it
        matches the supplied terms. Returns dict with valid=True/False
        and reason on failure. No DB writes. Used by e2e stage 7b.
        """
        body = {
            "seller_wallet": seller_wallet,
            "agreed_price": agreed_price,
            "agreed_duration_seconds": agreed_duration_seconds,
            "listing_id": listing_id,
            "chain_name": chain_name,
        }
        return self._authenticated_post(
            f"/api/v1/admin/settle/{escrow_uid}/verify",
            body,
            role="admin",
            operation="admin_verify_settlement",
            resource=escrow_uid,
            request_id=request_id,
        )

    def evaluate_settle(
        self,
        escrow_uid: str,
        *,
        listing_id: str,
        ssh_public_key: str = "",
        duration_seconds: int = 3600,
        request_id: str | None = None,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/evaluate.

        Resolves a host from inventory and builds the job spec without chain reads,
        DB writes, or provisioning calls. Returns dict with would_submit, vm_host,
        vm_target, required_attributes. Used by e2e stage 8a.
        """
        body = {
            "listing_id": listing_id,
            "ssh_public_key": ssh_public_key,
            "duration_seconds": duration_seconds,
        }
        return self._authenticated_post(
            f"/api/v1/admin/settle/{escrow_uid}/evaluate",
            body,
            role="admin",
            operation="admin_evaluate_settlement",
            resource=escrow_uid,
            request_id=request_id,
        )
