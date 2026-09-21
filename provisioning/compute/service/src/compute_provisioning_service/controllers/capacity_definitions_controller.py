"""Capacity-definitions controller.

    POST /api/v1/capacity/definitions/import   Reconcile a capacity-definitions document

The operator's submission path for the document the service can also mount at
startup. It always reconciles, because the operator has asked, and records no
digest, so a later startup still compares the mounted document with the one it
last reconciled itself.

Authentication is central, as for ``/api/v1/hosts/import``: the same kind of
act, an operator submitting inventory. The route lives here rather than on the
shared capacity router so a site authority that mounts that router without a
deployment story for documents does not acquire this surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv
from market_site import (
    CapacityDefinitionsImportRequest,
    CapacityDefinitionsImportResponse,
    CapacityLedgerService,
)

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.definition_documents import (
    reconcile_capacity_document,
)

router = APIRouter(prefix="/capacity/definitions", tags=["capacity"])


@cbv(router)
class CapacityDefinitionsController:
    def __init__(
        self,
        ledger: CapacityLedgerService = Depends(
            lambda: _container_module.resolved_capacity_ledger_service
        ),
        session_factory: Any = Depends(
            lambda: _container_module.resolved_session_factory
        ),
    ) -> None:
        self._ledger = ledger
        self._session_factory = session_factory

    @router.post(
        "/import",
        response_model=CapacityDefinitionsImportResponse,
        summary="Reconcile a capacity-definitions document",
    )
    def import_capacity_definitions(
        self, body: CapacityDefinitionsImportRequest
    ) -> CapacityDefinitionsImportResponse:
        """Upsert the declarations a top-level ``resources:`` list names.

        Each entry replaces the whole declaration it names; declarations the
        document does not name are left as they are, and entries equal to
        the stored declaration write nothing. Any problem, structural or one
        only stored state can decide, leaves the whole document unapplied:
        an applying import answers 422 with every problem, and
        ``validate_only`` answers 200 with the problems and the diff an
        import would produce, applying nothing either way.
        """
        with self._session_factory() as db:
            outcome = reconcile_capacity_document(db, self._ledger, body.yaml_text)
            applied = outcome.valid and not body.validate_only
            if applied:
                db.commit()
            else:
                db.rollback()
        result = CapacityDefinitionsImportResponse(
            applied=applied, diff=outcome.diff, problems=list(outcome.problems)
        )
        if not outcome.valid and not body.validate_only:
            raise HTTPException(status_code=422, detail=result.model_dump())
        return result

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
