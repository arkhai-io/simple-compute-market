"""Synchronous and asynchronous HTTP clients for the registry API.

Every request is signed under the version 3 profile, naming the configured
registries as its audience, and every answer is verified against the request it
answers and those registries before it is read (:mod:`registry_client.auth`).
The descriptor read is a public operation: its request carries only a request
identity, and its answer is verified against the configured registries, or, by a
client bootstrapping a registry from its URL, against the principals the
descriptor itself names.
"""

from __future__ import annotations

import json
import urllib.parse
import uuid
from typing import Any, Optional, cast

import httpx
import injected_time
from market_identity import (
    Identity,
    RequestBinding,
    RotationIntent,
    Signer,
    TrustedIdentitySet,
    build_public_request,
    sign_rotation,
)
from market_core import RegistryDescriptor

from registry_client.auth import (
    DESCRIPTOR_OPERATION,
    DESCRIPTOR_PATH,
    RegistryClientError,
    SignedRegistryRequest,
    sign_registry_request,
    verify_registry_response,
)
from registry_client.models import (
    AdminStatusResponse,
    FilterSpecResponse,
    HealthResponse,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    Publisher,
    PublisherListResponse,
    SystemStatsResponse,
    TimeSettingResponse,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
)

#: The listing read's query parameter naming the filter-spec ETag its filters
#: were compiled under; the request's signature covers it.
FILTER_SPEC_ETAG_PARAM = "filter_spec_etag"

Query = list[tuple[str, str]]


def _admin_headers(admin_key: str) -> dict[str, str]:
    """The administrator bearer key the registry's ``/admin`` routes require,
    in place of any read or write key the client carries."""
    return {"Authorization": f"Bearer {admin_key}"}


def _admin_answer(response: httpx.Response) -> Any:
    """An ``/admin`` route's answer, which the registry returns unsigned, as a
    bearer-authenticated route; a non-2xx status raises."""
    if not response.is_success:
        raise RegistryClientError(
            response.request.method,
            str(response.request.url),
            response.status_code,
            response.text,
        )
    return response.json()


def _json_body(value: Any) -> bytes:
    return b"" if value is None else json.dumps(value, separators=(",", ":")).encode("utf-8")


def _query(params: dict[str, Any]) -> Query:
    return [(key, str(value)) for key, value in params.items()]


