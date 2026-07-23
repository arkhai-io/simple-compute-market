"""Resource pool controller.

Handles all pool-registry operations:

    GET    /api/v1/pools/                 List resource pools
    POST   /api/v1/pools/                 Create a resource pool
    GET    /api/v1/pools/{pool_id}        Pool details
    PUT    /api/v1/pools/{pool_id}        Replace pool fields (full desired state)
    PATCH  /api/v1/pools/{pool_id}        Partial-update pool fields
    DELETE /api/v1/pools/{pool_id}        Disable a pool (soft-delete)
    POST   /api/v1/pools/import           Bulk-import from pool-definitions YAML
    POST   /api/v1/pools/validate         Dry-run the same import, no writes

No ``/admin`` prefix and no per-route auth dependency: the provisioning
service has exactly one caller (the storefront) behind one shared secret
for every route, gated by StorefrontAuthMiddleware — unlike the storefront
itself, which serves multiple distinct audiences and uses ``/admin/`` to
separate one of them out. This mirrors ``/api/v1/hosts/``, the other
fully-operator-owned resource in this service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module
from compute_provisioning import (
    PoolCreate,
    PoolImportRequest,
    PoolImportResponse,
    PoolListResponse,
    PoolResponse,
    PoolReplace,
    PoolUpdate,
    PoolValidateResponse,
)
from market_resource_pools import (
    PoolAlreadyExistsError,
    PoolNotFoundError,
    PoolValidationError,
    ResourcePoolService,
)

router = APIRouter(prefix="/pools", tags=["pools"])


@cbv(router)
class PoolController:
    def __init__(
        self,
        pool_service: ResourcePoolService = Depends(
            lambda: _container_module.resolved_resource_pool_service
        ),
    ) -> None:
        self._pools = pool_service

    # ------------------------------------------------------------------
    # List / get
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=PoolListResponse,
        summary="List resource pools",
    )
    def list_pools(self, include_disabled: bool = True) -> PoolListResponse:
        """Return all resource pools.

        ``include_disabled`` defaults to True (unlike hosts) since pools are
        few and operators generally want to see disabled ones when auditing.
        """
        pools = self._pools.list_pools(enabled_only=not include_disabled)
        pool_models = [PoolResponse.model_validate(p) for p in pools]
        return PoolListResponse(pools=pool_models, total=len(pool_models))

    @router.get(
        "/export",
        response_class=Response,
        summary="Export canonical resource-pool YAML",
    )
    def export_pools(self) -> Response:
        return Response(
            content=self._pools.export_pools_yaml(),
            media_type="application/yaml",
        )

    @router.get(
        "/{pool_id}",
        response_model=PoolResponse,
        summary="Get pool details",
    )
    def get_pool(self, pool_id: str) -> PoolResponse:
        pool = self._pools.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail=f"Pool '{pool_id}' not found")
        return PoolResponse.model_validate(pool)

    # ------------------------------------------------------------------
    # Create / update / disable
    # ------------------------------------------------------------------

    @router.post(
        "/",
        response_model=PoolResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a resource pool",
    )
    def create_pool(self, body: PoolCreate) -> PoolResponse:
        try:
            pool = self._pools.create_pool(body)
        except PoolAlreadyExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PoolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PoolResponse.model_validate(pool)

    @router.put(
        "/{pool_id}",
        response_model=PoolResponse,
        summary="Replace pool fields (send the full desired state)",
    )
    def replace_pool(self, pool_id: str, body: PoolReplace) -> PoolResponse:
        try:
            pool = self._pools.replace_pool(pool_id, body)
        except PoolNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PoolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PoolResponse.model_validate(pool)

    @router.patch(
        "/{pool_id}",
        response_model=PoolResponse,
        summary="Partial-update pool fields",
    )
    def patch_pool(self, pool_id: str, body: PoolUpdate) -> PoolResponse:
        try:
            pool = self._pools.update_pool(pool_id, body)
        except PoolNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PoolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PoolResponse.model_validate(pool)

    @router.delete(
        "/{pool_id}",
        response_model=PoolResponse,
        summary="Disable a pool (soft-delete)",
    )
    def disable_pool(self, pool_id: str) -> PoolResponse:
        """Set ``enabled=False`` on a pool.

        Pools are never hard-deleted so that ``hosts.pool_id`` and any
        future settlement records referencing this id remain resolvable.
        """
        try:
            pool = self._pools.disable_pool(pool_id)
        except PoolNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PoolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PoolResponse.model_validate(pool)

    # ------------------------------------------------------------------
    # YAML import / validate
    # ------------------------------------------------------------------

    @router.post(
        "/import",
        response_model=PoolImportResponse,
        summary="Bulk-import pool definitions from YAML",
    )
    def import_pools(self, body: PoolImportRequest) -> PoolImportResponse:
        """Upsert pools from a top-level ``pools:`` list; each entry needs
        ``id``, ``label``, ``provider``, and optionally ``policy_tags`` /
        ``provider_config``.

        Idempotent: re-importing the same YAML produces an all-unchanged
        diff. Pools present in the DB but absent from the YAML are
        disabled, never hard-deleted.
        """
        try:
            diff = self._pools.import_pools(body.yaml_text, validate_only=False)
        except PoolValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PoolImportResponse(diff=diff, applied=True)

    @router.post(
        "/validate",
        response_model=PoolValidateResponse,
        summary="Dry-run a pool-definitions import without writing",
    )
    def validate_pools(self, body: PoolImportRequest) -> PoolValidateResponse:
        """Return all detectable document problems without applying writes."""
        return self._pools.validate_pools(body.yaml_text)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
