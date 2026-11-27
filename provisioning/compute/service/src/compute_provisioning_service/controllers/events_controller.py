"""The administrator's event routes, bound over the eventing component's service.

- ``GET /events``: recorded events in sequence order, filtered by ``kind``,
  ``severity``, ``subject`` or ``reference`` (each ``<type>:<id>``), past
  ``after``, ``limit`` at a time; an invalid filter is 422 ``invalid_query``.
- ``GET /events/deliveries``: each consumer destination's delivery state.
- ``POST /events/destinations/{destination}/resume``: resume a parked
  destination, the body's ``consumer`` naming it where two consumers share the
  name; 404 ``unknown_destination``, 409 ``ambiguous_destination`` or
  ``destination_retired``.

A refusal answers its status with ``{"code", "detail"}``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from compute_provisioning.route_errors import require_composed
from compute_provisioning_contracts import (
    EventDeliveriesResponse,
    EventDestinationResumeResponse,
    EventListResponse,
)
from eventing import EventService, EventServiceError
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from compute_provisioning_service.controllers.route_errors import routed


class EventDestinationResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer: str | None = None


def _refusal(error: EventServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code, content={"code": error.code, "detail": error.detail}
    )


def make_events_router(event_service: Callable[[], EventService | None]) -> APIRouter:
    """The ``/events`` router over an accessor of the composed event service."""
    router = APIRouter(prefix="/events", tags=["events"])

    def service() -> EventService:
        return routed(lambda: require_composed(event_service, "the event service"))

    @router.get("", response_model=EventListResponse, summary="List recorded events (admin)")
    def list_events(
        kind: str | None = Query(default=None),
        severity: str | None = Query(default=None),
        subject: str | None = Query(default=None),
        reference: str | None = Query(default=None),
        after: int | None = Query(default=None),
        limit: int = Query(default=100),
    ) -> Any:
        try:
            return service().list_events(
                kind=kind, severity=severity, subject=subject, reference=reference,
                after=after, limit=limit,
            )
        except EventServiceError as error:
            return _refusal(error)

    @router.get(
        "/deliveries",
        response_model=EventDeliveriesResponse,
        summary="Each consumer destination's delivery state (admin)",
    )
    def event_deliveries() -> Any:
        return service().deliveries()

    @router.post(
        "/destinations/{destination}/resume",
        response_model=EventDestinationResumeResponse,
        summary="Resume a parked event destination (admin)",
    )
    def resume_destination(destination: str, body: EventDestinationResumeRequest) -> Any:
        try:
            return service().resume(destination, consumer=body.consumer)
        except EventServiceError as error:
            return _refusal(error)

    return router


__all__ = ["EventDestinationResumeRequest", "make_events_router"]