class _RegistryClientBase:
    """Route construction, authentication, and parsing shared by both clients."""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        signer: Signer,
        caller_role: str,
        expected_registries: TrustedIdentitySet,
        registry_authority: str,
    ) -> None:
        if caller_role not in {"buyer", "seller", "service"}:
            raise ValueError("caller_role must be buyer, seller, or service")
        if not registry_authority:
            raise ValueError("registry_authority is required")
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._signer = signer
        self._caller_role = caller_role
        self._expected_registries = expected_registries
        self._registry_authority = registry_authority

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def _sign(
        self,
        method: str,
        path: str,
        *,
        query: Query | None = None,
        body: bytes = b"",
        request_id: str | None = None,
        origin: int | None = None,
    ) -> SignedRegistryRequest:
        return sign_registry_request(
            signer=self._signer,
            role=self._caller_role,
            method=method,
            path=path,
            body=body,
            audience=self._expected_registries,
            query=query or (),
            request_id=request_id,
            origin=origin,
        )

    def _answer(
        self,
        method: str,
        response: httpx.Response,
        binding: RequestBinding,
        expected: tuple[int, ...],
        *,
        expected_registries: TrustedIdentitySet | None = None,
    ) -> Any:
        url = str(response.request.url)
        try:
            verify_registry_response(
                status=response.status_code,
                headers=response.headers,
                body=response.content,
                binding=binding,
                expected_registries=(
                    self._expected_registries if expected_registries is None else expected_registries
                ),
            )
        except ValueError as exc:
            raise RegistryClientError(method, url, 502, str(exc)) from exc
        if response.status_code not in expected:
            raise RegistryClientError(method, url, response.status_code, response.text)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RegistryClientError(method, url, 502, "registry response is not JSON") from exc

    @staticmethod
    def _listings_query(
        *,
        status: str | None,
        publisher: Identity | None,
        limit: int,
        offset: int,
        etag: str | None,
        filters: dict[str, Any],
    ) -> Query:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if publisher is not None:
            params["publisher_scheme"] = publisher.scheme.value
            params["publisher_identifier"] = publisher.identifier
        if etag is not None:
            params[FILTER_SPEC_ETAG_PARAM] = etag.strip().removeprefix("W/").strip().strip('"')
        for key, value in filters.items():
            if value is not None:
                params[key] = str(value).lower() if isinstance(value, bool) else value
        return _query(params)

    @staticmethod
    def _publishers_query(principal: Identity | None, limit: int, offset: int) -> Query:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if principal is not None:
            params.update(scheme=principal.scheme.value, identifier=principal.identifier)
        return _query(params)

    @staticmethod
    def _bootstrap_target(base_url: str, *, allow_insecure_http: bool) -> str:
        """The bootstrapped registry's base URL, refused before any request when
        its scheme is not ``https`` and the caller has not opted into plain HTTP."""

        scheme = urllib.parse.urlsplit(base_url).scheme
        if scheme != "https" and not (scheme == "http" and allow_insecure_http):
            raise ValueError(
                f"a registry is bootstrapped over https, not {scheme or 'no scheme'}; "
                "pass allow_insecure_http=True only for a local or test registry"
            )
        return base_url.rstrip("/")

    @staticmethod
    def _bootstrapped_descriptor(response: httpx.Response, binding: RequestBinding, base_url: str) -> RegistryDescriptor:
        """The descriptor a bootstrap read, once its answer verifies against the
        principals it names, bound to the bootstrap's own request, and it names
        the URL it was read from as its base URL."""

        url = f"{base_url}{DESCRIPTOR_PATH}"
        if response.status_code != 200:
            raise RegistryClientError("GET", url, response.status_code, response.text)
        try:
            descriptor = RegistryDescriptor.model_validate(response.json())
        except ValueError as exc:
            raise RegistryClientError("GET", url, 502, "registry descriptor is not canonical JSON") from exc
        principals = TrustedIdentitySet(
            identities=tuple(
                Identity.model_validate(principal.model_dump(mode="json"))
                for principal in descriptor.authority.principals
            )
        )
        try:
            verify_registry_response(
                status=response.status_code,
                headers=response.headers,
                body=response.content,
                binding=binding,
                expected_registries=principals,
            )
        except ValueError as exc:
            raise RegistryClientError("GET", url, 502, str(exc)) from exc
        if descriptor.base_url.rstrip("/") != base_url:
            raise RegistryClientError(
                "GET",
                url,
                502,
                f"registry descriptor names base URL {descriptor.base_url}, not {base_url}",
            )
        return descriptor

    def _rotation_body(
        self,
        publisher_id: int,
        replacement_signer: Signer,
        *,
        nonce: str | None,
        overlap_seconds: int,
        expires_at: int | None,
    ) -> dict[str, Any]:
        intent = RotationIntent(
            current=self._signer.identity,
            replacement=replacement_signer.identity,
            subject=f"publisher:{publisher_id}",
            authority=self._registry_authority,
            nonce=nonce or uuid.uuid4().hex,
            overlap_seconds=overlap_seconds,
            expires_at=(expires_at if expires_at is not None else injected_time.now() + 300),
        )
        rotation = sign_rotation(
            current_signer=self._signer,
            replacement_signer=replacement_signer,
            intent=intent,
        )
        return rotation.model_dump(mode="json")

    @staticmethod
    def _parse_listing(data: Any) -> ListingSummary:
        return ListingSummary.from_dict(data.get("listing", data) if isinstance(data, dict) else data)


