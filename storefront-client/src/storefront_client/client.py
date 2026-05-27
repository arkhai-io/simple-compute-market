"""HTTP clients for the Arkhai storefront REST API.

Two clients with identical method signatures:

``StorefrontClient``      — async, backed by ``httpx.AsyncClient``
``SyncStorefrontClient``  — sync,  backed by ``httpx.Client``

Both clients:
- Own their HTTP session internally — callers never create or pass a session.
- Accept a ``transport=`` kwarg at construction for in-process test injection.
- Raise ``StorefrontClientError`` on non-2xx responses.
- Return typed model objects from all methods.

Usage (async)::

    from storefront_client import StorefrontClient

    client = StorefrontClient("http://seller-storefront:8001", private_key="0x...")
    async with client:
        reg = await client.get_registration()
        resp = await client.create_listing(
            agent_wallet_address="0xSellerWallet",
            offer={...},
            accepted_escrows=[{"chain_name": ..., "escrow_address": ...,
                               "fields": {...}, "price_per_hour": ...}],
        )

Usage (sync, e.g. smoke tests)::

    from storefront_client import SyncStorefrontClient

    client = SyncStorefrontClient("http://seller-storefront:8001", private_key="0x...")
    reg = client.get_registration()
    client.close()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from storefront_client.models import (
    EvaluateNegotiateResponse,
    StorefrontListingClaimResponse,
    StorefrontListingCloseResponse,
    StorefrontListingCreateResponse,
    StorefrontListingRefundResponse,
    ERC8004RegistrationFile,
    HealthResponse,
    ListingListResponse,
    ListingSummary,
    ListingPauseResponse,
    NegotiationListResponse,
    NegotiationDetail,
    NegotiationActionResponse,
    AdminPauseResponse,
    ReleaseReservationsResponse,
    RegistryAgentReadyResponse,
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


# ---------------------------------------------------------------------------
# EIP-191 signing helpers — shared by both clients
# ---------------------------------------------------------------------------


def _sign_eip191(private_key: str, message: str) -> str:
    """Sign *message* with *private_key* using EIP-191 personal_sign."""
    from eth_account import Account
    from eth_account.messages import encode_defunct
    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=private_key)
    return signed.signature.hex()


def _address_from_private_key(private_key: str) -> str:
    """Derive the EIP-191 wallet address (lowercase) for a private key."""
    from eth_account import Account
    return Account.from_key(private_key).address.lower()


def _signed_request_headers(
    private_key: str,
    message: str,
    *,
    identity_scheme: str = "eip191",
    identity_identifier: str | None = None,
) -> dict[str, str]:
    """Return the four signed-request headers for an arbitrary ``message``.

    Differs from :func:`_build_auth_headers` only in that the caller has
    already composed the full canonical message (used by per-endpoint
    constructions that include the timestamp inline). Always emits the
    ``X-Identity-Scheme`` / ``X-Identity`` pair.
    """
    ts = str(int(time.time()))
    full_message = f"{message}:{ts}"
    sig = _sign_eip191(private_key, full_message)
    identifier = identity_identifier or _address_from_private_key(private_key)
    return {
        "X-Timestamp": ts,
        "X-Signature": sig,
        "X-Identity-Scheme": identity_scheme,
        "X-Identity": identifier,
    }


def _build_auth_headers(
    private_key: str,
    operation: str,
    resource_id: str,
    *,
    identity_scheme: str = "eip191",
    identity_identifier: str | None = None,
) -> dict[str, str]:
    """Build signed-request headers for the storefront.

    Headers emitted:
      ``X-Timestamp`` / ``X-Signature`` — EIP-191 signature of
      ``"<operation>:<resource_id>:<timestamp>"``.
      ``X-Identity-Scheme`` / ``X-Identity`` — the scheme-tagged identity
      that the signature attests; defaults to ``("eip191", <address derived
      from private_key>)``. Servers that predate the pluggable-identity
      headers ignore them; servers that don't dispatch through their
      identity-scheme registry.
    """
    timestamp = str(int(time.time()))
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = _sign_eip191(private_key, message)
    identifier = identity_identifier or _address_from_private_key(private_key)
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "X-Identity-Scheme": identity_scheme,
        "X-Identity": identifier,
    }


def _build_listings_params(*, limit: int, offset: int, **filters: Any) -> dict[str, Any]:
    """Pack listing-list filter kwargs into URL params, dropping ``None`` and
    serializing booleans as the lowercase strings FastAPI expects.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    for key, val in filters.items():
        if val is None:
            continue
        params[key] = "true" if val is True else "false" if val is False else val
    return params


# ---------------------------------------------------------------------------
# Shared base — route paths, auth, response parsing
# ---------------------------------------------------------------------------


