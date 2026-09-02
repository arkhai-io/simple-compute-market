"""Relay administration controller.

    GET    /api/v1/relays/                     List relays
    POST   /api/v1/relays/                     Create a relay
    GET    /api/v1/relays/{relay_id}           Relay details
    PATCH  /api/v1/relays/{relay_id}           Change location, window, or label
    POST   /api/v1/relays/{relay_id}/token     Rotate the admission token
    POST   /api/v1/relays/{relay_id}/enable    Enable
    POST   /api/v1/relays/{relay_id}/disable   Disable

Deletion is deliberately absent. A relay carrying live port leases cannot
simply be removed: the proxies it carries outlive the row, and a deletion that
orphans leases loses the record of which ports on that rendezvous are bound.
Disable is the operator's answer to "stop using this relay" until that
lifecycle question is settled.

No ``/admin`` prefix and no per-route authentication dependency, matching
``/api/v1/pools/`` and ``/api/v1/hosts/``: the provisioning boundary
authenticates its configured storefront principal and seller role centrally. A
caller that can write a pool can already set that pool's playbook path, which
is arbitrary playbook execution on every host in it, so administering a relay
is not a greater privilege than one already held.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_utils.cbv import cbv

from compute_provisioning import (
    RelayCreate,
    RelayListResponse,
    RelayResponse,
    RelayTokenRotate,
    RelayUpdate,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.relay_rebinding import (
    RelayRebindingRefused,
)
from compute_provisioning_service.services.relay_service import (
    UNSET,
    RelayEndpointConflictError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
)

router = APIRouter(prefix="/relays", tags=["relays"])


def _response(view: RelayView) -> RelayResponse:
    """Shared wire model built from the service view.

    The view is the type that structurally cannot carry a token; this only
    renames it for the wire.
    """
    return RelayResponse(**view.__dict__)


@cbv(router)
class RelayController:
    def __init__(
        self,
        relay_service: RelayService = Depends(
            lambda: _container_module.resolved_relay_service
        ),
    ) -> None:
        self._relays = relay_service

    @router.get("/", response_model=RelayListResponse)
    def list_relays(self) -> RelayListResponse:
        return RelayListResponse(
            relays=[_response(v) for v in self._relays.list_relays()]
        )

    @router.post("/", response_model=RelayResponse, status_code=status.HTTP_201_CREATED)
    def create_relay(self, body: RelayCreate) -> RelayResponse:
        try:
            view = self._relays.create_relay(
                relay_id=body.id,
                label=body.label,
                relay_addr=body.relay_addr,
                relay_port=body.relay_port,
                vm_port_range_start=body.vm_port_range_start,
                vm_port_range_count=body.vm_port_range_count,
                token=body.token,
                enabled=body.enabled,
            )
        except RelayEndpointConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except RelayValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        return _response(view)

    @router.get("/{relay_id}", response_model=RelayResponse)
    def get_relay(self, relay_id: str) -> RelayResponse:
        return _response(self._get(relay_id))

    @router.patch("/{relay_id}", response_model=RelayResponse)
    def update_relay(self, relay_id: str, body: RelayUpdate) -> RelayResponse:
        try:
            fields = body.model_dump(exclude_unset=True)
            view = self._relays.update_relay(
                relay_id,
                label=fields.get("label", UNSET),
                relay_addr=body.relay_addr,
                relay_port=body.relay_port,
                vm_port_range_start=body.vm_port_range_start,
                vm_port_range_count=body.vm_port_range_count,
            )
        except RelayNotFoundError:
            raise self._not_found(relay_id)
        except RelayEndpointConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except RelayRebindingRefused as exc:
            # 409, not 422: the request is well-formed and would be valid once
            # the relay is drained. The message carries the drain sequence, so
            # it must reach the caller rather than becoming a 500.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except RelayValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        return _response(view)

    @router.post("/{relay_id}/token", response_model=RelayResponse)
    def rotate_token(self, relay_id: str, body: RelayTokenRotate) -> RelayResponse:
        try:
            view = self._relays.rotate_token(relay_id, body.token)
        except RelayNotFoundError:
            raise self._not_found(relay_id)
        except RelayValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        return _response(view)

    @router.post("/{relay_id}/enable", response_model=RelayResponse)
    def enable_relay(self, relay_id: str) -> RelayResponse:
        return self._set_enabled(relay_id, True)

    @router.post("/{relay_id}/disable", response_model=RelayResponse)
    def disable_relay(self, relay_id: str) -> RelayResponse:
        return self._set_enabled(relay_id, False)

    def _set_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        try:
            return _response(self._relays.set_enabled(relay_id, enabled))
        except RelayNotFoundError:
            raise self._not_found(relay_id)

    def _get(self, relay_id: str) -> RelayView:
        try:
            return self._relays.get_relay(relay_id)
        except RelayNotFoundError:
            raise self._not_found(relay_id)

    @staticmethod
    def _not_found(relay_id: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Relay '{relay_id}' not found",
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