class RegistryClient(_RegistryClientBase):
    """Asynchronous authenticated client pinned to one registry authority."""

    def __init__(
        self,
        base_url: str,
        *,
        signer: Signer,
        caller_role: str,
        expected_registries: TrustedIdentitySet,
        registry_authority: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url,
            timeout,
            signer,
            caller_role,
            expected_registries,
            registry_authority,
        )
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers=headers,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RegistryClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @classmethod
    async def bootstrap_registry_descriptor(
        cls,
        base_url: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> RegistryDescriptor:
        """Read a registry's descriptor knowing no registry principal, and verify
        that whoever answered holds a key the descriptor names.

        The request is the descriptor's public operation, under a fresh request
        ID, so its signed answer binds this request and no replay of an older
        one. The URL must be ``https``, whose certificate checking proves the
        host, unless ``allow_insecure_http`` opts into plain HTTP for a local or
        test registry; a URL of any other scheme is refused before any request
        is sent. A descriptor naming another base URL than ``base_url`` is
        refused. The proof establishes possession of the key, not a third
        party's endorsement of the operator or the URL.
        """

        target = cls._bootstrap_target(base_url, allow_insecure_http=allow_insecure_http)
        public = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
        async with httpx.AsyncClient(
            base_url=target,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            response = await client.get(DESCRIPTOR_PATH, headers=public.headers)
        return cls._bootstrapped_descriptor(response, public.binding, target)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        query: Query | None = None,
        json: Any = None,
        request_id: str | None = None,
        origin: int | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        body = _json_body(json)
        signed = self._sign(method, path, query=query, body=body, request_id=request_id, origin=origin)
        response = await self._client.request(method, signed.target, content=body, headers=signed.headers)
        return self._answer(method, response, signed.binding, expected)

    async def get_health(self) -> HealthResponse:
        return HealthResponse.from_dict(await self._send("GET", "/api/v1/system/health"))

    async def get_admin_status(self, *, admin_key: str) -> AdminStatusResponse:
        """GET /admin/status with the administrator key: the registry's time source."""
        response = await self._client.get(
            self._url("/admin/status"), headers=_admin_headers(admin_key)
        )
        return AdminStatusResponse.from_dict(_admin_answer(response))

    async def set_time(self, now: int, *, admin_key: str) -> TimeSettingResponse:
        """POST /admin/time with the administrator key: set an injected registry
        to ``now``, in Unix seconds, sent as given.

        The registry refuses anything but an integer instant (422
        ``invalid_time``) and an instant earlier than its own (409
        ``time_moves_forward``), raised as :class:`RegistryClientError`; a
        wall-time registry serves no such route (404).
        """
        response = await self._client.post(
            self._url("/admin/time"), json={"now": now}, headers=_admin_headers(admin_key)
        )
        return TimeSettingResponse.from_dict(_admin_answer(response))

    async def get_system_stats(self) -> SystemStatsResponse:
        return SystemStatsResponse.from_dict(await self._send("GET", "/api/v1/system/stats"))

    async def list_publishers(
        self,
        *,
        principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        return PublisherListResponse.from_raw(
            await self._send("GET", "/publishers", query=self._publishers_query(principal, limit, offset))
        )

    async def get_publisher(self, publisher_id: int) -> Publisher:
        return Publisher.from_dict(await self._send("GET", f"/publishers/{publisher_id}"))

    async def publish_listing(
        self,
        listing: ListingRequest,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        """Publish ``listing``. An exact retry of a publication whose answer was
        lost passes the ``request_id`` and ``origin`` of the first attempt, and
        is answered with its recorded outcome."""
        return cast(
            dict[str, Any],
            await self._send(
                "POST",
                "/listings",
                json=listing.to_dict(),
                request_id=request_id,
                origin=origin,
                expected=(201,),
            ),
        )

    async def validate_publish_listing(
        self,
        request: ValidatePublishRequest,
    ) -> ValidatePublishResponse:
        data = await self._send(
            "POST",
            "/api/v1/listings/validate-publish",
            json=request.to_dict(),
            expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    async def get_filter_spec(self) -> FilterSpecResponse:
        return FilterSpecResponse.from_dict(await self._send("GET", "/filter-spec"))

    async def get_registry_descriptor(self) -> RegistryDescriptor:
        """The registry's descriptor, read as its public operation and verified
        against the configured registries."""
        public = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
        response = await self._client.get(DESCRIPTOR_PATH, headers=public.headers)
        return RegistryDescriptor.model_validate(self._answer("GET", response, public.binding, (200,)))

    async def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        publisher: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """List listings. ``etag`` is the filter-spec ETag the filters were
        compiled under, sent as the ``filter_spec_etag`` query parameter; the
        registry answers a stale one with 412."""
        query = self._listings_query(
            status=status,
            publisher=publisher,
            limit=limit,
            offset=offset,
            etag=etag,
            filters=filters,
        )
        return ListingListResponse.from_raw(await self._send("GET", "/listings", query=query))

    async def list_listings_for_publisher(
        self,
        principal: Identity,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        return await self.list_listings(
            status=status,
            publisher=principal,
            limit=limit,
            offset=offset,
        )

    async def get_listing(self, listing_id: str) -> ListingSummary:
        return self._parse_listing(await self._send("GET", f"/listings/{listing_id}"))

    async def update_listing(
        self,
        listing_id: str,
        request: UpdateListingRequest,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._send(
                "PUT",
                f"/listings/{listing_id}",
                json=request.to_dict(),
                request_id=request_id,
                origin=origin,
            ),
        )

    async def delete_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> None:
        await self._send(
            "DELETE",
            f"/listings/{listing_id}",
            request_id=request_id,
            origin=origin,
            expected=(204,),
        )

    async def rotate_publisher_identity(
        self,
        publisher_id: int,
        replacement_signer: Signer,
        *,
        nonce: str | None = None,
        overlap_seconds: int = 300,
        expires_at: int | None = None,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        """Rotate the publisher to ``replacement_signer``'s principal.

        Both schemes sign deterministically, so an exact retry passes the first
        attempt's ``nonce`` and ``expires_at``, which make the same signed
        intent, with its ``request_id`` and ``origin``."""
        rotation = self._rotation_body(
            publisher_id,
            replacement_signer,
            nonce=nonce,
            overlap_seconds=overlap_seconds,
            expires_at=expires_at,
        )
        return cast(
            dict[str, Any],
            await self._send(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations",
                json=rotation,
                request_id=request_id,
                origin=origin,
            ),
        )

    async def get_publisher_rotation(
        self,
        publisher_id: int,
        nonce: str,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._send("GET", f"/publishers/{publisher_id}/identity-rotations/{nonce}"),
        )

    async def retire_publisher_identity(
        self,
        publisher_id: int,
        nonce: str,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._send(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
                request_id=request_id,
                origin=origin,
            ),
        )


class SyncRegistryClient(_RegistryClientBase):
    """Synchronous registry client with the same contract as RegistryClient."""

    def __init__(
        self,
        base_url: str,
        *,
        signer: Signer,
        caller_role: str,
        expected_registries: TrustedIdentitySet,
        registry_authority: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url,
            timeout,
            signer,
            caller_role,
            expected_registries,
            registry_authority,
        )
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=self._base,
            timeout=timeout,
            transport=transport,
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SyncRegistryClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @classmethod
    def bootstrap_registry_descriptor(
        cls,
        base_url: str,
        *,
        allow_insecure_http: bool = False,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> RegistryDescriptor:
        """Read a registry's descriptor knowing no registry principal, and verify
        that whoever answered holds a key the descriptor names.

        The request is the descriptor's public operation, under a fresh request
        ID, so its signed answer binds this request and no replay of an older
        one. The URL must be ``https``, whose certificate checking proves the
        host, unless ``allow_insecure_http`` opts into plain HTTP for a local or
        test registry; a URL of any other scheme is refused before any request
        is sent. A descriptor naming another base URL than ``base_url`` is
        refused. The proof establishes possession of the key, not a third
        party's endorsement of the operator or the URL.
        """

        target = cls._bootstrap_target(base_url, allow_insecure_http=allow_insecure_http)
        public = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
        with httpx.Client(
            base_url=target,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            response = client.get(DESCRIPTOR_PATH, headers=public.headers)
        return cls._bootstrapped_descriptor(response, public.binding, target)

    def _send(
        self,
        method: str,
        path: str,
        *,
        query: Query | None = None,
        json: Any = None,
        request_id: str | None = None,
        origin: int | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        body = _json_body(json)
        signed = self._sign(method, path, query=query, body=body, request_id=request_id, origin=origin)
        response = self._client.request(method, signed.target, content=body, headers=signed.headers)
        return self._answer(method, response, signed.binding, expected)

    def get_health(self) -> HealthResponse:
        return HealthResponse.from_dict(self._send("GET", "/api/v1/system/health"))

    def get_admin_status(self, *, admin_key: str) -> AdminStatusResponse:
        """GET /admin/status with the administrator key: the registry's time source."""
        response = self._client.get(
            self._url("/admin/status"), headers=_admin_headers(admin_key)
        )
        return AdminStatusResponse.from_dict(_admin_answer(response))

    def set_time(self, now: int, *, admin_key: str) -> TimeSettingResponse:
        """POST /admin/time with the administrator key: set an injected registry
        to ``now``, in Unix seconds, sent as given.

        The registry refuses anything but an integer instant (422
        ``invalid_time``) and an instant earlier than its own (409
        ``time_moves_forward``), raised as :class:`RegistryClientError`; a
        wall-time registry serves no such route (404).
        """
        response = self._client.post(
            self._url("/admin/time"), json={"now": now}, headers=_admin_headers(admin_key)
        )
        return TimeSettingResponse.from_dict(_admin_answer(response))

    def get_system_stats(self) -> SystemStatsResponse:
        return SystemStatsResponse.from_dict(self._send("GET", "/api/v1/system/stats"))

    def list_publishers(
        self,
        *,
        principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        return PublisherListResponse.from_raw(
            self._send("GET", "/publishers", query=self._publishers_query(principal, limit, offset))
        )

    def get_publisher(self, publisher_id: int) -> Publisher:
        return Publisher.from_dict(self._send("GET", f"/publishers/{publisher_id}"))

    def publish_listing(
        self,
        listing: ListingRequest,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        """Publish ``listing``. An exact retry of a publication whose answer was
        lost passes the ``request_id`` and ``origin`` of the first attempt, and
        is answered with its recorded outcome."""
        return cast(
            dict[str, Any],
            self._send(
                "POST",
                "/listings",
                json=listing.to_dict(),
                request_id=request_id,
                origin=origin,
                expected=(201,),
            ),
        )

    def validate_publish_listing(
        self,
        request: ValidatePublishRequest,
    ) -> ValidatePublishResponse:
        data = self._send(
            "POST",
            "/api/v1/listings/validate-publish",
            json=request.to_dict(),
            expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    def get_filter_spec(self) -> FilterSpecResponse:
        return FilterSpecResponse.from_dict(self._send("GET", "/filter-spec"))

    def get_registry_descriptor(self) -> RegistryDescriptor:
        """The registry's descriptor, read as its public operation and verified
        against the configured registries."""
        public = build_public_request(method="GET", operation=DESCRIPTOR_OPERATION)
        response = self._client.get(DESCRIPTOR_PATH, headers=public.headers)
        return RegistryDescriptor.model_validate(self._answer("GET", response, public.binding, (200,)))

    def list_listings(
        self,
        *,
        status: Optional[str] = "open",
        publisher: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
        etag: str | None = None,
        **filters: Any,
    ) -> ListingListResponse:
        """List listings. ``etag`` is the filter-spec ETag the filters were
        compiled under, sent as the ``filter_spec_etag`` query parameter; the
        registry answers a stale one with 412."""
        query = self._listings_query(
            status=status,
            publisher=publisher,
            limit=limit,
            offset=offset,
            etag=etag,
            filters=filters,
        )
        return ListingListResponse.from_raw(self._send("GET", "/listings", query=query))

    def list_listings_for_publisher(
        self,
        principal: Identity,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListingListResponse:
        return self.list_listings(
            status=status,
            publisher=principal,
            limit=limit,
            offset=offset,
        )

    def get_listing(self, listing_id: str) -> ListingSummary:
        return self._parse_listing(self._send("GET", f"/listings/{listing_id}"))

    def update_listing(
        self,
        listing_id: str,
        request: UpdateListingRequest,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._send(
                "PUT",
                f"/listings/{listing_id}",
                json=request.to_dict(),
                request_id=request_id,
                origin=origin,
            ),
        )

    def delete_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> None:
        self._send(
            "DELETE",
            f"/listings/{listing_id}",
            request_id=request_id,
            origin=origin,
            expected=(204,),
        )

    def rotate_publisher_identity(
        self,
        publisher_id: int,
        replacement_signer: Signer,
        *,
        nonce: str | None = None,
        overlap_seconds: int = 300,
        expires_at: int | None = None,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        """Rotate the publisher to ``replacement_signer``'s principal.

        Both schemes sign deterministically, so an exact retry passes the first
        attempt's ``nonce`` and ``expires_at``, which make the same signed
        intent, with its ``request_id`` and ``origin``."""
        rotation = self._rotation_body(
            publisher_id,
            replacement_signer,
            nonce=nonce,
            overlap_seconds=overlap_seconds,
            expires_at=expires_at,
        )
        return cast(
            dict[str, Any],
            self._send(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations",
                json=rotation,
                request_id=request_id,
                origin=origin,
            ),
        )

    def get_publisher_rotation(
        self,
        publisher_id: int,
        nonce: str,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._send("GET", f"/publishers/{publisher_id}/identity-rotations/{nonce}"),
        )

    def retire_publisher_identity(
        self,
        publisher_id: int,
        nonce: str,
        *,
        request_id: str | None = None,
        origin: int | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._send(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
                request_id=request_id,
                origin=origin,
            ),
        )
