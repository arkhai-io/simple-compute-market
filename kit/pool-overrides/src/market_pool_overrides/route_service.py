"""The override routes' handling, without a web framework.

Each storefront binds these three operations with its own router and its own
administrator authentication, so the kit carries no framework dependency and
makes no routing decision for the storefront. Every refusal is a
``PoolOverrideRouteError`` carrying the HTTP status to answer with.

Site and pool identifiers are operator-chosen strings with no character
restriction, so they travel in the body or query, never in a path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from market_pool_overrides.records import (
    PoolOverrideAddress,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideRecord,
    PoolOverrideResponse,
    PoolOverrideWriteResponse,
)
from market_pool_overrides.service import PoolOverrideRefused, PoolOverrideService


class PoolOverrideRouteError(Exception):
    """A refused request; ``status_code`` is the HTTP status to answer with."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _validation_detail(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]


class PoolOverrideRouteService:
    """Replace, read, and delete overrides on behalf of a storefront's routes.

    ``service`` is ``None`` when the storefront composed no override store;
    every operation then answers 503 rather than failing obscurely.
    """

    def __init__(self, service: PoolOverrideService | None) -> None:
        self._service = service

    def _require_service(self) -> PoolOverrideService:
        if self._service is None:
            raise PoolOverrideRouteError(503, "storefront pool overrides are unavailable")
        return self._service

    async def replace(
        self, body: PoolOverrideRecord | Mapping[str, Any]
    ) -> PoolOverrideWriteResponse:
        """Replace the whole override at the record's address.

        A body that is not a valid record is refused with 422. The service then
        refuses, before storing anything, an unconfigured site, a mode no market
        serves, or vocabulary or clauses that do not validate (422); a site that
        cannot answer usably (503, retryable); and a pool its live projection
        lacks (404).
        """
        service = self._require_service()
        if isinstance(body, PoolOverrideRecord):
            record = body
        else:
            try:
                record = PoolOverrideRecord.model_validate(body)
            except ValidationError as exc:
                raise PoolOverrideRouteError(422, _validation_detail(exc)) from exc
        try:
            result = await service.replace(record)
        except PoolOverrideRefused as exc:
            raise PoolOverrideRouteError(exc.status_code, exc.detail) from exc
        return PoolOverrideWriteResponse.model_validate(result)

    async def read(
        self,
        *,
        site_id: str | None = None,
        pool_id: str | None = None,
        offering_mode: str | None = None,
    ) -> PoolOverrideResponse | PoolOverrideListResponse:
        """With a whole address, that override (404 when absent); otherwise a
        list, optionally narrowed to a site or to one site's pool."""
        service = self._require_service()
        if site_id is not None and pool_id is not None and offering_mode is not None:
            address = self._address(site_id, pool_id, offering_mode)
            override = await service.get(address)
            if override is None:
                raise PoolOverrideRouteError(
                    404,
                    f"no override for site {site_id!r} pool {pool_id!r} "
                    f"mode {offering_mode!r}",
                )
            return PoolOverrideResponse.model_validate({"override": override})
        return PoolOverrideListResponse.model_validate(
            {"overrides": await service.list(site_id=site_id, pool_id=pool_id)}
        )

    async def delete(
        self,
        *,
        site_id: str | None,
        pool_id: str | None,
        offering_mode: str | None,
    ) -> PoolOverrideDeleteResponse:
        """Remove one override; idempotent. Requires the whole address, so a
        partial one can never delete more than was named."""
        service = self._require_service()
        if site_id is None or pool_id is None or offering_mode is None:
            raise PoolOverrideRouteError(
                400, "a delete names site_id, pool_id, and offering_mode"
            )
        address = self._address(site_id, pool_id, offering_mode)
        deleted = await service.delete(address)
        return PoolOverrideDeleteResponse(**address.model_dump(), deleted=deleted)

    @staticmethod
    def _address(site_id: str, pool_id: str, offering_mode: str) -> PoolOverrideAddress:
        try:
            return PoolOverrideAddress(
                site_id=site_id, pool_id=pool_id, offering_mode=offering_mode
            )
        except ValidationError as exc:
            raise PoolOverrideRouteError(400, _validation_detail(exc)) from exc


__all__ = ["PoolOverrideRouteError", "PoolOverrideRouteService"]
