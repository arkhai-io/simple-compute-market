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
from pydantic import BaseModel, Field

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.relay_service import (
    UNSET,
    RelayEndpointConflictError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
)

router = APIRouter(prefix="/relays", tags=["relays"])


class RelayResponse(BaseModel):
    """A relay as callers see it.

    ``token_configured`` rather than the token. An operator needs to know
    whether a relay is usable; nothing needs to read back a credential it
    supplied, and a field that is never returned cannot leak through a
    serializer someone adds later.
    """

    id: str
    label: str | None = None
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    enabled: bool
    token_configured: bool

    @classmethod
    def of(cls, view: RelayView) -> "RelayResponse":
        return cls(**view.__dict__)


class RelayListResponse(BaseModel):
    relays: list[RelayResponse]


class RelayCreate(BaseModel):
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    id: str | None = None
    label: str | None = None
    token: str | None = None
    enabled: bool = True


class RelayUpdate(BaseModel):
    """Partial update. An omitted field is unchanged.

    No token field: rotation is its own operation, so that changing a label
    cannot carry a credential along with it and so that a rotation is
    distinguishable in an audit trail from an ordinary edit.
    """

    label: str | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    vm_port_range_start: int | None = None
    vm_port_range_count: int | None = None


class RelayTokenRotate(BaseModel):
    token: str = Field(min_length=1)


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
            relays=[RelayResponse.of(v) for v in self._relays.list_relays()]
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
        return RelayResponse.of(view)

    @router.get("/{relay_id}", response_model=RelayResponse)
    def get_relay(self, relay_id: str) -> RelayResponse:
        return RelayResponse.of(self._get(relay_id))

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
        except RelayValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        return RelayResponse.of(view)

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
        return RelayResponse.of(view)

    @router.post("/{relay_id}/enable", response_model=RelayResponse)
    def enable_relay(self, relay_id: str) -> RelayResponse:
        return self._set_enabled(relay_id, True)

    @router.post("/{relay_id}/disable", response_model=RelayResponse)
    def disable_relay(self, relay_id: str) -> RelayResponse:
        return self._set_enabled(relay_id, False)

    def _set_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        try:
            return RelayResponse.of(self._relays.set_enabled(relay_id, enabled))
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