class _StorefrontClientBase:
    def __init__(
        self,
        base_url: str,
        private_key: Optional[str],
        timeout: float,
        admin_key: Optional[str] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._private_key = private_key
        self._timeout = timeout
        self._admin_key = admin_key

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _auth_headers(self, operation: str, resource_id: str) -> dict[str, str]:
        if not self._private_key:
            return {}
        return _build_auth_headers(self._private_key, operation, resource_id)

    def _admin_headers(self) -> dict[str, str]:
        if not self._admin_key:
            return {}
        return {"X-Admin-Key": self._admin_key}

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
    private_key:
        EIP-191 private key for signing auth headers. When ``None`` auth
        headers are omitted — only works if the storefront has
        ``AGENT_WALLET_ADDRESS`` unset.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.AsyncBaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        private_key: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        admin_key: Optional[str] = None,
    ) -> None:
        super().__init__(base_url, private_key, timeout, admin_key)
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

    async def _post(self, path: str, body: dict, *, extra_headers: dict | None = None) -> dict:
        url = self._url(path)
        resp = await self._client.post(
            path, json=body, headers=extra_headers or {}, timeout=self._timeout
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

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

    async def get_system_status(self) -> HealthResponse:
        """GET /api/v1/system/status — includes paused flag and check results.

        Does NOT raise on HTTP 503.  A 503 from this endpoint means the
        storefront is degraded (e.g. registry unreachable) but still returns a
        structured HealthResponse that callers can inspect.  Only unexpected
        status codes (4xx, non-503 5xx) raise StorefrontClientError.
        """
        url = self._url("/api/v1/system/status")
        resp = await self._client.get(
            "/api/v1/system/status", timeout=self._timeout,
            headers=self._admin_headers(),
        )
        if resp.status_code not in (200, 503):
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        return HealthResponse.from_dict(resp.json())

    async def wait_for_registry_agent_ready(
        self,
        *,
        timeout: float = 90.0,
    ) -> RegistryAgentReadyResponse:
        """GET /api/v1/system/wait-for-registry-agent — long-poll (admin).

        Single server-side long-poll: the storefront blocks internally until
        ``registry_auth_check()`` returns a definitive result (anything other
        than ``"agent_not_found"``), or until *timeout* seconds elapse.

        Returns ``RegistryAgentReadyResponse``.  Callers must check
        ``result.ready`` and ``result.registry_auth``:
        - ``ready=True, registry_auth="ok"`` — agent indexed and owner verified
        - ``ready=True, registry_auth=<other>`` — definitive but non-ok
        - ``ready=False`` — timed out while still ``"agent_not_found"``

        Raises ``StorefrontClientError`` on non-2xx responses.
        """
        url = self._url("/api/v1/system/wait-for-registry-agent")
        resp = await self._client.get(
            "/api/v1/system/wait-for-registry-agent",
            params={"timeout": timeout},
            headers=self._admin_headers(),
            timeout=timeout + 10.0,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return RegistryAgentReadyResponse.from_dict(resp.json())

    async def get_events(
        self,
        *,
        since_id: int = 0,
        limit: int = 100,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
    ) -> StageEventListResponse:
        """GET /api/v1/system/events — historical query (admin key required)."""
        params: dict[str, Any] = {"since_id": since_id, "limit": limit}
        if stage is not None:
            params["stage"] = stage
        if listing_id is not None:
            params["listing_id"] = listing_id
        if negotiation_id is not None:
            params["negotiation_id"] = negotiation_id
        url = self._url("/api/v1/system/events")
        resp = await self._client.get(
            "/api/v1/system/events",
            params=params,
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return StageEventListResponse.from_dict(resp.json())

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
    # Listings API (GET endpoints unauthenticated; write endpoints admin-key)
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
            status=status, paused=paused, limit=limit, offset=offset,
        )
        return ListingListResponse.from_dict(
            await self._get("/api/v1/listings", params=params)
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}")
        )

    async def pause_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause  (admin key required)"""
        return ListingPauseResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    async def resume_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume  (admin key required)"""
        return ListingPauseResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                extra_headers=self._admin_headers(),
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
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> "NegotiationListResponse":
        """GET /api/v1/listings/{listing_id}/negotiations"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_address is not None:
            params["buyer_address"] = buyer_address
        return NegotiationListResponse.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}/negotiations", params=params)
        )

    async def get_negotiation(self, listing_id: str, neg_id: str) -> "NegotiationDetail":
        """GET /api/v1/listings/{listing_id}/negotiations/{neg_id}"""
        return NegotiationDetail.from_dict(
            await self._get(f"/api/v1/listings/{listing_id}/negotiations/{neg_id}")
        )

    async def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance  (admin key)"""
        body: dict[str, Any] = {"action": action}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                extra_headers=self._admin_headers(),
            )
        )

    async def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        amount: int,
    ) -> "NegotiationActionResponse":
        """POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept  (admin key)"""
        return NegotiationActionResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"amount": int(amount)},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    async def admin_pause(self) -> AdminPauseResponse:
        """POST /admin/pause  (admin key required)"""
        return AdminPauseResponse.from_dict(
            await self._post("/api/v1/admin/pause", {}, extra_headers=self._admin_headers())
        )

    async def admin_resume(self) -> AdminPauseResponse:
        """POST /admin/resume  (admin key required)"""
        return AdminPauseResponse.from_dict(
            await self._post("/api/v1/admin/resume", {}, extra_headers=self._admin_headers())
        )

    async def admin_import_resources(
        self, csv_content: bytes, filename: str = "resources.csv"
    ) -> ImportResourcesResponse:
        """POST /admin/portfolio/resources/import  (admin key required).

        Upload a compute resource CSV to bulk-upsert portfolio rows. Always
        upserts regardless of current table state — use to force a clobber
        of the current inventory without restarting the pod.

        ``csv_content`` is the raw bytes of the CSV file. Typically read
        with ``Path(...).read_bytes()`` or ``open(..., "rb").read()``.
        """
        url = self._url("/api/v1/admin/portfolio/resources/import")
        resp = await self._client.post(
            "/api/v1/admin/portfolio/resources/import",
            files={"file": (filename, csv_content, "text/csv")},
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return ImportResourcesResponse.from_dict(resp.json())

    async def get_resource(self, resource_id: str) -> dict:
        """GET /api/v1/admin/portfolio/resources/{resource_id}  (admin key required).

        Returns the current state of the resource row — same shape as patch_resource.
        404 if the resource_id does not exist.
        """
        url = self._url(f"/api/v1/admin/portfolio/resources/{resource_id}")
        resp = await self._client.get(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    async def patch_resource(
        self,
        resource_id: str,
        *,
        state: "str | None" = None,
        attributes: "dict | None" = None,
    ) -> dict:
        """PATCH /api/v1/admin/portfolio/resources/{resource_id}  (admin key required).

        Partial update of a resource row. Only supplied (non-None) fields are
        written. Returns the full resource row after the patch.
        """
        body: dict = {}
        if state is not None:
            body["state"] = state
        if attributes is not None:
            body["attributes"] = attributes
        url = self._url(f"/api/v1/admin/portfolio/resources/{resource_id}")
        resp = await self._client.patch(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            json=body,
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        return resp.json()

    async def evaluate_negotiate(
        self,
        listing_id: str,
        *,
        proposal: dict[str, Any],
        requested_duration_seconds: int | None = None,
        buyer_address: str = "",
    ) -> EvaluateNegotiateResponse:
        """POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate — dry-run (admin key).

        Runs the configured negotiation strategy against a synthetic buyer
        proposal without creating a negotiation thread or writing to the
        database. ``proposal`` is the full EscrowProposal-shaped dict (with
        ``fields["amount"]`` carrying the absolute opening amount in base
        units). Returns ``EvaluateNegotiateResponse.would_negotiate=False``
        when the strategy would exit immediately.
        """
        body: dict[str, Any] = {"proposal": proposal, "buyer_address": buyer_address}
        if requested_duration_seconds is not None:
            body["requested_duration_seconds"] = int(requested_duration_seconds)
        return EvaluateNegotiateResponse.from_dict(
            await self._post(
                f"/api/v1/admin/listings/{listing_id}/evaluate-negotiate", body,
                extra_headers=self._admin_headers(),
            )
        )



    async def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            await self._get("/.well-known/erc-8004-registration.json")
        )

    async def create_listing(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        max_duration_seconds: int | None = None,
        paused: bool = False,
    ) -> StorefrontListingCreateResponse:
        """POST /listings/create.

        ``accepted_escrows`` lists the escrow shapes the seller will accept
        for this listing. Each entry pins ``(chain_name, escrow_address)``
        plus a partial ``ObligationData`` advertisement via the ``fields``
        map, with the per-hour rate in ``price_per_hour``.

        ``max_duration_seconds`` is the optional ceiling on lease duration
        (None = unlimited). Buyers supply the actual duration at
        negotiation init time; total payment is computed at agreement as
        ``price_per_hour × agreed_duration_seconds / 3600``. Pass
        ``paused=True`` to create the listing in local SQLite without
        publishing to the registry; call ``resume_listing`` to publish.
        """
        headers = self._auth_headers("create_listing", agent_wallet_address)
        body = {
            "offer": offer,
            "accepted_escrows": accepted_escrows,
            "max_duration_seconds": max_duration_seconds,
            "paused": paused,
        }
        return StorefrontListingCreateResponse.from_dict(
            await self._post("/api/v1/listings/create", body, extra_headers=headers)
        )

    async def close_listing(self, listing_id: str) -> StorefrontListingCloseResponse:
        """POST /listings/close"""
        headers = self._auth_headers("close_listing", listing_id)
        return StorefrontListingCloseResponse.from_dict(
            await self._post("/listings/close", {"listing_id": listing_id}, extra_headers=headers)
        )

    async def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_address: str | None = None,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /api/v1/listings/{listing_id}/refund

        ``buyer_address`` is optional; the storefront resolves it from the
        listing's recorded buyer when omitted.
        """
        headers = self._auth_headers("refund_listing", listing_id)
        body: dict[str, Any] = {}
        if buyer_address is not None:
            body["buyer_address"] = buyer_address
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontListingRefundResponse.from_dict(
            await self._post(
                f"/api/v1/listings/{listing_id}/refund",
                body, extra_headers=headers,
            )
        )

    async def claim_listing(
        self,
        *,
        listing_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /listings/claim"""
        headers = self._auth_headers("claim_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontListingClaimResponse.from_dict(
            await self._post("/listings/claim", body, extra_headers=headers)
        )


    # ------------------------------------------------------------------
    # Buyer protocol — negotiate / settle
    # EIP-191 signed X-Signature + X-Timestamp headers are added automatically.
    # ------------------------------------------------------------------

    async def negotiate_new(
        self,
        *,
        listing_id: str,
        buyer_address: str,
        initial_amount: int,
        duration_seconds: int,
        buyer_agent_url: str = "",
        ssh_public_key: str = "",
        token: str = "",
        chain_name: str = "",
        escrow_address: str = "",
        escrow_expiration_unix: int | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/new — adds EIP-191 auth headers automatically.

        ``provision_terms`` and ``proposal`` are required by the wire
        protocol; this helper builds canonical defaults from the scalar
        args so smoke / integration tests can keep their current call
        shape. ``initial_amount`` is the absolute opening amount in base
        units of the payment token (already multiplied out from any
        per-hour rate). ``chain_name`` + ``escrow_address`` pick the
        listing's accepted_escrows entry to propose against; ``token``
        populates ``fields["token"]``. Empty values produce zero-address
        / placeholder strings — legal in environments where the seller's
        listing has no typed payment token; the seller validates against
        its acceptance set.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"negotiate_new:{listing_id}",
            identity_identifier=buyer_address,
        )
        exp_unix = escrow_expiration_unix or (int(time.time()) + 3600)
        body = {
            "listing_id": listing_id,
            "buyer_address": buyer_address,
            "provision_terms": {
                "duration_seconds": duration_seconds,
                "ssh_public_key": ssh_public_key,
                "compute_resource": None,
            },
            "proposal": {
                "chain_name": chain_name or "anvil",
                "escrow_address": escrow_address or ("0x" + "0" * 40),
                "fields": {
                    "amount": int(initial_amount),
                    "token": token or ("0x" + "0" * 40),
                },
                "expiration_unix": exp_unix,
            },
            "buyer_agent_url": buyer_agent_url,
        }
        return await self._post(
            "/api/v1/negotiate/new", body, extra_headers=headers,
        )

    async def negotiate_continue(
        self,
        neg_id: str,
        *,
        action: str,
        buyer_address: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/{neg_id}.

        ``proposal`` is the full EscrowProposal-shaped dict for ``counter``;
        omitted for ``accept`` / ``exit``. ``fields["amount"]`` carries the
        buyer's absolute new offer in base units.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"negotiate_continue:{neg_id}",
            identity_identifier=buyer_address,
        )
        body: dict = {"action": action, "buyer_address": buyer_address}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return await self._post(
            f"/api/v1/negotiate/{neg_id}", body, extra_headers=headers,
        )

    async def settle(
        self,
        escrow_uid: str,
        *,
        negotiation_id: str,
        buyer_address: str,
        ssh_public_key: str = "",
        chain_name: str = "anvil",
    ) -> SettleResponse:
        """POST /api/v1/settle/{escrow_uid} — adds EIP-191 auth headers automatically.

        ``chain_name`` tells the seller which configured ``[chains.<name>]``
        entry to dispatch the on-chain verify against. Defaults to ``"anvil"``
        for compatibility with the e2e fixture; non-anvil consumers must
        pass their own value.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"settle_escrow:{escrow_uid}",
            identity_identifier=buyer_address,
        )
        body: dict = {
            "negotiation_id": negotiation_id,
            "buyer_address": buyer_address,
            "chain_name": chain_name,
        }
        if ssh_public_key:
            body["ssh_public_key"] = ssh_public_key
        return SettleResponse.from_dict(
            await self._post(
                f"/api/v1/settle/{escrow_uid}", body, extra_headers=headers,
            )
        )

    async def get_settle_status(
        self,
        escrow_uid: str,
        *,
        buyer_address: str,
    ) -> SettleStatusResponse:
        """GET /api/v1/settle/{escrow_uid}/status — adds EIP-191 auth headers automatically."""
        headers = _signed_request_headers(
            self._private_key,
            f"settle_status:{escrow_uid}",
            identity_identifier=buyer_address,
        )
        url = self._url(f"/api/v1/settle/{escrow_uid}/status")
        resp = await self._client.get(
            f"/api/v1/settle/{escrow_uid}/status",
            params={"buyer_address": buyer_address},
            headers=headers,
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return SettleStatusResponse.from_dict(resp.json())

    async def wait_for_settlement(
        self,
        escrow_uid: str,
        *,
        timeout: float = 60.0,
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
        url = self._url(f"/api/v1/admin/settle/{escrow_uid}/wait")
        resp = await self._client.get(
            f"/api/v1/admin/settle/{escrow_uid}/wait",
            params={"timeout": timeout},
            headers=self._admin_headers(),
            timeout=timeout + 10.0,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return SettleWaitResponse.from_dict(resp.json())

    async def verify_settle(
        self,
        escrow_uid: str,
        *,
        seller_wallet: str,
        agreed_price: float,
        agreed_duration_seconds: int,
        listing_id: str,
        chain_name: str = "anvil",
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/verify — dry-run escrow chain read (admin key).

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
        return await self._post(
            f"/api/v1/admin/settle/{escrow_uid}/verify", body,
            extra_headers=self._admin_headers(),
        )

    async def evaluate_settle(
        self,
        escrow_uid: str,
        *,
        listing_id: str,
        ssh_public_key: str = "",
        duration_seconds: int = 3600,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/evaluate — dry-run provisioning job spec (admin key).

        Resolves a host from inventory and builds the job spec without chain reads,
        DB writes, or provisioning calls. Returns dict with would_submit, vm_host,
        vm_target, required_attributes. Used by e2e stage 8a.
        """
        body = {
            "listing_id": listing_id,
            "ssh_public_key": ssh_public_key,
            "duration_seconds": duration_seconds,
        }
        return await self._post(
            f"/api/v1/admin/settle/{escrow_uid}/evaluate", body,
            extra_headers=self._admin_headers(),
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
    private_key:
        EIP-191 private key for signing auth headers.
    timeout:
        HTTP timeout in seconds.
    transport:
        Optional ``httpx.BaseTransport`` for in-process test injection.
    """

    def __init__(
        self,
        base_url: str,
        private_key: Optional[str] = None,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        admin_key: Optional[str] = None,
    ) -> None:
        super().__init__(base_url, private_key, timeout, admin_key)
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

    def _post(self, path: str, body: dict, *, extra_headers: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.post(
            path, json=body, headers=extra_headers or {}, timeout=self._timeout
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return resp.json()

    def _patch(self, path: str, body: dict, *, extra_headers: dict | None = None) -> dict:
        url = self._url(path)
        resp = self._client.patch(
            path, json=body, headers=extra_headers or {}, timeout=self._timeout
        )
        self._raise_for_status("PATCH", url, resp.status_code, resp.text)
        return resp.json()

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

    def get_system_status(self) -> HealthResponse:
        """GET /api/v1/system/status — includes paused flag and check results.

        Does NOT raise on HTTP 503.  A 503 from this endpoint means the
        storefront is degraded but still returns a structured HealthResponse.
        Only unexpected status codes (4xx, non-503 5xx) raise StorefrontClientError.
        """
        url = self._url("/api/v1/system/status")
        resp = self._client.get(
            "/api/v1/system/status", timeout=self._timeout,
            headers=self._admin_headers(),
        )
        if resp.status_code not in (200, 503):
            self._raise_for_status("GET", url, resp.status_code, resp.text)
        return HealthResponse.from_dict(resp.json())

    def wait_for_registry_agent_ready(
        self,
        *,
        timeout: float = 90.0,
    ) -> RegistryAgentReadyResponse:
        """GET /api/v1/system/wait-for-registry-agent — long-poll (admin).

        Single server-side long-poll: the storefront blocks internally until
        ``registry_auth_check()`` returns a definitive result (anything other
        than ``"agent_not_found"``), or until *timeout* seconds elapse.

        Returns ``RegistryAgentReadyResponse``.  Callers must check
        ``result.ready`` and ``result.registry_auth``:
        - ``ready=True, registry_auth="ok"`` — agent indexed and owner verified
        - ``ready=True, registry_auth=<other>`` — definitive but non-ok (e.g.
          ``"owner_mismatch"``, ``"unconfigured"``)
        - ``ready=False`` — timed out while still ``"agent_not_found"``

        Raises ``StorefrontClientError`` on non-2xx responses.
        """
        url = self._url("/api/v1/system/wait-for-registry-agent")
        resp = self._client.get(
            "/api/v1/system/wait-for-registry-agent",
            params={"timeout": timeout},
            headers=self._admin_headers(),
            timeout=timeout + 10.0,  # client timeout slightly longer than server cap
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return RegistryAgentReadyResponse.from_dict(resp.json())

    def get_events(
        self,
        *,
        since_id: int = 0,
        limit: int = 100,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
    ) -> StageEventListResponse:
        """GET /api/v1/system/events — historical query (admin key required)."""
        params: dict[str, Any] = {"since_id": since_id, "limit": limit}
        if stage is not None:
            params["stage"] = stage
        if listing_id is not None:
            params["listing_id"] = listing_id
        if negotiation_id is not None:
            params["negotiation_id"] = negotiation_id
        url = self._url("/api/v1/system/events")
        resp = self._client.get(
            "/api/v1/system/events",
            params=params,
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return StageEventListResponse.from_dict(resp.json())

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
            status=status, paused=paused, limit=limit, offset=offset,
        )
        return ListingListResponse.from_dict(
            self._get("/api/v1/listings", params=params)
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        """GET /api/v1/listings/{listing_id}"""
        return ListingSummary.from_dict(self._get(f"/api/v1/listings/{listing_id}"))

    def pause_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/pause  (admin key required)"""
        return ListingPauseResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/pause",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    def resume_listing(self, listing_id: str) -> ListingPauseResponse:
        """POST /api/v1/listings/{listing_id}/resume  (admin key required)"""
        return ListingPauseResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/resume",
                {},
                extra_headers=self._admin_headers(),
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
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> NegotiationListResponse:
        """GET /api/v1/listings/{listing_id}/negotiations"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if terminal_state is not None:
            params["terminal_state"] = terminal_state
        if buyer_address is not None:
            params["buyer_address"] = buyer_address
        return NegotiationListResponse.from_dict(
            self._get(f"/api/v1/listings/{listing_id}/negotiations", params=params)
        )

    def get_negotiation(self, listing_id: str, neg_id: str) -> NegotiationDetail:
        """GET /api/v1/listings/{listing_id}/negotiations/{neg_id}"""
        return NegotiationDetail.from_dict(
            self._get(f"/api/v1/listings/{listing_id}/negotiations/{neg_id}")
        )

    def advance_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        action: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> NegotiationActionResponse:
        """POST .../advance  (admin key required)"""
        body: dict[str, Any] = {"action": action}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return NegotiationActionResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                body,
                extra_headers=self._admin_headers(),
            )
        )

    def force_accept_negotiation(
        self,
        listing_id: str,
        neg_id: str,
        *,
        amount: int,
    ) -> NegotiationActionResponse:
        """POST .../force-accept  (admin key required)"""
        return NegotiationActionResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                {"amount": int(amount)},
                extra_headers=self._admin_headers(),
            )
        )

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    def admin_pause(self) -> AdminPauseResponse:
        """POST /admin/pause  (admin key required)"""
        return AdminPauseResponse.from_dict(
            self._post("/api/v1/admin/pause", {}, extra_headers=self._admin_headers())
        )

    def admin_resume(self) -> AdminPauseResponse:
        """POST /admin/resume  (admin key required)"""
        return AdminPauseResponse.from_dict(
            self._post("/api/v1/admin/resume", {}, extra_headers=self._admin_headers())
        )

    def admin_import_resources(
        self, csv_content: bytes, filename: str = "resources.csv"
    ) -> ImportResourcesResponse:
        """POST /admin/portfolio/resources/import  (admin key required).

        Upload a compute resource CSV to bulk-upsert portfolio rows. Always
        upserts regardless of current table state — use to force a clobber
        of the current inventory without restarting the pod.

        ``csv_content`` is the raw bytes of the CSV file. Typically read
        with ``Path(...).read_bytes()`` or ``open(..., "rb").read()``.
        """
        url = self._url("/api/v1/admin/portfolio/resources/import")
        resp = self._client.post(
            "/api/v1/admin/portfolio/resources/import",
            files={"file": (filename, csv_content, "text/csv")},
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("POST", url, resp.status_code, resp.text)
        return ImportResourcesResponse.from_dict(resp.json())

    def admin_release_reservations(self) -> "ReleaseReservationsResponse":
        """POST /admin/portfolio/release-reservations  (admin key required).

        Forces every ``reserved`` compute resource back to ``available``.
        Sledgehammer — prefer ``admin_release_one_reservation(resource_id)``
        for production operator workflows. This bulk variant is mainly for
        e2e teardown between back-to-back runs against the same stack
        (mocked provisioning never expires leases).
        """
        return ReleaseReservationsResponse.from_dict(
            self._post(
                "/api/v1/admin/portfolio/release-reservations",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    def admin_release_one_reservation(
        self, resource_id: str
    ) -> "ReleaseReservationsResponse":
        """POST /admin/portfolio/resources/{resource_id}/release-reservation
        (admin key required).

        Surgical: releases exactly the named reserved resource. Idempotent
        on already-available rows (returns released_count=0 instead of
        erroring). 404 if the row doesn't exist.

        For an actually-stuck VM, pair this with provisioning's
        ``POST /api/v1/hosts/{host}/vms/{vm_name}/destroy`` — that operation
        runs real Ansible against the host, while this endpoint only clears
        the storefront's own bookkeeping.
        """
        return ReleaseReservationsResponse.from_dict(
            self._post(
                f"/api/v1/admin/portfolio/resources/{resource_id}/release-reservation",
                {},
                extra_headers=self._admin_headers(),
            )
        )

    def get_resource(self, resource_id: str) -> dict:
        """GET /api/v1/admin/portfolio/resources/{resource_id}  (admin key required).

        Returns the current state of the resource row — same shape as patch_resource.
        404 if the resource_id does not exist.
        """
        url = self._url(f"/api/v1/admin/portfolio/resources/{resource_id}")
        resp = self._client.get(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            headers=self._admin_headers(),
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return resp.json()

    def patch_resource(
        self,
        resource_id: str,
        *,
        state: "str | None" = None,
        attributes: "dict | None" = None,
    ) -> dict:
        """PATCH /api/v1/admin/portfolio/resources/{resource_id}  (admin key required).

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
        return self._patch(
            f"/api/v1/admin/portfolio/resources/{resource_id}",
            body,
            extra_headers=self._admin_headers(),
        )

    def evaluate_negotiate(
        self,
        listing_id: str,
        *,
        proposal: dict[str, Any],
        requested_duration_seconds: int | None = None,
        buyer_address: str = "",
    ) -> EvaluateNegotiateResponse:
        """POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate — dry-run (admin key).

        Runs the configured negotiation strategy against a synthetic buyer
        proposal without creating a negotiation thread or writing to the
        database. ``proposal`` is the full EscrowProposal-shaped dict (with
        ``fields["amount"]`` carrying the absolute opening amount in base
        units). Returns ``EvaluateNegotiateResponse.would_negotiate=False``
        when the strategy would exit immediately.
        """
        body: dict[str, Any] = {"proposal": proposal, "buyer_address": buyer_address}
        if requested_duration_seconds is not None:
            body["requested_duration_seconds"] = int(requested_duration_seconds)
        return EvaluateNegotiateResponse.from_dict(
            self._post(
                f"/api/v1/admin/listings/{listing_id}/evaluate-negotiate", body,
                extra_headers=self._admin_headers(),
            )
        )



    def get_registration(self) -> ERC8004RegistrationFile:
        """GET /.well-known/erc-8004-registration.json"""
        return ERC8004RegistrationFile.from_dict(
            self._get("/.well-known/erc-8004-registration.json")
        )

    def create_listing(
        self,
        *,
        agent_wallet_address: str,
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        max_duration_seconds: int | None = None,
        paused: bool = False,
    ) -> StorefrontListingCreateResponse:
        """POST /listings/create.

        ``accepted_escrows`` lists the escrow shapes the seller will accept
        for this listing. Each entry pins ``(chain_name, escrow_address)``
        plus a partial ``ObligationData`` advertisement via the ``fields``
        map, with the per-hour rate in ``price_per_hour``.

        ``max_duration_seconds`` is the optional ceiling on lease duration
        (None = unlimited). Buyers supply the actual duration at
        negotiation init time; total payment is computed at agreement as
        ``price_per_hour × agreed_duration_seconds / 3600``. Pass
        ``paused=True`` to create the listing in local SQLite without
        publishing to the registry; call ``resume_listing`` to publish.
        """
        headers = self._auth_headers("create_listing", agent_wallet_address)
        body = {
            "offer": offer,
            "accepted_escrows": accepted_escrows,
            "max_duration_seconds": max_duration_seconds,
            "paused": paused,
        }
        return StorefrontListingCreateResponse.from_dict(
            self._post("/api/v1/listings/create", body, extra_headers=headers)
        )

    def close_listing(self, listing_id: str) -> StorefrontListingCloseResponse:
        """POST /listings/close"""
        headers = self._auth_headers("close_listing", listing_id)
        return StorefrontListingCloseResponse.from_dict(
            self._post("/listings/close", {"listing_id": listing_id}, extra_headers=headers)
        )

    def refund_listing(
        self,
        *,
        listing_id: str,
        buyer_address: str | None = None,
        amount: str | None = None,
        token: str | None = None,
    ) -> StorefrontListingRefundResponse:
        """POST /api/v1/listings/{listing_id}/refund

        ``buyer_address`` is optional; the storefront resolves it from the
        listing's recorded buyer when omitted.
        """
        headers = self._auth_headers("refund_listing", listing_id)
        body: dict[str, Any] = {}
        if buyer_address is not None:
            body["buyer_address"] = buyer_address
        if amount is not None:
            body["amount"] = amount
        if token is not None:
            body["token"] = token
        return StorefrontListingRefundResponse.from_dict(
            self._post(
                f"/api/v1/listings/{listing_id}/refund",
                body, extra_headers=headers,
            )
        )

    def claim_listing(
        self,
        *,
        listing_id: str,
        fulfillment_uid: str | None = None,
    ) -> StorefrontListingClaimResponse:
        """POST /listings/claim"""
        headers = self._auth_headers("claim_listing", listing_id)
        body: dict[str, Any] = {"listing_id": listing_id}
        if fulfillment_uid:
            body["fulfillment_uid"] = fulfillment_uid
        return StorefrontListingClaimResponse.from_dict(
            self._post("/listings/claim", body, extra_headers=headers)
        )

    # ------------------------------------------------------------------
    # Buyer protocol — negotiate / settle
    # EIP-191 signed X-Signature + X-Timestamp headers are added automatically.
    # ------------------------------------------------------------------

    def negotiate_new(
        self,
        *,
        listing_id: str,
        buyer_address: str,
        initial_amount: int,
        duration_seconds: int,
        buyer_agent_url: str = "",
        ssh_public_key: str = "",
        token: str = "",
        chain_name: str = "",
        escrow_address: str = "",
        escrow_expiration_unix: int | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/new — adds EIP-191 auth headers automatically.

        ``provision_terms`` and ``proposal`` are required by the wire
        protocol; this helper builds canonical defaults from the scalar
        args. ``initial_amount`` is the absolute opening amount in base
        units of the payment token.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"negotiate_new:{listing_id}",
            identity_identifier=buyer_address,
        )
        exp_unix = escrow_expiration_unix or (int(time.time()) + 3600)
        body = {
            "listing_id": listing_id,
            "buyer_address": buyer_address,
            "provision_terms": {
                "duration_seconds": duration_seconds,
                "ssh_public_key": ssh_public_key,
                "compute_resource": None,
            },
            "proposal": {
                "chain_name": chain_name or "anvil",
                "escrow_address": escrow_address or ("0x" + "0" * 40),
                "fields": {
                    "amount": int(initial_amount),
                    "token": token or ("0x" + "0" * 40),
                },
                "expiration_unix": exp_unix,
            },
            "buyer_agent_url": buyer_agent_url,
        }
        return self._post(
            "/api/v1/negotiate/new", body, extra_headers=headers,
        )

    def negotiate_continue(
        self,
        neg_id: str,
        *,
        action: str,
        buyer_address: str,
        proposal: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> dict:
        """POST /api/v1/negotiate/{neg_id}.

        ``proposal`` is the full EscrowProposal-shaped dict for ``counter``;
        omitted for ``accept`` / ``exit``. ``fields["amount"]`` carries the
        buyer's absolute new offer in base units.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"negotiate_continue:{neg_id}",
            identity_identifier=buyer_address,
        )
        body: dict = {"action": action, "buyer_address": buyer_address}
        if proposal is not None:
            body["proposal"] = proposal
        if reason is not None:
            body["reason"] = reason
        return self._post(
            f"/api/v1/negotiate/{neg_id}", body, extra_headers=headers,
        )

    def settle(
        self,
        escrow_uid: str,
        *,
        negotiation_id: str,
        buyer_address: str,
        ssh_public_key: str = "",
        chain_name: str = "anvil",
    ) -> SettleResponse:
        """POST /api/v1/settle/{escrow_uid} — adds EIP-191 auth headers automatically.

        ``chain_name`` tells the seller which configured ``[chains.<name>]``
        entry to dispatch the on-chain verify against. Defaults to ``"anvil"``
        for compatibility with the e2e fixture; non-anvil consumers must
        pass their own value.
        """
        headers = _signed_request_headers(
            self._private_key,
            f"settle_escrow:{escrow_uid}",
            identity_identifier=buyer_address,
        )
        body: dict = {
            "negotiation_id": negotiation_id,
            "buyer_address": buyer_address,
            "chain_name": chain_name,
        }
        if ssh_public_key:
            body["ssh_public_key"] = ssh_public_key
        return SettleResponse.from_dict(
            self._post(
                f"/api/v1/settle/{escrow_uid}", body, extra_headers=headers,
            )
        )

    def get_settle_status(
        self,
        escrow_uid: str,
        *,
        buyer_address: str,
    ) -> SettleStatusResponse:
        """GET /api/v1/settle/{escrow_uid}/status — adds EIP-191 auth headers automatically."""
        headers = _signed_request_headers(
            self._private_key,
            f"settle_status:{escrow_uid}",
            identity_identifier=buyer_address,
        )
        url = self._url(f"/api/v1/settle/{escrow_uid}/status")
        resp = self._client.get(
            f"/api/v1/settle/{escrow_uid}/status",
            params={"buyer_address": buyer_address},
            headers=headers,
            timeout=self._timeout,
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return SettleStatusResponse.from_dict(resp.json())

    def wait_for_settlement(
        self,
        escrow_uid: str,
        *,
        timeout: float = 60.0,
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
        url = self._url(f"/api/v1/admin/settle/{escrow_uid}/wait")
        resp = self._client.get(
            f"/api/v1/admin/settle/{escrow_uid}/wait",
            params={"timeout": timeout},
            headers=self._admin_headers(),
            timeout=timeout + 10.0,  # client timeout slightly longer than server cap
        )
        self._raise_for_status("GET", url, resp.status_code, resp.text)
        return SettleWaitResponse.from_dict(resp.json())

    def verify_settle(
        self,
        escrow_uid: str,
        *,
        seller_wallet: str,
        agreed_price: float,
        agreed_duration_seconds: int,
        listing_id: str,
        chain_name: str = "anvil",
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/verify — dry-run escrow chain read (admin key).

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
        return self._post(
            f"/api/v1/admin/settle/{escrow_uid}/verify", body,
            extra_headers=self._admin_headers(),
        )

    def evaluate_settle(
        self,
        escrow_uid: str,
        *,
        listing_id: str,
        ssh_public_key: str = "",
        duration_seconds: int = 3600,
    ) -> dict:
        """POST /api/v1/admin/settle/{escrow_uid}/evaluate — dry-run provisioning job spec (admin key).

        Resolves a host from inventory and builds the job spec without chain reads,
        DB writes, or provisioning calls. Returns dict with would_submit, vm_host,
        vm_target, required_attributes. Used by e2e stage 8a.
        """
        body = {
            "listing_id": listing_id,
            "ssh_public_key": ssh_public_key,
            "duration_seconds": duration_seconds,
        }
        return self._post(
            f"/api/v1/admin/settle/{escrow_uid}/evaluate", body,
            extra_headers=self._admin_headers(),
        )

