"""Typed resource-pool methods over a service client's generic transport.

A pool authority is hosted by a service that has its own client, and that
client carries no pool vocabulary. These methods wrap any transport offering
``authenticated_request(method, path, body, *, request_id, route)``: each
request names its route declaration from ``market_resource_pools_contracts``,
the same declarations the hosting service assembles into the table its request
authentication reads, so the signed operation and resource cannot diverge.
``ResourcePoolClient`` wraps an async transport and ``SyncResourcePoolClient`` a
sync one, with identical method signatures.
"""

from __future__ import annotations

from typing import Any, Protocol

from market_resource_pools_contracts import (
    PoolCreate,
    PoolImportRequest,
    PoolImportResponse,
    PoolListResponse,
    PoolReplace,
    PoolResponse,
    PoolUpdate,
    PoolValidateResponse,
    pool_route,
)


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, *args: Any, **kwargs: Any) -> Any: ...


# Each operation as (method, path, route declaration, body); the body is
# omitted for a read, so the transport signs its own empty-body sentinel.
def _list() -> tuple[tuple, dict[str, Any]]:
    return ("GET", "/api/v1/pools/"), {"route": pool_route("provisioning_pools_list")}


def _get(pool_id: str) -> tuple[tuple, dict[str, Any]]:
    return ("GET", f"/api/v1/pools/{pool_id}"), {"route": pool_route("provisioning_pool_get")}


def _export() -> tuple[tuple, dict[str, Any]]:
    return ("GET", "/api/v1/pools/export"), {"route": pool_route("provisioning_pools_export")}


def _create(body: PoolCreate) -> tuple[tuple, dict[str, Any]]:
    return ("POST", "/api/v1/pools/", body), {"route": pool_route("provisioning_pool_create")}


def _replace(pool_id: str, body: PoolReplace) -> tuple[tuple, dict[str, Any]]:
    return ("PUT", f"/api/v1/pools/{pool_id}", body), {
        "route": pool_route("provisioning_pool_replace")
    }


def _patch(pool_id: str, body: PoolUpdate) -> tuple[tuple, dict[str, Any]]:
    return ("PATCH", f"/api/v1/pools/{pool_id}", body), {
        "route": pool_route("provisioning_pool_update")
    }


def _delete(pool_id: str) -> tuple[tuple, dict[str, Any]]:
    return ("DELETE", f"/api/v1/pools/{pool_id}", {}), {
        "route": pool_route("provisioning_pool_disable")
    }


def _import(yaml_text: str) -> tuple[tuple, dict[str, Any]]:
    return ("POST", "/api/v1/pools/import", PoolImportRequest(yaml_text=yaml_text)), {
        "route": pool_route("provisioning_pools_import")
    }


def _validate(yaml_text: str) -> tuple[tuple, dict[str, Any]]:
    return ("POST", "/api/v1/pools/validate", PoolImportRequest(yaml_text=yaml_text)), {
        "route": pool_route("provisioning_pools_validate")
    }


class ResourcePoolClient:
    """Resource-pool administration over an async signing transport."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def _call(self, call: tuple[tuple, dict[str, Any]], request_id: str | None) -> Any:
        args, kwargs = call
        return await self._transport.authenticated_request(
            *args, **kwargs, request_id=request_id
        )

    async def list_pools(self, *, request_id: str | None = None) -> PoolListResponse:
        return PoolListResponse.model_validate(await self._call(_list(), request_id))

    async def get_pool(self, pool_id: str, *, request_id: str | None = None) -> PoolResponse:
        return PoolResponse.model_validate(await self._call(_get(pool_id), request_id))

    async def export_pools_yaml(self, *, request_id: str | None = None) -> str:
        """The pool authority's canonical YAML document."""
        return await self._call(_export(), request_id)

    async def create_pool(
        self, body: PoolCreate, *, request_id: str | None = None
    ) -> PoolResponse:
        return PoolResponse.model_validate(await self._call(_create(body), request_id))

    async def replace_pool(
        self, pool_id: str, body: PoolReplace, *, request_id: str | None = None
    ) -> PoolResponse:
        return PoolResponse.model_validate(
            await self._call(_replace(pool_id, body), request_id)
        )

    async def patch_pool(
        self, pool_id: str, body: PoolUpdate, *, request_id: str | None = None
    ) -> PoolResponse:
        return PoolResponse.model_validate(await self._call(_patch(pool_id, body), request_id))

    async def delete_pool(self, pool_id: str, *, request_id: str | None = None) -> PoolResponse:
        """Disable a pool; a pool is never hard-deleted."""
        return PoolResponse.model_validate(await self._call(_delete(pool_id), request_id))

    async def import_pools(
        self, yaml_text: str, *, request_id: str | None = None
    ) -> PoolImportResponse:
        return PoolImportResponse.model_validate(
            await self._call(_import(yaml_text), request_id)
        )

    async def validate_pools(
        self, yaml_text: str, *, request_id: str | None = None
    ) -> PoolValidateResponse:
        return PoolValidateResponse.model_validate(
            await self._call(_validate(yaml_text), request_id)
        )


class SyncResourcePoolClient:
    """Resource-pool administration over a sync signing transport."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    def _call(self, call: tuple[tuple, dict[str, Any]], request_id: str | None) -> Any:
        args, kwargs = call
        return self._transport.authenticated_request(*args, **kwargs, request_id=request_id)

    def list_pools(self, *, request_id: str | None = None) -> PoolListResponse:
        return PoolListResponse.model_validate(self._call(_list(), request_id))

    def get_pool(self, pool_id: str, *, request_id: str | None = None) -> PoolResponse:
        return PoolResponse.model_validate(self._call(_get(pool_id), request_id))

    def export_pools_yaml(self, *, request_id: str | None = None) -> str:
        """The pool authority's canonical YAML document."""
        return self._call(_export(), request_id)

    def create_pool(self, body: PoolCreate, *, request_id: str | None = None) -> PoolResponse:
        return PoolResponse.model_validate(self._call(_create(body), request_id))

    def replace_pool(
        self, pool_id: str, body: PoolReplace, *, request_id: str | None = None
    ) -> PoolResponse:
        return PoolResponse.model_validate(self._call(_replace(pool_id, body), request_id))

    def patch_pool(
        self, pool_id: str, body: PoolUpdate, *, request_id: str | None = None
    ) -> PoolResponse:
        return PoolResponse.model_validate(self._call(_patch(pool_id, body), request_id))

    def delete_pool(self, pool_id: str, *, request_id: str | None = None) -> PoolResponse:
        """Disable a pool; a pool is never hard-deleted."""
        return PoolResponse.model_validate(self._call(_delete(pool_id), request_id))

    def import_pools(self, yaml_text: str, *, request_id: str | None = None) -> PoolImportResponse:
        return PoolImportResponse.model_validate(self._call(_import(yaml_text), request_id))

    def validate_pools(
        self, yaml_text: str, *, request_id: str | None = None
    ) -> PoolValidateResponse:
        return PoolValidateResponse.model_validate(self._call(_validate(yaml_text), request_id))


__all__ = ["ResourcePoolClient", "SyncResourcePoolClient"]
