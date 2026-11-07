"""Typed pool-override methods over a storefront client's generic transport.

The core storefront client carries no market's vocabulary, so these methods wrap
its market-neutral ``authenticated_request``. ``PoolOverrideClient`` wraps the
async client and ``SyncPoolOverrideClient`` the sync one, with identical method
signatures. Resources come from ``contract``, the same module the storefront's
identity middleware binds them with.
"""

from __future__ import annotations

from typing import Any, Protocol

from market_pool_overrides.contract import (
    DELETE_OPERATION,
    GET_OPERATION,
    LIST_OPERATION,
    POOL_OVERRIDES_PATH,
    PUT_OPERATION,
    address_resource,
    read_query,
    read_resource,
)
from market_pool_overrides.records import (
    PoolOverride,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideRecord,
    PoolOverrideWriteResponse,
)


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _record_body(record: PoolOverrideRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, PoolOverrideRecord):
        return record.model_dump(exclude_none=True)
    if not isinstance(record, dict):
        raise TypeError("record must be a PoolOverrideRecord or a dict")
    return record


def _list_query(site_id: str | None, pool_id: str | None) -> dict[str, str]:
    items = [(name, value) for name, value in (("site_id", site_id), ("pool_id", pool_id))
             if value is not None]
    return read_query(items)


def _put(record: PoolOverrideRecord | dict[str, Any]) -> tuple[tuple, dict[str, Any]]:
    body = _record_body(record)
    resource = address_resource(body.get("site_id"), body.get("pool_id"), body.get("offering_mode"))
    return ("PUT", POOL_OVERRIDES_PATH), {
        "role": "admin", "operation": PUT_OPERATION, "resource": resource, "body": body,
    }


def _get(site_id: str, pool_id: str, offering_mode: str) -> tuple[tuple, dict[str, Any]]:
    query = read_query(
        [("site_id", site_id), ("pool_id", pool_id), ("offering_mode", offering_mode)]
    )
    return ("GET", POOL_OVERRIDES_PATH), {
        "role": "admin", "operation": GET_OPERATION, "resource": read_resource(query),
        "params": query,
    }


def _list(site_id: str | None, pool_id: str | None) -> tuple[tuple, dict[str, Any]]:
    query = _list_query(site_id, pool_id)
    return ("GET", POOL_OVERRIDES_PATH), {
        "role": "admin", "operation": LIST_OPERATION, "resource": read_resource(query),
        "params": query or None,
    }


def _delete(site_id: str, pool_id: str, offering_mode: str) -> tuple[tuple, dict[str, Any]]:
    query = {"site_id": site_id, "pool_id": pool_id, "offering_mode": offering_mode}
    return ("DELETE", POOL_OVERRIDES_PATH), {
        "role": "admin", "operation": DELETE_OPERATION,
        "resource": address_resource(site_id, pool_id, offering_mode), "params": query,
    }


class PoolOverrideClient:
    """Pool-override methods over an async storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    async def put_pool_override(
        self, record: PoolOverrideRecord | dict[str, Any], *, request_id: str | None = None
    ) -> PoolOverrideWriteResponse:
        """Replace the whole override at ``record``'s address.

        Refused with 422 for an unconfigured site, a mode no market serves, or
        vocabulary or clauses that do not validate; with a retryable 503 when the
        site cannot answer usably; and with 404 when its live projection lacks
        the pool. An infeasible shape is reported, not refused.
        """
        args, kwargs = _put(record)
        return PoolOverrideWriteResponse.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    async def get_pool_override(
        self, site_id: str, pool_id: str, offering_mode: str, *, request_id: str | None = None
    ) -> PoolOverride:
        args, kwargs = _get(site_id, pool_id, offering_mode)
        payload = await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        return PoolOverride.model_validate(payload["override"])

    async def list_pool_overrides(
        self, *, site_id: str | None = None, pool_id: str | None = None,
        request_id: str | None = None,
    ) -> PoolOverrideListResponse:
        args, kwargs = _list(site_id, pool_id)
        return PoolOverrideListResponse.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    async def delete_pool_override(
        self, site_id: str, pool_id: str, offering_mode: str, *, request_id: str | None = None
    ) -> PoolOverrideDeleteResponse:
        """Delete one override; ``deleted`` is false when none existed."""
        args, kwargs = _delete(site_id, pool_id, offering_mode)
        return PoolOverrideDeleteResponse.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


class SyncPoolOverrideClient:
    """Pool-override methods over a sync storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    def put_pool_override(
        self, record: PoolOverrideRecord | dict[str, Any], *, request_id: str | None = None
    ) -> PoolOverrideWriteResponse:
        """Replace the whole override at ``record``'s address; see
        ``PoolOverrideClient.put_pool_override``."""
        args, kwargs = _put(record)
        return PoolOverrideWriteResponse.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    def get_pool_override(
        self, site_id: str, pool_id: str, offering_mode: str, *, request_id: str | None = None
    ) -> PoolOverride:
        args, kwargs = _get(site_id, pool_id, offering_mode)
        payload = self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        return PoolOverride.model_validate(payload["override"])

    def list_pool_overrides(
        self, *, site_id: str | None = None, pool_id: str | None = None,
        request_id: str | None = None,
    ) -> PoolOverrideListResponse:
        args, kwargs = _list(site_id, pool_id)
        return PoolOverrideListResponse.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    def delete_pool_override(
        self, site_id: str, pool_id: str, offering_mode: str, *, request_id: str | None = None
    ) -> PoolOverrideDeleteResponse:
        """Delete one override; ``deleted`` is false when none existed."""
        args, kwargs = _delete(site_id, pool_id, offering_mode)
        return PoolOverrideDeleteResponse.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


def pool_override_statuses(status: Any) -> list[dict[str, Any]] | None:
    """The ``pool_overrides`` entries of a storefront's system status, if reported.

    The generic status model does not declare the field; a storefront that
    composes overrides reports it, and it arrives in the response's ``extra``.
    """
    extra = getattr(status, "extra", None) or {}
    return extra.get("pool_overrides")


__all__ = ["PoolOverrideClient", "SyncPoolOverrideClient", "pool_override_statuses"]
