"""The relay administration routes, bound to ``RelayRouteService``.

No per-route authentication dependency: the service authenticates every request
centrally against the route's contract, which for every relay route admits only
the administrator.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning.relays import RelayRouteService
from compute_provisioning.route_errors import require_composed
from compute_provisioning_contracts import (
    RelayCreate,
    RelayGrantKeyStage,
    RelayLeaseListResponse,
    RelayListResponse,
    RelayResponse,
    RelayStagedGrantKey,
    RelayTokenRotate,
    RelayUpdate,
)
from fastapi import APIRouter, Body, Depends, status

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


@router.get(
    "/{relay_id}/leases",
    response_model=RelayLeaseListResponse,
    summary="Read the ports a relay holds and has released",
)
def list_relay_leases(
    relay_id: str, service: RelayRouteService = Depends(_service)
) -> RelayLeaseListResponse:
    return routed(lambda: service.list_leases(relay_id))


@router.post(
    "/{relay_id}/grant-keys/stage",
    response_model=RelayStagedGrantKey,
    summary="Stage a relay's next grant-signing key",
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"schema": RelayGrantKeyStage.model_json_schema()}}
        }
    },
)
def stage_relay_grant_key(
    relay_id: str,
    # Taken as any JSON and validated by the route service, which refuses
    # without quoting the body: the framework's validation answer would quote
    # a private key back to the caller.
    payload: Any = Body(default=None),
    service: RelayRouteService = Depends(_service),
) -> RelayStagedGrantKey:
    return routed(lambda: service.stage_grant_key(relay_id, payload))


@router.post(
    "/{relay_id}/grant-keys/activate",
    response_model=RelayResponse,
    summary="Activate a relay's staged grant-signing key",
)
def activate_relay_grant_key(
    relay_id: str, service: RelayRouteService = Depends(_service)
) -> RelayResponse:
    return routed(lambda: service.activate_grant_key(relay_id))
