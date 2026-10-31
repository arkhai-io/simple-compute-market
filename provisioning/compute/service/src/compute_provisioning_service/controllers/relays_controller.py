"""The relay administration routes, bound to ``RelayRouteService``.

No per-route authentication dependency: the service authenticates every request
centrally against the route's contract, which for every relay route admits only
the administrator.
"""

from __future__ import annotations

from compute_provisioning.relays import RelayRouteService
from compute_provisioning.route_errors import require_composed
from compute_provisioning_contracts import (
    RelayCreate,
    RelayListResponse,
    RelayResponse,
    RelayTokenRotate,
    RelayUpdate,
)
from fastapi import APIRouter, Depends, status

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed

router = APIRouter(prefix="/relays", tags=["relays"])


def _service() -> RelayRouteService:
    return routed(
        lambda: RelayRouteService(
            require_composed(
                lambda: _container_module.resolved_relay_service, "relay administration"
            )
        )
    )


@router.get("/", response_model=RelayListResponse, summary="List relays")
def list_relays(service: RelayRouteService = Depends(_service)) -> RelayListResponse:
    return service.list_relays()


@router.post(
    "/", response_model=RelayResponse, status_code=status.HTTP_201_CREATED, summary="Create a relay"
)
def create_relay(body: RelayCreate, service: RelayRouteService = Depends(_service)) -> RelayResponse:
    return routed(lambda: service.create_relay(body))


@router.get("/{relay_id}", response_model=RelayResponse, summary="Get relay details")
def get_relay(relay_id: str, service: RelayRouteService = Depends(_service)) -> RelayResponse:
    return routed(lambda: service.get_relay(relay_id))


@router.patch("/{relay_id}", response_model=RelayResponse, summary="Change a relay's location, window, or label")
def update_relay(
    relay_id: str, body: RelayUpdate, service: RelayRouteService = Depends(_service)
) -> RelayResponse:
    return routed(lambda: service.update_relay(relay_id, body))


@router.post("/{relay_id}/token", response_model=RelayResponse, summary="Rotate a relay's admission token")
def rotate_token(
    relay_id: str, body: RelayTokenRotate, service: RelayRouteService = Depends(_service)
) -> RelayResponse:
    return routed(lambda: service.rotate_token(relay_id, body))


@router.post("/{relay_id}/enable", response_model=RelayResponse, summary="Enable a relay")
def enable_relay(relay_id: str, service: RelayRouteService = Depends(_service)) -> RelayResponse:
    return routed(lambda: service.set_enabled(relay_id, True))


@router.post("/{relay_id}/disable", response_model=RelayResponse, summary="Disable a relay")
def disable_relay(relay_id: str, service: RelayRouteService = Depends(_service)) -> RelayResponse:
    return routed(lambda: service.set_enabled(relay_id, False))
