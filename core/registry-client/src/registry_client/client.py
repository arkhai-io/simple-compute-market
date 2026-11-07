"""Synchronous and asynchronous HTTP clients for the registry API."""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional, cast

import httpx
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Identity,
    RotationIntent,
    Signer,
    TrustedIdentitySet,
    sign_rotation,
)
from market_core import RegistryDescriptor

from registry_client.auth import (
    REQUEST_ID_HEADER,
    TIMESTAMP_HEADER,
    RegistryClientError,
    authenticate_request,
    authentication_headers,
    verify_authenticated_response,
)
from registry_client.models import (
    FilterSpecResponse,
    HealthResponse,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    Publisher,
    PublisherListResponse,
    SystemStatsResponse,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
)


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

    def _require_signer(self) -> Signer:
        return self._signer

    def _authenticated_headers(
        self,
        *,
        method: str,
        operation: str,
        resource: str,
        body: Any = EMPTY_BODY,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        authenticated = authenticate_request(
            signer=self._require_signer(),
            role=self._caller_role,
            method=method,
            operation=operation,
            resource=resource,
            body=body,
            request_id=request_id,
            timestamp=timestamp,
        )
        return authentication_headers(authenticated)

    @staticmethod
    def _request_context(method: str, path: str) -> tuple[str, str]:
        parts = [part for part in path.split("/") if part]
        if path == "/api/v1/system/health":
            return "health.read", "health"
        if path == "/api/v1/system/stats":
            return "system.stats.read", "system"
        if path == "/api/v1/listings/validate-publish":
            return "listing.validate", "listings"
        if path == "/filter-spec":
            return "filter.get", "filter-spec"
        if path == "/.well-known/arkhai/registry-descriptor.json":
            return "registry.descriptor.read", "registry-descriptor"
        if parts[:1] == ["listings"]:
            if len(parts) == 1:
                return (
                    "listing.publish" if method.upper() == "POST" else "listing.list",
                    "listings",
                )
            operation = {
                "GET": "listing.get",
                "PUT": "listing.update",
                "DELETE": "listing.delete",
            }[method.upper()]
            return operation, parts[1]
        if parts[:1] == ["publishers"]:
            if len(parts) == 1:
                return "publisher.list", "publishers"
            if len(parts) == 2:
                return "publisher.get", parts[1]
            if parts[2] == "identity-rotations":
                if len(parts) == 3:
                    return "publisher.identity.rotate", parts[1]
                if len(parts) == 4:
                    return "publisher.identity.rotation.read", f"{parts[1]}:{parts[3]}"
                if len(parts) == 5 and parts[4] == "retire":
                    return "publisher.identity.retire", f"{parts[1]}:{parts[3]}"
        raise ValueError(f"unsupported registry route: {method} {path}")

    @staticmethod
    def _query_body(
        params: dict | None,
        headers: dict | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": sorted(
                [list(item) for item in httpx.QueryParams(params or {}).multi_items()]
            )
        }
        if_match = httpx.Headers(headers or {}).get("If-Match")
        if if_match is not None:
            body["if_match"] = if_match.strip().removeprefix("W/").strip().strip('"')
        return body

    @staticmethod
    def _listings_params(
        *,
        status: str | None,
        publisher: Identity | None,
        limit: int,
        offset: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if publisher is not None:
            params["publisher_scheme"] = publisher.scheme.value
            params["publisher_identifier"] = publisher.identifier
        for key, value in filters.items():
            if value is not None:
                params[key] = str(value).lower() if isinstance(value, bool) else value
        return params

    @staticmethod
    def _if_match_headers(etag: str | None) -> dict[str, str] | None:
        if etag is None:
            return None
        normalized = etag if etag.startswith('"') else f'"{etag}"'
        return {"If-Match": normalized}

    @staticmethod
    def _request_identity_headers(
        request_id: str | None,
        timestamp: int | None,
    ) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if request_id is not None:
            headers[REQUEST_ID_HEADER] = request_id
        if timestamp is not None:
            headers[TIMESTAMP_HEADER] = str(timestamp)
        return headers or None

    @classmethod
    def _descriptor_bootstrap_request(
        cls,
        *,
        signer: Signer,
        caller_role: str,
    ) -> AuthenticatedRequest:
        if caller_role not in {"buyer", "seller", "service"}:
            raise ValueError("caller_role must be buyer, seller, or service")
        return authenticate_request(
            signer=signer,
            role=caller_role,
            method="GET",
            operation="registry.descriptor.read",
            resource="registry-descriptor",
            body=cls._query_body(None, None),
        )

    @staticmethod
    def _verify_bootstrap_descriptor(
        *,
        response: httpx.Response,
        request: AuthenticatedRequest,
        url: str,
    ) -> RegistryDescriptor:
        if response.status_code != 200:
            raise RegistryClientError("GET", url, response.status_code, response.text)
        try:
            descriptor = RegistryDescriptor.model_validate(response.json())
        except ValueError as exc:
            raise RegistryClientError(
                "GET",
                url,
                502,
                "registry descriptor is not canonical JSON",
            ) from exc
        expected_registries = TrustedIdentitySet(
            identities=tuple(
                Identity.model_validate(principal.model_dump(mode="json"))
                for principal in descriptor.authority.principals
            )
        )
        try:
            verify_authenticated_response(
                headers=response.headers,
                expected_registries=expected_registries,
                request=request,
                status=response.status_code,
                body=descriptor.to_wire(),
            )
        except ValueError as exc:
            raise RegistryClientError("GET", url, 502, str(exc)) from exc
        return descriptor

    def _publish_listing_request(
        self,
        listing: ListingRequest,
        *,
        request_id: str | None,
        timestamp: int | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        body = listing.to_dict()
        headers = self._authenticated_headers(
            method="POST",
            operation="listing.publish",
            resource="listings",
            body=body,
            request_id=request_id,
            timestamp=timestamp,
        )
        return body, headers

    def _update_listing_request(
        self,
        listing_id: str,
        request: UpdateListingRequest,
        *,
        request_id: str | None,
        timestamp: int | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        body = request.to_dict()
        headers = self._authenticated_headers(
            method="PUT",
            operation="listing.update",
            resource=listing_id,
            body=body,
            request_id=request_id,
            timestamp=timestamp,
        )
        return body, headers

    def _delete_listing_headers(
        self,
        listing_id: str,
        *,
        request_id: str | None,
        timestamp: int | None,
    ) -> dict[str, str]:
        return self._authenticated_headers(
            method="DELETE",
            operation="listing.delete",
            resource=listing_id,
            request_id=request_id,
            timestamp=timestamp,
        )

    def _rotation_request(
        self,
        publisher_id: int,
        replacement_signer: Signer,
        *,
        nonce: str | None,
        overlap_seconds: int,
        expires_at: int | None,
        request_id: str | None,
        timestamp: int | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        current_signer = self._require_signer()
        rotation_nonce = nonce or uuid.uuid4().hex
        intent = RotationIntent(
            current=current_signer.identity,
            replacement=replacement_signer.identity,
            subject=f"publisher:{publisher_id}",
            authority=self._registry_authority,
            nonce=rotation_nonce,
            overlap_seconds=overlap_seconds,
            expires_at=(
                expires_at if expires_at is not None else int(time.time()) + 300
            ),
        )
        rotation = sign_rotation(
            current_signer=current_signer,
            replacement_signer=replacement_signer,
            intent=intent,
        )
        body = rotation.model_dump(mode="json")
        headers = self._authenticated_headers(
            method="POST",
            operation="publisher.identity.rotate",
            resource=str(publisher_id),
            body=body,
            request_id=request_id,
            timestamp=timestamp,
        )
        return body, headers

    def _retirement_headers(
        self,
        publisher_id: int,
        nonce: str,
        *,
        request_id: str | None,
        timestamp: int | None,
    ) -> dict[str, str]:
        return self._authenticated_headers(
            method="POST",
            operation="publisher.identity.retire",
            resource=f"{publisher_id}:{nonce}",
            request_id=request_id,
            timestamp=timestamp,
        )

    @staticmethod
    def _raise_for_status(
        method: str,
        url: str,
        status: int,
        text: str,
        expected: tuple[int, ...],
    ) -> None:
        if status not in expected:
            raise RegistryClientError(method, url, status, text)

    @staticmethod
    def _parse_health(data: dict) -> HealthResponse:
        return HealthResponse.from_dict(data)

    @staticmethod
    def _parse_publisher(data: dict) -> Publisher:
        return Publisher.from_dict(data)

    @staticmethod
    def _parse_publisher_list(data: Any) -> PublisherListResponse:
        return PublisherListResponse.from_raw(data)

    @staticmethod
    def _parse_listing_list(data: Any) -> ListingListResponse:
        return ListingListResponse.from_raw(data)

    @staticmethod
    def _parse_listing(data: dict) -> ListingSummary:
        return ListingSummary.from_dict(data)

    @staticmethod
    def _parse_system_stats(data: dict) -> SystemStatsResponse:
        return SystemStatsResponse.from_dict(data)


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
        signer: Signer,
        caller_role: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> RegistryDescriptor:
        """Read a descriptor and verify possession of its advertised key."""

        path = "/.well-known/arkhai/registry-descriptor.json"
        request = cls._descriptor_bootstrap_request(
            signer=signer,
            caller_role=caller_role,
        )
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            response = await client.get(
                path,
                headers=authentication_headers(request),
            )
        return cls._verify_bootstrap_descriptor(
            response=response,
            request=request,
            url=f"{base_url.rstrip('/')}{path}",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = self._url(path)
        operation, resource = self._request_context(method, path)
        request_headers = dict(headers or {})
        request_body = (
            self._query_body(params, request_headers)
            if method.upper() == "GET"
            else (json if json is not None else EMPTY_BODY)
        )
        timestamp = request_headers.get(TIMESTAMP_HEADER)
        authenticated = authenticate_request(
            signer=self._signer,
            role=self._caller_role,
            method=method,
            operation=operation,
            resource=resource,
            body=request_body,
            request_id=request_headers.get(REQUEST_ID_HEADER),
            timestamp=int(timestamp) if timestamp is not None else None,
        )
        request_headers.update(authentication_headers(authenticated))
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=request_headers,
        )
        empty_response = response.status_code == 204 or not response.content
        if empty_response:
            response_body = EMPTY_BODY
        else:
            try:
                response_body = response.json()
            except ValueError as exc:
                raise RegistryClientError(
                    method, url, 502, "registry response is not canonical JSON"
                ) from exc
        try:
            verify_authenticated_response(
                headers=response.headers,
                expected_registries=self._expected_registries,
                request=authenticated,
                status=response.status_code,
                body=response_body,
            )
        except ValueError as exc:
            raise RegistryClientError(method, url, 502, str(exc)) from exc
        self._raise_for_status(
            method, url, response.status_code, response.text, expected
        )
        return None if empty_response else response_body

    async def get_health(self) -> HealthResponse:
        return self._parse_health(await self._request("GET", "/api/v1/system/health"))

    async def get_system_stats(self) -> SystemStatsResponse:
        return self._parse_system_stats(
            await self._request("GET", "/api/v1/system/stats")
        )

    async def list_publishers(
        self,
        *,
        principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if principal is not None:
            params.update(
                scheme=principal.scheme.value,
                identifier=principal.identifier,
            )
        return self._parse_publisher_list(
            await self._request("GET", "/publishers", params=params)
        )

    async def get_publisher(self, publisher_id: int) -> Publisher:
        return self._parse_publisher(
            await self._request("GET", f"/publishers/{publisher_id}")
        )

    async def publish_listing(
        self,
        listing: ListingRequest,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._publish_listing_request(
            listing,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            await self._request(
                "POST",
                "/listings",
                json=body,
                headers=headers,
                expected=(201,),
            ),
        )

    async def validate_publish_listing(
        self,
        request: ValidatePublishRequest,
    ) -> ValidatePublishResponse:
        data = await self._request(
            "POST",
            "/api/v1/listings/validate-publish",
            json=request.to_dict(),
            expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    async def get_filter_spec(self) -> FilterSpecResponse:
        return FilterSpecResponse.from_dict(await self._request("GET", "/filter-spec"))

    async def get_registry_descriptor(
        self,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> RegistryDescriptor:
        return RegistryDescriptor.model_validate(
            await self._request(
                "GET",
                "/.well-known/arkhai/registry-descriptor.json",
                headers=self._request_identity_headers(request_id, timestamp),
            )
        )

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
        params = self._listings_params(
            status=status,
            publisher=publisher,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return self._parse_listing_list(
            await self._request(
                "GET",
                "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

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
        data = await self._request("GET", f"/listings/{listing_id}")
        return self._parse_listing(
            data.get("listing", data) if isinstance(data, dict) else data
        )

    async def update_listing(
        self,
        listing_id: str,
        request: UpdateListingRequest,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._update_listing_request(
            listing_id,
            request,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            await self._request(
                "PUT",
                f"/listings/{listing_id}",
                json=body,
                headers=headers,
            ),
        )

    async def delete_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> None:
        headers = self._delete_listing_headers(
            listing_id,
            request_id=request_id,
            timestamp=timestamp,
        )
        await self._request(
            "DELETE",
            f"/listings/{listing_id}",
            headers=headers,
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
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._rotation_request(
            publisher_id,
            replacement_signer,
            nonce=nonce,
            overlap_seconds=overlap_seconds,
            expires_at=expires_at,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            await self._request(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations",
                json=body,
                headers=headers,
            ),
        )

    async def get_publisher_rotation(
        self,
        publisher_id: int,
        nonce: str,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._request(
                "GET",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}",
            ),
        )

    async def retire_publisher_identity(
        self,
        publisher_id: int,
        nonce: str,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        headers = self._retirement_headers(
            publisher_id,
            nonce,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            await self._request(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
                headers=headers,
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
        signer: Signer,
        caller_role: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> RegistryDescriptor:
        """Read a descriptor and verify possession of its advertised key."""

        path = "/.well-known/arkhai/registry-descriptor.json"
        request = cls._descriptor_bootstrap_request(
            signer=signer,
            caller_role=caller_role,
        )
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        ) as client:
            response = client.get(
                path,
                headers=authentication_headers(request),
            )
        return cls._verify_bootstrap_descriptor(
            response=response,
            request=request,
            url=f"{base_url.rstrip('/')}{path}",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = self._url(path)
        operation, resource = self._request_context(method, path)
        request_headers = dict(headers or {})
        request_body = (
            self._query_body(params, request_headers)
            if method.upper() == "GET"
            else (json if json is not None else EMPTY_BODY)
        )
        timestamp = request_headers.get(TIMESTAMP_HEADER)
        authenticated = authenticate_request(
            signer=self._signer,
            role=self._caller_role,
            method=method,
            operation=operation,
            resource=resource,
            body=request_body,
            request_id=request_headers.get(REQUEST_ID_HEADER),
            timestamp=int(timestamp) if timestamp is not None else None,
        )
        request_headers.update(authentication_headers(authenticated))
        response = self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=request_headers,
        )
        empty_response = response.status_code == 204 or not response.content
        if empty_response:
            response_body = EMPTY_BODY
        else:
            try:
                response_body = response.json()
            except ValueError as exc:
                raise RegistryClientError(
                    method, url, 502, "registry response is not canonical JSON"
                ) from exc
        try:
            verify_authenticated_response(
                headers=response.headers,
                expected_registries=self._expected_registries,
                request=authenticated,
                status=response.status_code,
                body=response_body,
            )
        except ValueError as exc:
            raise RegistryClientError(method, url, 502, str(exc)) from exc
        self._raise_for_status(
            method, url, response.status_code, response.text, expected
        )
        return None if empty_response else response_body

    def get_health(self) -> HealthResponse:
        return self._parse_health(self._request("GET", "/api/v1/system/health"))

    def get_system_stats(self) -> SystemStatsResponse:
        return self._parse_system_stats(self._request("GET", "/api/v1/system/stats"))

    def list_publishers(
        self,
        *,
        principal: Identity | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PublisherListResponse:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if principal is not None:
            params.update(
                scheme=principal.scheme.value,
                identifier=principal.identifier,
            )
        return self._parse_publisher_list(
            self._request("GET", "/publishers", params=params)
        )

    def get_publisher(self, publisher_id: int) -> Publisher:
        return self._parse_publisher(
            self._request("GET", f"/publishers/{publisher_id}")
        )

    def publish_listing(
        self,
        listing: ListingRequest,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._publish_listing_request(
            listing,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            self._request(
                "POST",
                "/listings",
                json=body,
                headers=headers,
                expected=(201,),
            ),
        )

    def validate_publish_listing(
        self,
        request: ValidatePublishRequest,
    ) -> ValidatePublishResponse:
        data = self._request(
            "POST",
            "/api/v1/listings/validate-publish",
            json=request.to_dict(),
            expected=(200,),
        )
        return ValidatePublishResponse.from_dict(data)

    def get_filter_spec(self) -> FilterSpecResponse:
        return FilterSpecResponse.from_dict(self._request("GET", "/filter-spec"))

    def get_registry_descriptor(
        self,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> RegistryDescriptor:
        return RegistryDescriptor.model_validate(
            self._request(
                "GET",
                "/.well-known/arkhai/registry-descriptor.json",
                headers=self._request_identity_headers(request_id, timestamp),
            )
        )

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
        params = self._listings_params(
            status=status,
            publisher=publisher,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return self._parse_listing_list(
            self._request(
                "GET",
                "/listings",
                params=params,
                headers=self._if_match_headers(etag),
            )
        )

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
        data = self._request("GET", f"/listings/{listing_id}")
        return self._parse_listing(
            data.get("listing", data) if isinstance(data, dict) else data
        )

    def update_listing(
        self,
        listing_id: str,
        request: UpdateListingRequest,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._update_listing_request(
            listing_id,
            request,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            self._request(
                "PUT",
                f"/listings/{listing_id}",
                json=body,
                headers=headers,
            ),
        )

    def delete_listing(
        self,
        listing_id: str,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> None:
        headers = self._delete_listing_headers(
            listing_id,
            request_id=request_id,
            timestamp=timestamp,
        )
        self._request(
            "DELETE",
            f"/listings/{listing_id}",
            headers=headers,
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
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        body, headers = self._rotation_request(
            publisher_id,
            replacement_signer,
            nonce=nonce,
            overlap_seconds=overlap_seconds,
            expires_at=expires_at,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            self._request(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations",
                json=body,
                headers=headers,
            ),
        )

    def get_publisher_rotation(
        self,
        publisher_id: int,
        nonce: str,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request(
                "GET",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}",
            ),
        )

    def retire_publisher_identity(
        self,
        publisher_id: int,
        nonce: str,
        *,
        request_id: str | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        headers = self._retirement_headers(
            publisher_id,
            nonce,
            request_id=request_id,
            timestamp=timestamp,
        )
        return cast(
            dict[str, Any],
            self._request(
                "POST",
                f"/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
                headers=headers,
            ),
        )
