"""The relay administration routes, without a web framework.

``RelayRouteService`` serves list, create, read, update, token rotation, and
enable and disable over the relay service, reporting a refusal as a
``ProvisioningRouteError``. Every relay route admits only the administrator:
relays are operator infrastructure, and no storefront administers them.

Deletion is deliberately absent. A relay carrying live port leases cannot
simply be removed: the proxies it carries outlive the row, and a deletion that
orphans leases loses the record of which ports on that rendezvous are bound.
Disable is the operator's answer to "stop using this relay".
"""

from __future__ import annotations

from compute_provisioning_contracts import (
    RelayCreate,
    RelayListResponse,
    RelayResponse,
    RelayTokenRotate,
    RelayUpdate,
)

from ..route_errors import ProvisioningRouteError
from .rebinding import RelayRebindingRefused
from .service import (
    UNSET,
    RelayEndpointConflictError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
    RelayView,
)


def _response(view: RelayView) -> RelayResponse:
    """The wire model built from the service view.

    The view is the type that structurally cannot carry a token; this only
    renames it for the wire.
    """
    return RelayResponse(**view.__dict__)


def _missing(relay_id: str) -> ProvisioningRouteError:
    return ProvisioningRouteError(404, f"Relay '{relay_id}' not found")


class RelayRouteService:
    def __init__(self, relays: RelayService) -> None:
        self._relays = relays

    def list_relays(self) -> RelayListResponse:
        return RelayListResponse(relays=[_response(v) for v in self._relays.list_relays()])

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
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def get_relay(self, relay_id: str) -> RelayResponse:
        try:
            return _response(self._relays.get_relay(relay_id))
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc

    def update_relay(self, relay_id: str, body: RelayUpdate) -> RelayResponse:
        fields = body.model_dump(exclude_unset=True)
        try:
            view = self._relays.update_relay(
                relay_id,
                label=fields.get("label", UNSET),
                relay_addr=body.relay_addr,
                relay_port=body.relay_port,
                vm_port_range_start=body.vm_port_range_start,
                vm_port_range_count=body.vm_port_range_count,
            )
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayEndpointConflictError as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayRebindingRefused as exc:
            # 409, not 422: the request is well-formed and would be valid once
            # the relay is drained. The message carries the drain sequence, so
            # it must reach the caller rather than becoming a 500.
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def rotate_token(self, relay_id: str, body: RelayTokenRotate) -> RelayResponse:
        try:
            view = self._relays.rotate_token(relay_id, body.token)
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc
        except RelayRebindingRefused as exc:
            raise ProvisioningRouteError(409, str(exc)) from exc
        except RelayValidationError as exc:
            raise ProvisioningRouteError(422, str(exc)) from exc
        return _response(view)

    def set_enabled(self, relay_id: str, enabled: bool) -> RelayResponse:
        try:
            return _response(self._relays.set_enabled(relay_id, enabled))
        except RelayNotFoundError as exc:
            raise _missing(relay_id) from exc


__all__ = ["RelayRouteService"]
